import subprocess
from PyQt6.QtCore import QThread, pyqtSignal


class WhisperThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, audio_path: str, output_dir: str, whisper_bin: str) -> None:
        super().__init__()
        self.audio_path = audio_path
        self.output_dir = output_dir
        self.whisper_bin = whisper_bin

    def run(self) -> None:
        try:
            result = subprocess.run(
                [
                    self.whisper_bin,
                    self.audio_path,
                    "--language", "Portuguese",
                    "--model", "small",
                    "--output_format", "txt",
                    "--output_dir", self.output_dir,
                    "--fp16", "False",
                ],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if result.returncode == 0:
                self.finished.emit()
            else:
                self.error.emit(result.stderr or "Whisper retornou erro sem mensagem.")
        except FileNotFoundError:
            self.error.emit(
                f"Binário do Whisper não encontrado: {self.whisper_bin}\n"
                "Verifique se o Whisper está instalado no ambiente virtual."
            )
        except subprocess.TimeoutExpired:
            self.error.emit("Tempo limite de transcrição excedido (1 hora).")
        except Exception as exc:
            self.error.emit(f"Erro inesperado na transcrição: {exc}")
