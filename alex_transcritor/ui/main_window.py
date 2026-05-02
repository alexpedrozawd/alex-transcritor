import os
import re
import subprocess
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QCloseEvent

from .. import __version__
from ..constants import ICON_PATH, WHISPER_BIN
from ..config import get_monitor, get_last_output_dir, save_last_output_dir
from ..worker import WhisperThread
from .styles import STYLE
from .settings_dialog import SettingsDialog


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[/\\<>:"|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "gravacao"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.recording_process: subprocess.Popen | None = None
        self.whisper_thread: WhisperThread | None = None
        self.audio_path = ""
        self.txt_path = ""
        self.log_path = ""
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setWindowTitle("Alex-Transcritor")
        self.setFixedSize(360, 385)
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
        root.addSpacing(10)
        root.addWidget(self._make_file_buttons())
        root.addSpacing(8)
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
        self.input_name.setPlaceholderText("ex: aula-01")
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
        self.btn_stop.clicked.connect(self._stop_recording)
        row.addWidget(self.btn_record)
        row.addWidget(self.btn_stop)
        return row

    def _make_status_label(self) -> QLabel:
        self.lbl_status = QLabel("Aguardando...")
        self.lbl_status.setObjectName("label_status")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return self.lbl_status

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
        if self.recording_process is not None:
            reply = QMessageBox.question(
                self,
                "Gravação em andamento",
                "Há uma gravação em andamento. Encerrar o app vai interrompê-la.\n\nDeseja sair mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.recording_process.terminate()
            self.recording_process.wait()
            self.recording_process = None

        if self.whisper_thread and self.whisper_thread.isRunning():
            self.whisper_thread.terminate()
            self.whisper_thread.wait()

        event.accept()

    # ── Recording logic ───────────────────────────────────────────────────────

    def _start_recording(self) -> None:
        name = _sanitize_filename(self.input_name.text().strip())
        output_dir = self.input_dir.text().strip()

        if not output_dir:
            QMessageBox.warning(self, "Diretório inválido", "Informe um diretório de saída.")
            return

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

        monitor = get_monitor()
        if not monitor:
            QMessageBox.warning(
                self, "Dispositivo não configurado",
                "Nenhum dispositivo de áudio configurado.\n\n"
                "Acesse: ⚙ Configurações (canto superior direito)",
            )
            return

        self.audio_path = os.path.join(output_dir, f"{name}.mp3")
        self.txt_path = os.path.join(output_dir, f"{name}.txt")
        self.log_path = os.path.join(output_dir, f"{name}_erro.txt")
        self.widget_files.hide()

        try:
            self.recording_process = subprocess.Popen(
                ["ffmpeg", "-y", "-f", "pulse", "-i", monitor,
                 "-ac", "1", "-ar", "16000", self.audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            QMessageBox.critical(
                self, "ffmpeg não encontrado",
                "O comando 'ffmpeg' não foi encontrado.\n"
                "Instale com: sudo apt install ffmpeg",
            )
            return

        self.btn_record.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText("🔴  Gravando...")
        self.lbl_status.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def _stop_recording(self) -> None:
        if self.recording_process:
            self.recording_process.terminate()
            self.recording_process.wait()
            self.recording_process = None

        save_last_output_dir(self.input_dir.text().strip())
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("⏳  Transcrevendo...")
        self.lbl_status.setStyleSheet("color: #f39c12; font-size: 12px;")

        self.whisper_thread = WhisperThread(
            self.audio_path,
            self.input_dir.text().strip(),
            WHISPER_BIN,
        )
        self.whisper_thread.finished.connect(self._on_done)
        self.whisper_thread.error.connect(self._on_error)
        self.whisper_thread.start()

    def _on_done(self) -> None:
        self.btn_record.setEnabled(True)
        self.lbl_status.setText("✅  Transcrição concluída!")
        self.lbl_status.setStyleSheet("color: #2ecc71; font-size: 12px;")
        self.btn_open_audio.show()
        self.btn_open_text.show()
        self.btn_open_log.hide()
        self.widget_files.show()

    def _on_error(self, msg: str) -> None:
        self.btn_record.setEnabled(True)
        self.lbl_status.setText("❌  Erro na transcrição")
        self.lbl_status.setStyleSheet("color: #e74c3c; font-size: 12px;")
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write(msg)
        except OSError:
            pass
        self.btn_open_audio.hide()
        self.btn_open_text.hide()
        self.btn_open_log.show()
        self.widget_files.show()
