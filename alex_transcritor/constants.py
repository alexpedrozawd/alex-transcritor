from pathlib import Path

INSTALL_DIR: Path = Path(__file__).parent.parent
WHISPER_BIN: str = str(INSTALL_DIR / "venv" / "bin" / "whisper")
ICON_PATH: str = str(INSTALL_DIR / "assets" / "icon.png")
SOCKET_NAME: str = "alex-transcritor-instance"
