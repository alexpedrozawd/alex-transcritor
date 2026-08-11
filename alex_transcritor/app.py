import shutil
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .constants import SOCKET_NAME, WHISPER_BIN
from .config import load_config
from .ui.main_window import MainWindow


def _check_dependencies() -> list[str]:
    missing = []
    for cmd in ("ffmpeg", "ffprobe", "pactl"):
        if not shutil.which(cmd):
            missing.append(cmd)
    if load_config()["transcription_backend"] == "local" and not Path(WHISPER_BIN).exists():
        missing.append("whisper (ambiente virtual)")
    return missing


def _is_already_running() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    connected = socket.waitForConnected(300)
    if connected:
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
    socket.close()
    return connected


def _on_new_connection(server: QLocalServer, window: MainWindow) -> None:
    conn = server.nextPendingConnection()
    if conn:
        conn.waitForReadyRead(300)
        window._show_window()
        conn.disconnectFromServer()


def _start_server(window: MainWindow) -> QLocalServer:
    server = QLocalServer()
    # Restringe o socket ao próprio usuário: sem isso qualquer conta local pode
    # conectar nele e manipular a janela do app.
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(SOCKET_NAME)
    server.listen(SOCKET_NAME)
    server.newConnection.connect(lambda: _on_new_connection(server, window))
    return server


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("alex-transcritor")
    app.setDesktopFileName("alex-transcritor")
    app.setQuitOnLastWindowClosed(True)

    if _is_already_running():
        sys.exit(0)

    missing = _check_dependencies()
    if missing:
        warn = QMessageBox()
        warn.setWindowTitle("Dependências ausentes")
        warn.setIcon(QMessageBox.Icon.Warning)
        warn.setText(
            "As seguintes dependências não foram encontradas:\n\n"
            + "\n".join(f"  • {m}" for m in missing)
            + "\n\nO app pode não funcionar corretamente.\n"
            "Consulte o manual de instalação."
        )
        warn.exec()

    window = MainWindow()
    window.show()
    server = _start_server(window)  # noqa: F841 — mantém o socket vivo enquanto o app roda

    sys.exit(app.exec())
