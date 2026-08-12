import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QFrame, QMessageBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QCloseEvent

from .. import __version__
from ..audio import record_command, unique_path
from ..constants import ICON_PATH, WHISPER_BIN
from ..config import (
    load_config, get_monitor, get_mic, get_last_output_dir,
    save_last_output_dir, get_initial_prompt, get_replacements,
)
from ..worker import WhisperThread
from ..remote import RemoteWhisperThread
from ..live import LiveTranscriber
from ..live_remote import RemoteLiveTranscriber
from .styles import STYLE
from .settings_dialog import SettingsDialog
from .live_panel import LivePanel

#: Deixa margem para o sufixo "-2" e para a extensão dentro do limite de 255
#: bytes por componente de caminho da maioria dos sistemas de arquivos Linux.
MAX_NAME_LEN = 200

#: Tempo dado ao ffmpeg para falhar de forma visível (dispositivo inexistente,
#: destino sem permissão) antes de a interface confirmar que está gravando.
FFMPEG_CHECK_MS = 1200


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[/\\<>:"|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    name = name[:MAX_NAME_LEN].strip(". ")
    return name or datetime.now().strftime("gravacao-%Y-%m-%d-%H%M%S")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.recording_process: subprocess.Popen | None = None
        self.whisper_thread: WhisperThread | RemoteWhisperThread | None = None
        self.live_transcriber: LiveTranscriber | RemoteLiveTranscriber | None = None
        # Threads de transcrição ao vivo em vias de encerrar, mas ainda não
        # confirmaram via `finished` — ver _stop_live_transcriber().
        self._retiring_threads: list[LiveTranscriber | RemoteLiveTranscriber] = []
        self.audio_path = ""
        self.txt_path = ""
        self.log_path = ""
        self._ffmpeg_log: str = ""
        self._started_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setWindowTitle("Alex-Transcritor")
        self.setMinimumSize(380, 430)
        self.resize(380, 430)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(0)

        root.addWidget(self._make_title())
        root.addSpacing(14)
        root.addWidget(self._make_separator())
        root.addSpacing(16)
        root.addLayout(self._make_filename_section())
        root.addSpacing(12)
        root.addLayout(self._make_directory_section())
        root.addSpacing(18)
        root.addLayout(self._make_controls_section())
        root.addSpacing(14)
        root.addWidget(self._make_status_label())
        root.addSpacing(6)
        root.addWidget(self._make_live_panel())
        root.addSpacing(10)
        root.addWidget(self._make_progress_bar())
        root.addSpacing(10)
        root.addWidget(self._make_file_buttons())
        root.addStretch(1)
        root.addWidget(self._make_version_label())

    def _make_title(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # Spacer invisível com mesma largura do botão para manter o título centralizado
        spacer = QWidget()
        spacer.setFixedWidth(28)

        title = QLabel("ALEX-TRANSCRITOR")
        title.setObjectName("label_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_settings = QPushButton("⚙")
        btn_settings.setObjectName("btn_settings")
        btn_settings.setFixedSize(28, 28)
        btn_settings.setToolTip("Configurações")
        btn_settings.clicked.connect(self._open_settings)

        row.addWidget(spacer)
        row.addWidget(title, 1)
        row.addWidget(btn_settings)
        return container

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        return sep

    def _make_filename_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(5)
        lbl = QLabel("NOME DO ARQUIVO")
        lbl.setObjectName("label_field")
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("ex: aula-01 (vazio = data e hora)")
        self.input_name.setMaxLength(MAX_NAME_LEN)
        layout.addWidget(lbl)
        layout.addWidget(self.input_name)
        return layout

    def _make_directory_section(self) -> QVBoxLayout:
        outer = QVBoxLayout()
        outer.setSpacing(5)
        lbl = QLabel("DIRETÓRIO DE SAÍDA")
        lbl.setObjectName("label_field")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.input_dir = QLineEdit()
        self.input_dir.setText(get_last_output_dir())
        btn_dir = QPushButton("…")
        btn_dir.setObjectName("btn_dir")
        btn_dir.setFixedWidth(42)
        btn_dir.clicked.connect(self._choose_dir)
        row.addWidget(self.input_dir)
        row.addWidget(btn_dir)
        outer.addWidget(lbl)
        outer.addLayout(row)
        return outer

    def _make_controls_section(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_record = QPushButton("⏺  Gravar")
        self.btn_record.setObjectName("btn_record")
        self.btn_record.clicked.connect(self._start_recording)
        self.btn_stop = QPushButton("⏹  Parar")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_clicked)
        row.addWidget(self.btn_record)
        row.addWidget(self.btn_stop)
        return row

    def _make_status_label(self) -> QLabel:
        self.lbl_status = QLabel("Aguardando...")
        self.lbl_status.setObjectName("label_status")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        return self.lbl_status

    def _make_live_panel(self) -> LivePanel:
        self.live_panel = LivePanel()
        self.live_panel.hide()
        return self.live_panel

    def _make_progress_bar(self) -> QProgressBar:
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        return self.progress

    def _make_file_buttons(self) -> QWidget:
        self.widget_files = QWidget()
        row = QHBoxLayout(self.widget_files)
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        self.btn_open_audio = QPushButton("🎵  Áudio")
        self.btn_open_audio.setObjectName("btn_file")
        self.btn_open_audio.clicked.connect(lambda: self._open_file(self.audio_path))

        self.btn_open_text = QPushButton("📄  Texto")
        self.btn_open_text.setObjectName("btn_file")
        self.btn_open_text.clicked.connect(lambda: self._open_file(self.txt_path))

        self.btn_open_log = QPushButton("📋  Ver Log de Erro")
        self.btn_open_log.setObjectName("btn_file")
        self.btn_open_log.clicked.connect(lambda: self._open_file(self.log_path))

        row.addWidget(self.btn_open_audio)
        row.addWidget(self.btn_open_text)
        row.addWidget(self.btn_open_log)
        self.widget_files.hide()
        return self.widget_files

    def _make_version_label(self) -> QLabel:
        lbl = QLabel(f"v{__version__}")
        lbl.setObjectName("label_version")
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        return lbl

    # ── Event handlers ────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _show_window(self) -> None:
        self.show()
        self.activateWindow()
        self.raise_()

    def _choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher diretório", self.input_dir.text())
        if path:
            self.input_dir.setText(path)

    def _open_file(self, path: str) -> None:
        if path and os.path.exists(path):
            try:
                subprocess.Popen(["xdg-open", path])
            except OSError:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        busy = self.recording_process is not None or (
            self.whisper_thread is not None and self.whisper_thread.isRunning()
        )
        if busy:
            reply = QMessageBox.question(
                self,
                "Trabalho em andamento",
                "Há uma gravação ou transcrição em andamento. Encerrar o app vai interrompê-la.\n\n"
                "Deseja sair mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        self._stop_ffmpeg()
        self._cleanup_ffmpeg_log()
        self._stop_whisper()
        event.accept()

    # ── Encerramento de processos ─────────────────────────────────────────────

    def _stop_ffmpeg(self) -> None:
        """Encerra o ffmpeg dando tempo de fechar o arquivo corretamente."""
        process = self.recording_process
        self.recording_process = None
        self._timer.stop()
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        except OSError:
            pass
        # O ffmpeg fechado libera o stdout que o LiveTranscriber lê — parar
        # depois dele garante que a leitura bloqueada desemperra por EOF.
        self._stop_live_transcriber()

    def _stop_whisper(self) -> None:
        """Cancela a transcrição e o processo filho, sem deixar Whisper órfão."""
        thread = self.whisper_thread
        if thread is None:
            return
        if thread.isRunning():
            thread.cancel()
            if not thread.wait(15000):
                thread.terminate()
                thread.wait()
        self.whisper_thread = None

    # ── Gravação ──────────────────────────────────────────────────────────────

    def _resolve_sources(self) -> tuple[str, str] | None:
        """Dispositivos a gravar conforme o modo configurado, ou ``None`` se faltar algum."""
        mode = load_config()["source_mode"]
        monitor = get_monitor() if mode in ("system", "both") else ""
        mic = get_mic() if mode in ("mic", "both") else ""
        missing = (mode in ("system", "both") and not monitor) or (
            mode in ("mic", "both") and not mic
        )
        if missing:
            QMessageBox.warning(
                self, "Dispositivo não configurado",
                "Nenhum dispositivo de áudio disponível para o modo escolhido.\n\n"
                "Acesse: ⚙ Configurações (canto superior direito)",
            )
            return None
        return monitor, mic

    def _start_recording(self) -> None:
        typed_dir = self.input_dir.text().strip()
        if not typed_dir:
            QMessageBox.warning(self, "Diretório inválido", "Informe um diretório de saída.")
            return

        # Caminho absoluto por dois motivos: um diretório relativo cairia no
        # diretório de trabalho do launcher (raramente o esperado), e "." com um
        # nome iniciado por "-" produziria um argumento que o ffmpeg leria como
        # opção em vez de arquivo de saída.
        output_dir = str(Path(typed_dir).expanduser().resolve())

        try:
            os.makedirs(output_dir, exist_ok=True)
        except PermissionError:
            QMessageBox.critical(
                self, "Sem permissão",
                f"Sem permissão para criar o diretório:\n{output_dir}",
            )
            return
        except OSError as exc:
            QMessageBox.critical(self, "Erro", f"Não foi possível criar o diretório:\n{exc}")
            return

        if not os.access(output_dir, os.W_OK):
            QMessageBox.critical(
                self, "Sem permissão",
                f"Sem permissão de escrita no diretório:\n{output_dir}",
            )
            return

        sources = self._resolve_sources()
        if sources is None:
            return
        monitor, mic = sources

        config = load_config()
        name = _sanitize_filename(self.input_name.text().strip())
        # unique_path evita que uma segunda gravação com o mesmo nome apague a primeira.
        audio_file = unique_path(output_dir, name, "." + config["audio_format"])
        self.audio_path = str(audio_file)
        self.txt_path = str(audio_file.with_suffix(".txt"))
        self.log_path = str(audio_file.with_name(audio_file.stem + "_erro.txt"))
        self.widget_files.hide()

        try:
            log = tempfile.NamedTemporaryFile(
                mode="w+", prefix="alex-transcritor-ffmpeg-", suffix=".log", delete=False
            )
        except OSError as exc:
            QMessageBox.critical(self, "Erro", f"Não foi possível iniciar a gravação:\n{exc}")
            return
        self._ffmpeg_log = log.name

        live_enabled = bool(config["live_transcription"])
        try:
            self.recording_process = subprocess.Popen(
                record_command(
                    self.audio_path, monitor, mic, config["audio_format"], live_pcm=live_enabled,
                ),
                stdout=subprocess.PIPE if live_enabled else subprocess.DEVNULL,
                stderr=log,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            QMessageBox.critical(
                self, "ffmpeg não encontrado",
                "O comando 'ffmpeg' não foi encontrado.\n"
                "Instale o pacote ffmpeg da sua distribuição.",
            )
            return
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Erro", f"Não foi possível iniciar a gravação:\n{exc}")
            return
        finally:
            log.close()

        self.input_dir.setText(output_dir)  # mostra onde os arquivos realmente vão cair
        self._started_at = time.monotonic()
        self._timer.start()
        self.btn_record.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("⏹  Parar")
        self.progress.hide()
        self._set_status("🔴  Gravando...", "#e74c3c")
        if live_enabled:
            self._start_live_transcriber(config)
        # O ffmpeg só falha alguns instantes após iniciar; sem esta verificação a
        # interface anuncia "gravando" enquanto nada é capturado.
        QTimer.singleShot(FFMPEG_CHECK_MS, self._verify_recording_started)

    def _start_live_transcriber(self, config: dict) -> None:
        """Best-effort: qualquer falha aqui só avisa no painel, nunca a gravação principal.

        O motor é decidido pelo mesmo ``transcription_backend`` do passe
        final: remoto processa no servidor (GPU forte, sem os problemas de
        driver/biblioteca CUDA já vistos no notebook); local roda em CPU
        aqui mesmo, único cenário em que a GPU local faria sentido, mas o
        motor local (faster-whisper) só tem suporte real a CPU neste app —
        ver histórico de `_live_device` removido, que tentava CUDA local e
        não funcionou bem no hardware do usuário.
        """
        self.live_panel.clear()
        self.live_panel.show()
        try:
            process = self.recording_process
            if process is None or process.stdout is None:
                raise RuntimeError("saída de áudio ao vivo indisponível")
            if config["transcription_backend"] == "remote":
                self.live_transcriber = RemoteLiveTranscriber(
                    process.stdout,
                    remote_url=config["remote_url"],
                    token=config["remote_token"],
                    language=config["language"],
                    model=config["live_model"],
                    # Mesmo vocabulário do passe final: nomes próprios e jargão
                    # erram muito menos quando vão como contexto.
                    initial_prompt=get_initial_prompt(),
                    diarize=config["diarize_speakers"],
                )
            else:
                self.live_transcriber = LiveTranscriber(
                    process.stdout,
                    model_size=config["live_model"],
                    device="cpu",
                    language=config["language"],
                )
            self.live_transcriber.segment.connect(self.live_panel.append_segment)
            self.live_transcriber.failed.connect(self.live_panel.show_unavailable)
            if hasattr(self.live_transcriber, "status"):  # só o motor remoto tem
                self.live_transcriber.status.connect(self.live_panel.show_status)
            self.live_transcriber.start()
        except Exception as exc:
            self.live_transcriber = None
            self.live_panel.show_unavailable(str(exc))

    def _stop_live_transcriber(self) -> None:
        """Sinaliza parada sem bloquear a UI.

        ``wait()`` aqui travaria a thread da interface até a janela de
        transcrição em andamento terminar — perceptível como um
        congelamento ao clicar "Parar". A thread termina sozinha (a
        transcrição atual conclui, o loop vê ``_stopped`` e sai).

        A referência em ``_retiring_threads`` é o que evita o crash "QThread:
        Destroyed while thread is still running": checar ``isRunning()``
        antes de decidir manter uma referência tem corrida — a thread pode
        terminar entre o cheque e a conexão do sinal, perdendo o ``finished``
        e deixando o wrapper Python sem nada que o segure enquanto o SO ainda
        não encerrou a thread de verdade. Manter a referência incondicional
        aqui, e só soltá-la quando ``finished`` realmente disparar, elimina
        essa corrida.
        """
        transcriber = self.live_transcriber
        self.live_transcriber = None
        if transcriber is None:
            return
        transcriber.stop()
        self._retiring_threads.append(transcriber)
        transcriber.finished.connect(lambda t=transcriber: self._forget_retiring_thread(t))
        if transcriber.isFinished():
            # Já tinha terminado antes desta conexão — o finished antigo não
            # é reemitido para quem conecta depois, então libera aqui mesmo.
            # isFinished() aqui é seguro (ao contrário de isRunning() antes):
            # uma thread finalizada não "volta a rodar", não há corrida.
            self._forget_retiring_thread(transcriber)

    def _forget_retiring_thread(self, transcriber: LiveTranscriber | RemoteLiveTranscriber) -> None:
        if transcriber in self._retiring_threads:
            self._retiring_threads.remove(transcriber)
        transcriber.deleteLater()

    def _verify_recording_started(self) -> None:
        process = self.recording_process
        if process is None or process.poll() is None:
            return
        detail = self._read_ffmpeg_log()
        self._cleanup_ffmpeg_log()
        self.recording_process = None
        self._stop_live_transcriber()
        self.live_panel.hide()
        self._timer.stop()
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_status("❌  Falha ao gravar", "#e74c3c")
        QMessageBox.critical(
            self, "Falha na gravação",
            "O ffmpeg encerrou logo após iniciar — nada foi gravado.\n\n"
            "Verifique o dispositivo em ⚙ Configurações.\n\n" + detail,
        )

    def _read_ffmpeg_log(self) -> str:
        try:
            with open(self._ffmpeg_log, encoding="utf-8", errors="replace") as f:
                return f.read()[-800:].strip()
        except OSError:
            return ""

    def _tick(self) -> None:
        elapsed = int(time.monotonic() - self._started_at)
        self.lbl_status.setText(f"🔴  Gravando...  {elapsed // 60:02d}:{elapsed % 60:02d}")

    # ── Transcrição ───────────────────────────────────────────────────────────

    def _stop_clicked(self) -> None:
        if self.recording_process is not None:
            self._stop_recording()
        elif self.whisper_thread is not None and self.whisper_thread.isRunning():
            self._cancel_transcription()

    def _cancel_transcription(self) -> None:
        self.btn_stop.setEnabled(False)
        self._set_status("Cancelando...", "#9a9a9a")
        self._stop_whisper()
        self.progress.hide()
        self.btn_record.setEnabled(True)
        self._set_status("Transcrição cancelada.", "#9a9a9a")

    def _stop_recording(self) -> None:
        self._stop_ffmpeg()
        self.live_panel.hide()
        self._cleanup_ffmpeg_log()
        # Deriva do arquivo gravado, não do campo: se o usuário mudar o diretório
        # durante a gravação, o texto tem que acompanhar o áudio.
        save_last_output_dir(str(Path(self.audio_path).parent))

        self.btn_stop.setText("✕  Cancelar")
        self.progress.setValue(0)
        self.progress.show()
        self._set_status("⏳  Transcrevendo...", "#f39c12")

        config = load_config()
        common = dict(
            audio_path=self.audio_path,
            txt_path=self.txt_path,
            model=config["model"],
            language=config["language"],
            initial_prompt=get_initial_prompt(),
            enhance=config["enhance_audio"],
            replacements=get_replacements(),
        )
        if config["transcription_backend"] == "remote":
            self.whisper_thread = RemoteWhisperThread(
                remote_url=config["remote_url"], token=config["remote_token"],
                diarize=config["diarize_speakers"], **common
            )
        else:
            self.whisper_thread = WhisperThread(
                whisper_bin=WHISPER_BIN, device=config["device"], **common
            )
        self.whisper_thread.succeeded.connect(self._on_done)
        self.whisper_thread.failed.connect(self._on_error)
        self.whisper_thread.progress.connect(self._on_progress)
        self.whisper_thread.start()

    def _cleanup_ffmpeg_log(self) -> None:
        if not self._ffmpeg_log:
            return
        try:
            os.unlink(self._ffmpeg_log)
        except OSError:
            pass
        self._ffmpeg_log = ""

    def _on_progress(self, percent: int, label: str) -> None:
        self.progress.setValue(percent)
        self._set_status(f"⏳  {label}", "#f39c12")

    def _on_done(self, txt_path: str) -> None:
        self.txt_path = txt_path
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("⏹  Parar")
        self.progress.hide()
        self._set_status(f"✅  Pronto — {Path(txt_path).name}", "#2ecc71")
        self.btn_open_audio.show()
        self.btn_open_text.show()
        self.btn_open_log.hide()
        self.widget_files.show()

    def _on_error(self, msg: str) -> None:
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("⏹  Parar")
        self.progress.hide()
        self._set_status("❌  Erro na transcrição", "#e74c3c")
        self._write_log(msg)
        self.btn_open_audio.show()  # o áudio existe mesmo quando a transcrição falha
        self.btn_open_text.hide()
        self.btn_open_log.show()
        self.widget_files.show()

    def _write_log(self, msg: str) -> None:
        try:
            # 0600: a saída do Whisper pode conter caminhos e trechos do áudio.
            fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(msg)
        except OSError:
            pass

    def _set_status(self, text: str, color: str) -> None:
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 12px;")
