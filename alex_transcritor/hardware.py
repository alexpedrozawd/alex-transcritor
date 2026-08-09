"""Detecção de GPU para escolher entre CUDA e CPU sem carregar o PyTorch."""

import subprocess

from .constants import MODEL_VRAM_GB

#: Margem sobre a estimativa de VRAM. A implementação de referência do Whisper
#: mantém os pesos em float32 mesmo com --fp16 True, então a exigência real fica
#: bem acima do tamanho nominal do modelo.
VRAM_HEADROOM = 1.15


def gpu_vram_gb() -> float:
    """VRAM total da primeira GPU NVIDIA em GB; ``0.0`` se não houver GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 0.0
    if result.returncode != 0:
        return 0.0
    first = result.stdout.strip().splitlines()
    try:
        return float(first[0].strip()) / 1024
    except (IndexError, ValueError):
        return 0.0


def pick_device(model: str, preference: str = "auto") -> str:
    """Escolhe ``cuda`` ou ``cpu`` para o modelo pedido.

    Em ``auto``, só usa a GPU quando a VRAM comporta o modelo — caso contrário o
    Whisper aborta com *CUDA out of memory* no meio da transcrição.
    """
    if preference in ("cuda", "cpu"):
        return preference
    vram = gpu_vram_gb()
    if vram <= 0:
        return "cpu"
    needed = MODEL_VRAM_GB.get(model, 4.0) * VRAM_HEADROOM
    return "cuda" if vram >= needed else "cpu"
