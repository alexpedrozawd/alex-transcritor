import os
import stat
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QMessageBox, QPushButton, QLabel
from PyQt6.QtGui import QCloseEvent

import alex_transcritor.config as cfg
from alex_transcritor.ui.main_window import MainWindow, _sanitize_filename, MAX_NAME_LEN


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "transcricoes"))


@pytest.fixture(autouse=True)
def no_real_devices(monkeypatch):
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "monitor_teste")
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_mic", lambda: "mic_teste")


def _safe_close(w: MainWindow) -> None:
    # qtbot fecha o widget no teardown; sem limpar o estado, o closeEvent abre um
    # QMessageBox que trava no modo offscreen.
    w.recording_process = None
    w.whisper_thread = None
    w.live_transcriber = None


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_safe_close)
    return w


@pytest.fixture
def popen(monkeypatch):
    """Substitui o Popen do ffmpeg por um duplo que se comporta como processo vivo."""
    process = MagicMock()
    process.poll.return_value = None
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen", MagicMock(return_value=process)
    )
    return process


@pytest.fixture
def no_thread(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("alex_transcritor.ui.main_window.WhisperThread", fake)
    return fake


@pytest.fixture
def live_thread(monkeypatch):
    """Substitui o LiveTranscriber por um duplo — não roda modelo nenhum de verdade."""
    fake = MagicMock()
    monkeypatch.setattr("alex_transcritor.ui.main_window.LiveTranscriber", fake)
    return fake


# ── _sanitize_filename ────────────────────────────────────────────────────────

def test_sanitize_normal_name():
    assert _sanitize_filename("aula-01") == "aula-01"


def test_sanitize_removes_slashes():
    assert "/" not in _sanitize_filename("path/to/file")
    assert "\\" not in _sanitize_filename("path\\to\\file")


def test_sanitize_removes_dangerous_chars():
    result = _sanitize_filename('file<>:"|?*name')
    assert all(c not in result for c in '<>:"|?*')


def test_sanitize_blocks_path_traversal():
    assert "/" not in _sanitize_filename("../../etc/passwd")


def test_sanitize_removes_control_characters():
    assert "\x00" not in _sanitize_filename("nome\x00\x1fruim")


def test_sanitize_empty_uses_timestamp():
    result = _sanitize_filename("")
    assert result.startswith("gravacao-")
    datetime.strptime(result, "gravacao-%Y-%m-%d-%H%M%S")


def test_sanitize_only_dots_uses_timestamp():
    assert _sanitize_filename("...").startswith("gravacao-")


def test_sanitize_strips_leading_trailing():
    assert _sanitize_filename("  nome  ") == "nome"


def test_sanitize_limits_length():
    assert len(_sanitize_filename("a" * 500)) == MAX_NAME_LEN


# ── Estado inicial ────────────────────────────────────────────────────────────

def test_window_title(window):
    assert window.windowTitle() == "Alex-Transcritor"


def test_window_is_resizable(window):
    """Janela fixa cortava o texto com fontes de acessibilidade."""
    assert window.maximumWidth() > window.minimumWidth()


def test_initial_button_states(window):
    assert window.btn_record.isEnabled()
    assert not window.btn_stop.isEnabled()


def test_initial_status_text(window):
    assert "Aguardando" in window.lbl_status.text()


def test_file_buttons_hidden_initially(window):
    assert window.widget_files.isHidden()


def test_progress_hidden_initially(window):
    assert window.progress.isHidden()


def test_default_output_dir_uses_config(tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "custom"))
    w = MainWindow()
    qtbot.addWidget(w)
    assert str(tmp_path / "custom") in w.input_dir.text()


def test_settings_button_exists(window):
    btn = window.findChild(QPushButton, "btn_settings")
    assert btn is not None and btn.toolTip() == "Configurações"


def test_version_label_shows_version(window):
    from alex_transcritor import __version__
    lbl = window.findChild(QLabel, "label_version")
    assert lbl is not None and f"v{__version__}" in lbl.text()


# ── _start_recording: validações ──────────────────────────────────────────────

def test_start_recording_empty_dir_shows_warning(window, monkeypatch):
    window.input_dir.setText("")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


def test_start_recording_no_device_shows_warning(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


def test_start_recording_mic_mode_requires_mic(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    cfg.update_config(source_mode="mic")
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_mic", lambda: "")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


def test_start_recording_permission_error_shows_critical(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path / "blocked"))
    monkeypatch.setattr("os.makedirs", MagicMock(side_effect=PermissionError))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown


def test_start_recording_oserror_shows_critical(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path / "blocked"))
    monkeypatch.setattr("os.makedirs", MagicMock(side_effect=OSError("disco cheio")))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown


