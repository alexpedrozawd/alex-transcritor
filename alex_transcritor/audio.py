"""Construção dos comandos de áudio do ffmpeg (gravação e pré-processamento)."""

import re
import subprocess
from pathlib import Path

from .constants import AUDIO_FORMATS, DEFAULT_AUDIO_FORMAT

#: Whisper reamostra tudo para 16 kHz mono internamente; gravar direto nesse
#: formato evita uma conversão e reduz o tamanho do arquivo.
SAMPLE_RATE = "16000"

#: Pico alvo após a normalização, em dBFS. -3 dB deixa margem contra clipping.
TARGET_PEAK_DB = -3.0

#: Só vale normalizar quando há folga real. Medido com áudio sintético em
#: português: um trecho a -24 dB de pico caiu de 23,3% para 12,8% de WER com
#: ganho puro, enquanto aplicar filtro em áudio já adequado piorou o resultado
#: (19,8% → 24,4%). Por isso o ganho é condicional, e sem compressão dinâmica.
MIN_GAIN_DB = 3.0

_PEAK_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def unique_path(directory: str, stem: str, suffix: str) -> Path:
    """Caminho inédito em ``directory``, adicionando ``-2``, ``-3``… se necessário.

    Evita que uma segunda gravação com o mesmo nome apague silenciosamente o
    áudio e a transcrição da primeira.
    """
    base = Path(directory)
    candidate = base / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = base / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def record_command(
    output_path: str,
    monitor: str = "",
    mic: str = "",
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    live_pcm: bool = False,
) -> list[str]:
    """Comando ffmpeg para gravar as fontes indicadas em ``output_path``.

    Informar ``monitor`` e ``mic`` juntos mistura as duas fontes — o caso de uma
    reunião em que se quer tanto o interlocutor quanto a própria voz.

    ``live_pcm=True`` acrescenta uma segunda saída, PCM bruto em ``pipe:1``,
    para um consumidor de transcrição ao vivo — sem alterar a saída principal.
    Com duas fontes, o mix (``amix``) só pode ser consumido uma vez por saída;
    por isso ``asplit`` duplica o stream quando as duas saídas coexistem.
    """
    inputs = [device for device in (monitor, mic) if device]
    if not inputs:
        raise ValueError("Nenhuma fonte de áudio informada.")

    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for device in inputs:
        cmd += ["-f", "pulse", "-i", device]

    multi = len(inputs) > 1
    if multi:
        mix = f"amix=inputs={len(inputs)}:duration=longest:normalize=0,aresample=async=1"
        if live_pcm:
            cmd += ["-filter_complex", f"{mix},asplit=2[mix_principal][mix_vivo]"]
            cmd += ["-map", "[mix_principal]"]
        else:
            cmd += ["-filter_complex", mix]

    cmd += ["-ac", "1", "-ar", SAMPLE_RATE]
    cmd += AUDIO_FORMATS.get(audio_format, AUDIO_FORMATS[DEFAULT_AUDIO_FORMAT])
    cmd.append(output_path)

    if live_pcm:
        if multi:
            cmd += ["-map", "[mix_vivo]"]
        cmd += ["-f", "s16le", "-ar", SAMPLE_RATE, "-ac", "1", "pipe:1"]

    return cmd


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def peak_db(path: str) -> float | None:
    """Pico do arquivo em dBFS, ou ``None`` se não for possível medir."""
    result = _run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        timeout=300,
    )
    if result is None:
        return None
    match = _PEAK_RE.search(result.stderr or "")
    return float(match.group(1)) if match else None


def needed_gain_db(path: str) -> float:
    """Ganho a aplicar para levar o pico até ``TARGET_PEAK_DB``; ``0`` se não convém.

    Devolve zero para áudio já em nível adequado — normalizar nesse caso degrada
    a transcrição em vez de ajudar.
    """
    peak = peak_db(path)
    if peak is None:
        return 0.0
    gain = TARGET_PEAK_DB - peak
    return round(gain, 1) if gain >= MIN_GAIN_DB else 0.0


def gain_command(source_path: str, target_path: str, gain_db: float) -> list[str]:
    """Comando ffmpeg que gera uma cópia amplificada para alimentar o Whisper.

    Ganho puro, sem compressão nem equalização: preserva a forma de onda e só
    corrige o nível. A gravação original permanece intacta.
    """
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", source_path,
        "-af", f"volume={gain_db}dB",
        "-ac", "1", "-ar", SAMPLE_RATE,
        "-c:a", "flac",
        target_path,
    ]


def probe_duration(path: str) -> float:
    """Duração do áudio em segundos; ``0.0`` se não for possível determinar."""
    result = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        timeout=60,
    )
    if result is None:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0
