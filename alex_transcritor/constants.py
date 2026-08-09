import shutil
import sys
from pathlib import Path

INSTALL_DIR: Path = Path(__file__).parent.parent
ICON_PATH: str = str(INSTALL_DIR / "assets" / "icon.png")
SOCKET_NAME: str = "alex-transcritor-instance"

#: Formatos de áudio suportados na gravação: extensão → argumentos de codec do ffmpeg.
#: FLAC é o padrão — sem perda e ~40% menor que WAV. MP3 fica disponível por
#: compatibilidade, mas degrada a transcrição (o encoder usa ~24 kb/s em 16 kHz mono).
AUDIO_FORMATS: dict[str, list[str]] = {
    "flac": ["-c:a", "flac", "-compression_level", "5"],
    "wav": ["-c:a", "pcm_s16le"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
}
DEFAULT_AUDIO_FORMAT: str = "flac"

#: Modelos Whisper oferecidos na interface, do mais rápido ao mais preciso.
WHISPER_MODELS: tuple[str, ...] = (
    "tiny", "base", "small", "medium", "large-v3", "turbo",
)

#: VRAM aproximada (GB) exigida por modelo pela implementação de referência do
#: Whisper, que mantém os pesos em float32 mesmo com --fp16 True.
#: Limites verificados em uma GTX 1650 (3,64 GiB utilizáveis): "small" roda,
#: "medium" e "turbo" abortam com CUDA out of memory.
MODEL_VRAM_GB: dict[str, float] = {
    "tiny": 0.5, "base": 0.8, "small": 2.0, "medium": 6.0,
    "large-v3": 10.0, "turbo": 5.0,
}


def whisper_bin() -> str:
    """Caminho do executável do Whisper.

    Prefere o venv da instalação; em execução a partir do repositório clonado
    (sem venv local) cai para o ``whisper`` disponível no PATH.
    """
    venv_bin = INSTALL_DIR / "venv" / "bin" / "whisper"
    if venv_bin.exists():
        return str(venv_bin)
    sibling = Path(sys.executable).parent / "whisper"
    if sibling.exists():
        return str(sibling)
    return shutil.which("whisper") or str(venv_bin)


WHISPER_BIN: str = whisper_bin()