def test_start_recording_readonly_dir_shows_critical(window, monkeypatch, tmp_path):
    readonly = tmp_path / "somente-leitura"
    readonly.mkdir()
    readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)
    window.input_dir.setText(str(readonly))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    try:
        window._start_recording()
    finally:
        readonly.chmod(0o700)
    assert shown and window.recording_process is None


def test_start_recording_ffmpeg_not_found(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen",
        MagicMock(side_effect=FileNotFoundError),
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


# ── _start_recording: caminho feliz ───────────────────────────────────────────

def test_start_recording_success(window, popen, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window.input_name.setText("teste")
    window._start_recording()
    assert window.recording_process is popen
    assert not window.btn_record.isEnabled()
    assert window.btn_stop.isEnabled()
    assert "Gravando" in window.lbl_status.text()


def test_start_recording_live_transcription_disabled_by_default(window, popen, live_thread, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    live_thread.assert_not_called()
    assert window.live_panel.isHidden()


def test_start_recording_live_transcription_enabled_starts_engine(
    window, popen, live_thread, tmp_path
):
    cfg.update_config(live_transcription=True)
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    live_thread.assert_called_once()
    live_thread.return_value.start.assert_called_once()
    assert not window.live_panel.isHidden()


def test_start_recording_live_transcription_uses_gpu_when_backend_is_remote(
    window, popen, live_thread, tmp_path
):
    """A GPU local fica ociosa a gravação inteira quando o passe final é
    remoto — sem risco de disputar VRAM, então a transcrição ao vivo pode
    usá-la em vez de ficar restrita à CPU."""
    cfg.update_config(live_transcription=True, transcription_backend="remote")
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    assert live_thread.call_args.kwargs["device"] == "cuda"


def test_start_recording_live_transcription_stays_on_cpu_when_backend_is_local(
    window, popen, live_thread, tmp_path
):
    """Só quando o passe final também é local (mesma GPU) a transcrição ao
    vivo continua restrita à CPU — é a única situação com risco real de
    disputa de VRAM entre os dois motores."""
    cfg.update_config(live_transcription=True, transcription_backend="local")
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    assert live_thread.call_args.kwargs["device"] == "cpu"


def test_start_recording_live_transcriber_failure_does_not_block_recording(
    window, popen, monkeypatch, tmp_path
):
    """Uma falha ao iniciar a transcrição ao vivo nunca pode impedir a gravação principal."""
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.LiveTranscriber",
        MagicMock(side_effect=RuntimeError("faster-whisper ausente")),
    )
    cfg.update_config(live_transcription=True)
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    assert window.recording_process is popen
    assert window.live_transcriber is None


def test_stop_live_transcriber_never_blocks_and_holds_a_reference(window):
    """Regressão dupla: wait() aqui travava a UI até a janela em transcrição
    terminar (congelamento ao clicar Parar); e sem segurar uma referência
    real até 'finished' disparar, o wrapper Python podia ser coletado
    enquanto a thread ainda rodava de verdade — Qt aborta o processo com
    "QThread: Destroyed while thread is still running" (crash real em uso)."""
    transcriber = MagicMock()
    transcriber.isFinished.return_value = False
    window.live_transcriber = transcriber
    window._stop_live_transcriber()
    transcriber.wait.assert_not_called()
    transcriber.stop.assert_called_once()
    assert transcriber in window._retiring_threads
    transcriber.finished.connect.assert_called_once()


def test_finished_signal_releases_the_retiring_thread(window):
    """Só depois que a thread confirma via `finished` que terminou de
    verdade é que a referência é solta — nunca antes (checar isRunning()
    antes de conectar tinha corrida: a thread podia terminar entre o cheque
    e a conexão)."""
    transcriber = MagicMock()
    transcriber.isFinished.return_value = False
    window.live_transcriber = transcriber
    window._stop_live_transcriber()
    on_finished = transcriber.finished.connect.call_args.args[0]
    on_finished()
    assert transcriber not in window._retiring_threads
    transcriber.deleteLater.assert_called_once()


def test_already_finished_thread_is_released_immediately(window):
    """Se a thread já tinha terminado antes de conectarmos ao finished (o
    sinal antigo não seria reemitido), a limpeza precisa acontecer na hora —
    sem isso, a referência ficava presa para sempre em _retiring_threads."""
    transcriber = MagicMock()
    transcriber.isFinished.return_value = True
    window.live_transcriber = transcriber
    window._stop_live_transcriber()
    assert transcriber not in window._retiring_threads
    transcriber.deleteLater.assert_called_once()


def test_stop_live_transcriber_survives_a_thread_that_finishes_immediately(qtbot, window, monkeypatch):
    """Integração com uma LiveTranscriber real (não mockada): reproduz a
    corrida do bug de verdade — parar bem no instante em que a thread já
    terminou (ou está terminando) não pode deixar o wrapper sem nenhuma
    referência Python enquanto o Qt ainda considera a thread viva."""
    import io

    from alex_transcritor import live as live_module

    class _InstantModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **kwargs):
            return [], None

    monkeypatch.setattr(live_module, "WhisperModel", _InstantModel)
    transcriber = live_module.LiveTranscriber(io.BytesIO(b""))  # EOF imediato
    window.live_transcriber = transcriber
    transcriber.start()
    # Dá tempo da thread real terminar sozinha antes de mandarmos parar —
    # é exatamente a janela de corrida que causava o crash.
    assert transcriber.wait(2000)
    window._stop_live_transcriber()
    qtbot.waitUntil(lambda: transcriber not in window._retiring_threads, timeout=2000)


def test_start_recording_uses_configured_audio_format(window, popen, tmp_path):
    cfg.update_config(audio_format="wav")
    window.input_dir.setText(str(tmp_path))
    window.input_name.setText("teste")
    window._start_recording()
    assert window.audio_path.endswith("teste.wav")


def test_start_recording_never_overwrites_existing_files(window, popen, tmp_path):
    (tmp_path / "aula.flac").write_bytes(b"gravacao anterior")
    window.input_dir.setText(str(tmp_path))
    window.input_name.setText("aula")
    window._start_recording()
    assert window.audio_path.endswith("aula-2.flac")
    assert window.txt_path.endswith("aula-2.txt")
    assert (tmp_path / "aula.flac").read_bytes() == b"gravacao anterior"


def test_start_recording_detects_ffmpeg_dying_immediately(window, monkeypatch, tmp_path):
    """ffmpeg com dispositivo inválido morre em silêncio; a UI dizia 'gravando'."""
    dead = MagicMock()
    dead.poll.return_value = 1
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen", MagicMock(return_value=dead)
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._verify_recording_started()
    assert shown
    assert window.recording_process is None
    assert window.btn_record.isEnabled()


def test_verify_recording_silent_while_process_alive(window, popen, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._verify_recording_started()
    assert not shown and window.recording_process is popen


def test_recording_timer_shows_elapsed(window, popen, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._started_at -= 65
    window._tick()
    assert "01:05" in window.lbl_status.text()


# ── _stop_recording ───────────────────────────────────────────────────────────

def test_stop_recording_terminates_and_starts_thread(window, popen, no_thread, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._stop_clicked()
    popen.terminate.assert_called_once()
    no_thread.return_value.start.assert_called_once()
    assert window.recording_process is None


def test_stop_recording_kills_ffmpeg_that_ignores_terminate(window, popen, no_thread, tmp_path):
    import subprocess as sp
    popen.wait.side_effect = [sp.TimeoutExpired(cmd="ffmpeg", timeout=10), 0]
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._stop_clicked()
    popen.kill.assert_called_once()


def test_stop_recording_passes_configured_options(window, popen, no_thread, tmp_path):
    cfg.update_config(model="tiny", language="en", device="cpu", vocabulary="PipeWire")
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._stop_clicked()
    kwargs = no_thread.call_args.kwargs
    assert kwargs["model"] == "tiny"
    assert kwargs["language"] == "en"
    assert kwargs["device"] == "cpu"
    assert "PipeWire" in kwargs["initial_prompt"]
    assert kwargs["txt_path"] == window.txt_path
    assert "diarize" not in kwargs  # motor local nunca recebe diarização


def test_stop_recording_uses_remote_server(window, popen, tmp_path, monkeypatch):
    remote = MagicMock()
    monkeypatch.setattr("alex_transcritor.ui.main_window.RemoteWhisperThread", remote)
    cfg.update_config(
        transcription_backend="remote",
        remote_url="http://100.84.64.122:8300",
        remote_token="x" * 32,
        model="turbo",
        diarize_speakers=True,
    )
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._stop_clicked()
    kwargs = remote.call_args.kwargs
    assert kwargs["remote_url"] == "http://100.84.64.122:8300"
    assert kwargs["token"] == "x" * 32
    assert kwargs["model"] == "turbo"
    assert kwargs["diarize"] is True
    remote.return_value.start.assert_called_once()


def test_stop_recording_saves_output_dir(window, popen, no_thread, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    window._stop_clicked()
    assert cfg.get_last_output_dir() == str(tmp_path)


def test_stop_button_cancels_transcription(window, tmp_path, monkeypatch):
    thread = MagicMock()
    thread.isRunning.return_value = True
    thread.wait.return_value = True
    window.whisper_thread = thread
    window._stop_clicked()
    thread.cancel.assert_called_once()
    assert "cancelada" in window.lbl_status.text().lower()
    assert window.btn_record.isEnabled()


# ── Progresso e conclusão ─────────────────────────────────────────────────────

def test_progress_updates_bar_and_status(window):
    window._on_progress(42, "Transcrevendo (turbo · CPU)")
    assert window.progress.value() == 42
    assert "turbo" in window.lbl_status.text()


def test_on_done_updates_ui(window, tmp_path):
    txt = tmp_path / "aula.txt"
    txt.write_text("ok", encoding="utf-8")
    window._on_done(str(txt))
    assert window.btn_record.isEnabled()
    assert "aula.txt" in window.lbl_status.text()
    assert not window.btn_open_audio.isHidden()
    assert not window.btn_open_text.isHidden()
    assert window.btn_open_log.isHidden()
    assert window.progress.isHidden()


def test_on_done_adopts_real_output_path(window, tmp_path):
    txt = tmp_path / "aula-2.txt"
    txt.write_text("ok", encoding="utf-8")
    window._on_done(str(txt))
    assert window.txt_path == str(txt)


def test_on_error_updates_ui(window, tmp_path):
    window.log_path = str(tmp_path / "erro.txt")
    window._on_error("erro de teste")
    assert window.btn_record.isEnabled()
    assert "Erro" in window.lbl_status.text()
    assert window.btn_open_text.isHidden()
    assert not window.btn_open_log.isHidden()
    assert not window.btn_open_audio.isHidden()  # o áudio existe mesmo com falha


def test_on_error_writes_log_with_private_permissions(window, tmp_path):
    log = tmp_path / "erro.txt"
    window.log_path = str(log)
    window._on_error("mensagem de erro")
    assert log.read_text(encoding="utf-8") == "mensagem de erro"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_on_error_log_write_failure_does_not_crash(window):
    window.log_path = "/proc/versao-inexistente/erro.txt"
    window._on_error("erro")


# ── Diálogos auxiliares ───────────────────────────────────────────────────────

def test_open_settings_calls_dialog(window, monkeypatch):
    executed = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.SettingsDialog",
        type("FakeDlg", (), {"__init__": lambda s, p=None: None,
                             "exec": lambda s: executed.append(True)}),
    )
    window._open_settings()
    assert executed


def test_show_window_makes_visible(window):
    window.hide()
    window._show_window()
    assert not window.isHidden()


def test_choose_dir_updates_input(window, monkeypatch):
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **k: "/new/path",
    )
    window._choose_dir()
    assert window.input_dir.text() == "/new/path"


def test_choose_dir_cancelled_keeps_original(window, monkeypatch):
    window.input_dir.setText("/original")
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **k: "",
    )
    window._choose_dir()
    assert window.input_dir.text() == "/original"


def test_open_file_calls_xdg_open(window, tmp_path, monkeypatch):
    f = tmp_path / "audio.flac"
    f.write_bytes(b"fake")
    opened = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen", lambda cmd, **k: opened.append(cmd)
    )
    window._open_file(str(f))
    assert opened and "xdg-open" in opened[0]


def test_open_file_oserror_does_not_crash(window, tmp_path, monkeypatch):
    f = tmp_path / "audio.flac"
    f.write_bytes(b"fake")
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen", MagicMock(side_effect=OSError)
    )
    window._open_file(str(f))


