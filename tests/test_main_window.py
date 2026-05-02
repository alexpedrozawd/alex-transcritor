import os
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QMessageBox, QPushButton
from PyQt6.QtCore import QCoreApplication

import alex_transcritor.config as cfg
from alex_transcritor.ui.main_window import MainWindow, _sanitize_filename


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "transcricoes"))


def _safe_close(w: MainWindow) -> None:
    # qtbot.addWidget usa before_close_func para limpar antes de fechar;
    # sem isso, recording_process setado em alguns testes dispara
    # QMessageBox.question no closeEvent e bloqueia em modo offscreen.
    w.recording_process = None
    if w.whisper_thread and w.whisper_thread.isRunning():
        w.whisper_thread.terminate()
        w.whisper_thread.wait()


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_safe_close)
    yield w


# ── _sanitize_filename ────────────────────────────────────────────────────────

def test_sanitize_normal_name():
    assert _sanitize_filename("aula-01") == "aula-01"


def test_sanitize_removes_slashes():
    assert "/" not in _sanitize_filename("path/to/file")
    assert "\\" not in _sanitize_filename("path\\to\\file")


def test_sanitize_removes_dangerous_chars():
    result = _sanitize_filename('file<>:"|?*name')
    assert all(c not in result for c in '<>:"|?*')


def test_sanitize_empty_returns_default():
    assert _sanitize_filename("") == "gravacao"


def test_sanitize_only_dots_returns_default():
    assert _sanitize_filename("...") == "gravacao"


def test_sanitize_strips_leading_trailing():
    assert _sanitize_filename("  nome  ") == "nome"


# ── MainWindow initialization ─────────────────────────────────────────────────

def test_window_title(window):
    assert window.windowTitle() == "Alex-Transcritor"


def test_initial_button_states(window):
    assert window.btn_record.isEnabled()
    assert not window.btn_stop.isEnabled()


def test_initial_status_text(window):
    assert "Aguardando" in window.lbl_status.text()


def test_file_buttons_hidden_initially(window):
    assert not window.widget_files.isVisible()


def test_default_output_dir_uses_config(tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "custom"))
    w = MainWindow()
    qtbot.addWidget(w)
    assert str(tmp_path / "custom") in w.input_dir.text()


# ── _start_recording validations ──────────────────────────────────────────────

def test_start_recording_empty_dir_shows_warning(window, qtbot, monkeypatch):
    window.input_dir.setText("")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(True) or QMessageBox.StandardButton.Ok)
    window._start_recording()
    assert shown


def test_start_recording_no_monitor_shows_warning(window, qtbot, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(True) or QMessageBox.StandardButton.Ok)
    window._start_recording()
    assert shown
    assert window.recording_process is None


def test_start_recording_permission_error_shows_critical(window, qtbot, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path / "blocked"))
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "test_monitor")
    monkeypatch.setattr("os.makedirs", MagicMock(side_effect=PermissionError))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True) or QMessageBox.StandardButton.Ok)
    window._start_recording()
    assert shown


def test_start_recording_ffmpeg_not_found(window, qtbot, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "test_monitor")
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen",
        MagicMock(side_effect=FileNotFoundError),
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True) or QMessageBox.StandardButton.Ok)
    window._start_recording()
    assert shown
    assert window.recording_process is None


def test_start_recording_success(window, qtbot, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path))
    window.input_name.setText("teste")
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "test_monitor")
    mock_popen = MagicMock()
    monkeypatch.setattr("alex_transcritor.ui.main_window.subprocess.Popen", MagicMock(return_value=mock_popen))
    window._start_recording()
    assert window.recording_process is mock_popen
    assert not window.btn_record.isEnabled()
    assert window.btn_stop.isEnabled()
    assert "Gravando" in window.lbl_status.text()


# ── _stop_recording ───────────────────────────────────────────────────────────

def test_stop_recording_terminates_process(window, qtbot, monkeypatch, tmp_path):
    mock_proc = MagicMock()
    window.recording_process = mock_proc
    window.audio_path = str(tmp_path / "audio.mp3")
    window.input_dir.setText(str(tmp_path))
    monkeypatch.setattr("alex_transcritor.ui.main_window.WhisperThread", MagicMock())
    window._stop_recording()
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
    assert window.recording_process is None


def test_stop_recording_starts_whisper_thread(window, qtbot, monkeypatch, tmp_path):
    window.recording_process = MagicMock()
    window.audio_path = str(tmp_path / "audio.mp3")
    window.input_dir.setText(str(tmp_path))
    mock_thread_cls = MagicMock()
    mock_thread_inst = MagicMock()
    mock_thread_cls.return_value = mock_thread_inst
    monkeypatch.setattr("alex_transcritor.ui.main_window.WhisperThread", mock_thread_cls)
    window._stop_recording()
    mock_thread_inst.start.assert_called_once()


