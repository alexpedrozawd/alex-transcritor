"""Testes do ponto de entrada.

Antes ficavam de fora da cobertura por supostamente exigirem display real; com
``QT_QPA_PLATFORM=offscreen`` (definido no conftest) rodam normalmente.
"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtNetwork import QLocalServer

from alex_transcritor import app as app_module


# ── _check_dependencies ───────────────────────────────────────────────────────

def test_no_missing_dependencies(monkeypatch, tmp_path):
    binary = tmp_path / "whisper"
    binary.write_text("")
    monkeypatch.setattr(app_module, "WHISPER_BIN", str(binary))
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: "/usr/bin/" + cmd)
    assert app_module._check_dependencies() == []


def test_reports_missing_system_commands(monkeypatch, tmp_path):
    binary = tmp_path / "whisper"
    binary.write_text("")
    monkeypatch.setattr(app_module, "WHISPER_BIN", str(binary))
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: None)
    missing = app_module._check_dependencies()
    assert {"ffmpeg", "ffprobe", "pactl"} <= set(missing)


def test_reports_missing_whisper(monkeypatch):
    monkeypatch.setattr(app_module, "WHISPER_BIN", "/nao/existe/whisper")
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: "/usr/bin/" + cmd)
    assert any("whisper" in m for m in app_module._check_dependencies())


def test_ffprobe_is_checked(monkeypatch, tmp_path):
    """probe_duration depende de ffprobe, que nem sempre acompanha o ffmpeg."""
    binary = tmp_path / "whisper"
    binary.write_text("")
    monkeypatch.setattr(app_module, "WHISPER_BIN", str(binary))
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: None if cmd == "ffprobe" else "/x")
    assert app_module._check_dependencies() == ["ffprobe"]


# ── Instância única ───────────────────────────────────────────────────────────

def test_is_already_running_false_without_server(monkeypatch):
    socket = MagicMock()
    socket.waitForConnected.return_value = False
    monkeypatch.setattr(app_module, "QLocalSocket", lambda: socket)
    assert app_module._is_already_running() is False
    socket.close.assert_called_once()


def test_is_already_running_true_and_asks_to_show(monkeypatch):
    socket = MagicMock()
    socket.waitForConnected.return_value = True
    monkeypatch.setattr(app_module, "QLocalSocket", lambda: socket)
    assert app_module._is_already_running() is True
    socket.write.assert_called_once_with(b"show")


# ── Servidor local ────────────────────────────────────────────────────────────

@pytest.fixture
def window():
    return MagicMock()


def test_server_restricts_socket_to_current_user(window, monkeypatch):
    """Sem UserAccessOption qualquer conta local conecta no socket do app."""
    server = MagicMock()
    monkeypatch.setattr(app_module, "QLocalServer", MagicMock(return_value=server))
    app_module.QLocalServer.SocketOption = QLocalServer.SocketOption
    app_module._start_server(window)
    server.setSocketOptions.assert_called_once_with(QLocalServer.SocketOption.UserAccessOption)


def test_server_listens_on_socket_name(window, qtbot):
    server = app_module._start_server(window)
    try:
        assert server.isListening()
        assert app_module.SOCKET_NAME in server.fullServerName()
    finally:
        server.close()
        QLocalServer.removeServer(app_module.SOCKET_NAME)


def test_new_connection_raises_window(window):
    connection = MagicMock()
    server = MagicMock()
    server.nextPendingConnection.return_value = connection
    app_module._on_new_connection(server, window)
    window._show_window.assert_called_once()
    connection.disconnectFromServer.assert_called_once()


def test_new_connection_without_pending_is_noop(window):
    server = MagicMock()
    server.nextPendingConnection.return_value = None
    app_module._on_new_connection(server, window)
    window._show_window.assert_not_called()


# ── main ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def main_stubs(monkeypatch):
    """Neutraliza QApplication, janela e servidor para exercitar main() sem GUI real."""
    stubs = {
        "app": MagicMock(),
        "window": MagicMock(),
        "server": MagicMock(),
        "warned": [],
    }
    stubs["app"].exec.return_value = 0
    monkeypatch.setattr(app_module, "QApplication", MagicMock(return_value=stubs["app"]))
    monkeypatch.setattr(app_module, "MainWindow", MagicMock(return_value=stubs["window"]))
    monkeypatch.setattr(app_module, "_start_server", MagicMock(return_value=stubs["server"]))
    monkeypatch.setattr(app_module, "_is_already_running", lambda: False)
    monkeypatch.setattr(app_module, "_check_dependencies", lambda: [])

    box = MagicMock()
    box.exec.side_effect = lambda: stubs["warned"].append(True)
    monkeypatch.setattr(app_module, "QMessageBox", MagicMock(return_value=box))
    return stubs


def test_main_shows_window_and_runs_event_loop(main_stubs):
    with pytest.raises(SystemExit) as exit_info:
        app_module.main()
    assert exit_info.value.code == 0
    main_stubs["window"].show.assert_called_once()
    main_stubs["app"].exec.assert_called_once()


def test_main_exits_when_another_instance_is_running(main_stubs, monkeypatch):
    monkeypatch.setattr(app_module, "_is_already_running", lambda: True)
    with pytest.raises(SystemExit) as exit_info:
        app_module.main()
    assert exit_info.value.code == 0
    main_stubs["window"].show.assert_not_called()


def test_main_warns_about_missing_dependencies(main_stubs, monkeypatch):
    monkeypatch.setattr(app_module, "_check_dependencies", lambda: ["ffmpeg"])
    with pytest.raises(SystemExit):
        app_module.main()
    assert main_stubs["warned"]
    main_stubs["window"].show.assert_called_once()  # o app abre mesmo assim