def test_open_file_nonexistent_does_nothing(window, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen", lambda cmd, **k: opened.append(cmd)
    )
    window._open_file("/nao/existe.flac")
    assert not opened


# ── closeEvent ────────────────────────────────────────────────────────────────

def test_close_event_accepts_when_idle(window):
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_close_event_ignores_when_recording_and_user_cancels(window, popen, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window.recording_process is popen


def test_close_event_terminates_recording_when_confirmed(window, popen, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()
    window.closeEvent(event)
    popen.terminate.assert_called_once()
    assert event.isAccepted()
    assert window.recording_process is None


def test_close_event_cancels_transcription_instead_of_orphaning_it(window, monkeypatch):
    """terminate() da QThread matava só a thread e deixava o Whisper rodando."""
    thread = MagicMock()
    thread.isRunning.return_value = True
    thread.wait.return_value = True
    window.whisper_thread = thread
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()
    window.closeEvent(event)
    thread.cancel.assert_called_once()
    thread.terminate.assert_not_called()
    assert event.isAccepted()


def test_close_event_force_terminates_thread_that_ignores_cancel(window, monkeypatch):
    thread = MagicMock()
    thread.isRunning.return_value = True
    thread.wait.return_value = False
    window.whisper_thread = thread
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.closeEvent(QCloseEvent())
    thread.terminate.assert_called_once()


# ── Higiene de arquivos temporários ───────────────────────────────────────────

def test_ffmpeg_log_removed_after_stop(window, popen, no_thread, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window._start_recording()
    log_path = window._ffmpeg_log
    window._stop_clicked()
    assert not os.path.exists(log_path)


# ── Caminhos de erro do sistema de arquivos ───────────────────────────────────

def test_start_recording_temp_log_failure_shows_critical(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.tempfile.NamedTemporaryFile",
        MagicMock(side_effect=OSError("sem espaço em /tmp")),
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


def test_start_recording_invalid_command_shows_critical(window, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.record_command",
        MagicMock(side_effect=ValueError("nenhuma fonte")),
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True))
    window._start_recording()
    assert shown and window.recording_process is None


def test_ffmpeg_log_read_failure_returns_empty(window):
    window._ffmpeg_log = "/nao/existe.log"
    assert window._read_ffmpeg_log() == ""


def test_ffmpeg_log_failure_detail_reaches_the_user(window, monkeypatch, tmp_path):
    log = tmp_path / "ffmpeg.log"
    log.write_text("Unknown PulseAudio source", encoding="utf-8")
    window._ffmpeg_log = str(log)
    dead = MagicMock()
    dead.poll.return_value = 1
    window.recording_process = dead
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: messages.append(a[2]))
    window._verify_recording_started()
    assert "Unknown PulseAudio source" in messages[0]


def test_cleanup_without_log_is_noop(window):
    window._ffmpeg_log = ""
    window._cleanup_ffmpeg_log()


def test_cleanup_tolerates_already_removed_log(window, tmp_path):
    window._ffmpeg_log = str(tmp_path / "sumiu.log")
    window._cleanup_ffmpeg_log()
    assert window._ffmpeg_log == ""


def test_open_file_of_missing_path_after_failure(window, tmp_path):
    window._open_file(str(tmp_path / "nunca-criado.txt"))  # não deve levantar exceção


# ── Resolução do diretório de saída ───────────────────────────────────────────

def test_relative_output_dir_is_resolved(window, popen, tmp_path, monkeypatch):
    """Diretório relativo cairia no CWD do launcher, não onde o usuário espera."""
    monkeypatch.chdir(tmp_path)
    window.input_dir.setText("saida")
    window.input_name.setText("aula")
    window._start_recording()
    assert window.audio_path == str(tmp_path / "saida" / "aula.flac")
    assert window.input_dir.text() == str(tmp_path / "saida")


def test_output_path_is_never_read_as_an_ffmpeg_flag(window, popen, tmp_path, monkeypatch):
    """'.' + nome começando com '-' geraria um argv que o ffmpeg lê como opção."""
    monkeypatch.chdir(tmp_path)
    window.input_dir.setText(".")
    window.input_name.setText("-rf")
    window._start_recording()
    assert not Path(window.audio_path).name.startswith("/")
    assert window.audio_path.startswith("/")


def test_tilde_in_output_dir_is_expanded(window, popen, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    window.input_dir.setText("~/gravacoes")
    window._start_recording()
    assert window.audio_path.startswith(str(tmp_path / "gravacoes"))


def test_saved_dir_follows_the_recording_not_the_field(window, popen, no_thread, tmp_path):
    """Trocar o diretório durante a gravação não pode separar áudio e texto."""
    window.input_dir.setText(str(tmp_path / "original"))
    window._start_recording()
    window.input_dir.setText(str(tmp_path / "outro"))
    window._stop_clicked()
    assert cfg.get_last_output_dir() == str(tmp_path / "original")
    assert Path(window.txt_path).parent == Path(window.audio_path).parent