# ── _on_done ──────────────────────────────────────────────────────────────────

def test_on_done_updates_ui(window):
    window._on_done()
    assert window.btn_record.isEnabled()
    assert "concluída" in window.lbl_status.text()
    # isHidden() verifica o estado explícito do widget, independente da janela estar renderizada
    assert not window.btn_open_audio.isHidden()
    assert not window.btn_open_text.isHidden()
    assert window.btn_open_log.isHidden()
    assert not window.widget_files.isHidden()


# ── _on_error ─────────────────────────────────────────────────────────────────

def test_on_error_updates_ui(window, tmp_path):
    window.log_path = str(tmp_path / "erro.txt")
    window._on_error("erro de teste")
    assert window.btn_record.isEnabled()
    assert "Erro" in window.lbl_status.text()
    assert window.btn_open_audio.isHidden()
    assert not window.btn_open_log.isHidden()


def test_on_error_writes_log(window, tmp_path):
    log = tmp_path / "erro.txt"
    window.log_path = str(log)
    window._on_error("mensagem de erro")
    assert log.read_text(encoding="utf-8") == "mensagem de erro"


def test_on_error_log_write_failure_does_not_crash(window, monkeypatch):
    window.log_path = "/root/no_permission/erro.txt"
    window._on_error("erro")  # não deve levantar exceção


# ── _open_settings ───────────────────────────────────────────────────────────

def test_open_settings_calls_dialog(window, monkeypatch):
    executed = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.SettingsDialog",
        type("FakeDlg", (), {"__init__": lambda s, p=None: None, "exec": lambda s: executed.append(True)}),
    )
    window._open_settings()
    assert executed


# ── _show_window ──────────────────────────────────────────────────────────────

def test_show_window_makes_visible(window):
    window.hide()
    window._show_window()
    assert not window.isHidden()


# ── _choose_dir ───────────────────────────────────────────────────────────────

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


# ── _open_file ────────────────────────────────────────────────────────────────

def test_open_file_calls_xdg_open(window, tmp_path, monkeypatch):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"fake")
    opened = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen",
        lambda cmd, **k: opened.append(cmd),
    )
    window._open_file(str(f))
    assert opened and "xdg-open" in opened[0]


def test_open_file_oserror_does_not_crash(window, tmp_path, monkeypatch):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"fake")
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen",
        MagicMock(side_effect=OSError("xdg-open not found")),
    )
    window._open_file(str(f))  # não deve levantar exceção


def test_open_file_nonexistent_does_nothing(window, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "alex_transcritor.ui.main_window.subprocess.Popen",
        lambda cmd, **k: opened.append(cmd),
    )
    window._open_file("/nonexistent/file.mp3")
    assert not opened


# ── _start_recording OSError ──────────────────────────────────────────────────

def test_start_recording_oserror_shows_critical(window, qtbot, monkeypatch, tmp_path):
    window.input_dir.setText(str(tmp_path / "blocked"))
    monkeypatch.setattr("alex_transcritor.ui.main_window.get_monitor", lambda: "test_monitor")
    monkeypatch.setattr("os.makedirs", MagicMock(side_effect=OSError("disk full")))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(True) or QMessageBox.StandardButton.Ok)
    window._start_recording()
    assert shown


# ── settings button ───────────────────────────────────────────────────────────

def test_settings_button_exists(window):
    btn = window.findChild(QPushButton, "btn_settings")
    assert btn is not None
    assert btn.toolTip() == "Configurações"


# ── version label ─────────────────────────────────────────────────────────────

def test_version_label_shows_version(window):
    from PyQt6.QtWidgets import QLabel
    from alex_transcritor import __version__
    lbl = window.findChild(QLabel, "label_version")
    assert lbl is not None
    assert f"v{__version__}" in lbl.text()


# ── closeEvent ────────────────────────────────────────────────────────────────

def test_close_event_accepts_when_not_recording(window, qtbot, monkeypatch):
    from PyQt6.QtGui import QCloseEvent
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_close_event_ignores_when_recording_and_user_cancels(window, monkeypatch):
    from PyQt6.QtGui import QCloseEvent
    window.recording_process = MagicMock()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.No,
    )
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window.recording_process is not None  # processo não foi terminado


def test_close_event_terminates_recording_when_user_confirms(window, monkeypatch):
    from PyQt6.QtGui import QCloseEvent
    proc = MagicMock()
    window.recording_process = proc
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    event = QCloseEvent()
    window.closeEvent(event)
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
    assert event.isAccepted()
    assert window.recording_process is None
