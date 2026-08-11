"""Transcrição incremental (ao vivo), opcional e best-effort.

Roda em paralelo à gravação principal, lendo PCM bruto do stdout do ffmpeg
(ver ``audio.record_command(..., live_pcm=True)``) e decodificando em janelas
curtas com ``faster-whisper``. Qualquer falha aqui é reportada por sinal e
nunca deve interromper a gravação/transcrição principal — por isso o import
do motor é protegido e toda a ``run()`` está isolada em try/except.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from PyQt6.QtCore import QThread, pyqtSignal

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover — exercitado via testes com monkeypatch
    WhisperModel = None

#: PCM s16le mono a 16 kHz: 2 bytes por amostra, 16000 amostras/segundo.
BYTES_PER_SECOND = 16000 * 2

#: Janela de decodificação e sobreposição usada só como contexto acústico —
#: o texto da sobreposição já foi emitido pela janela anterior e é descartado
#: (ver ``_should_emit``), não reemitido.
WINDOW_S = 3.0
OVERLAP_S = 0.75
WINDOW_BYTES = int(WINDOW_S * BYTES_PER_SECOND)
OVERLAP_BYTES = int(OVERLAP_S * BYTES_PER_SECOND)
ADVANCE_BYTES = WINDOW_BYTES - OVERLAP_BYTES

#: Quanto silêncio ao final da janela para considerar a fala finalizada (pausa
#: real) em vez de cortada no meio — só afeta o rótulo ``is_final``.
TRAILING_SILENCE_S = 0.3

READ_CHUNK_BYTES = 4096


@dataclass
class LiveSegment:
    """Um trecho decodificado da fala ao vivo.

    Dataclass simples, sem Qt, para que um futuro cruzamento por palavra-chave
    (fase seguinte, fora de escopo aqui) possa consumir o sinal ``segment``
    sem depender do PyQt6.
    """

    text: str
    start_s: float
    end_s: float
    is_final: bool  # True = pausa detectada ao fim da janela, não será revisado


def accumulate(buffer: bytes, chunk: bytes) -> tuple[bytes, bytes | None]:
    """Acrescenta ``chunk`` ao ``buffer`` e extrai uma janela pronta, se houver.

    Devolve ``(buffer_restante, janela_ou_None)``. O buffer restante inclui os
    últimos ``OVERLAP_BYTES`` da janela extraída, como contexto para a próxima
    decodificação — função pura, testável sem ffmpeg nem modelo.
    """
    buffer += chunk
    if len(buffer) < WINDOW_BYTES:
        return buffer, None
    window = buffer[:WINDOW_BYTES]
    return buffer[ADVANCE_BYTES:], window


def should_emit(rel_end_s: float, is_first_window: bool) -> bool:
    """Um segmento cujo fim cai dentro da sobreposição já foi emitido antes."""
    return is_first_window or rel_end_s > OVERLAP_S


class LiveTranscriber(QThread):
    """Lê PCM do stdout do ffmpeg e emite texto incremental por janela."""

    segment = pyqtSignal(object)  # LiveSegment
    failed = pyqtSignal(str)      # não fatal — a gravação principal segue

    def __init__(
        self,
        stdout: BinaryIO,
        model_size: str = "small",
        device: str = "cpu",
        language: str = "pt",
    ) -> None:
        super().__init__()
        self._stdout = stdout
        self.model_size = model_size
        self.device = device
        self.language = language
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> None:
        if WhisperModel is None:
            self.failed.emit(
                "faster-whisper não instalado — veja requirements-live.txt"
            )
            return
        try:
            model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
        except Exception as exc:  # rede de segurança: modelo não deve matar a thread calado
            self.failed.emit(f"Não foi possível carregar o modelo ao vivo: {exc}")
            return

        buffer = b""
        elapsed_s = 0.0
        first_window = True
        already_failed = False

        while not self._stopped:
            chunk = self._read_chunk()
            if chunk is None:
                break
            if not chunk:
                continue
            buffer, window = accumulate(buffer, chunk)
            if window is None:
                continue
            try:
                self._transcribe_window(model, window, elapsed_s, first_window)
            except Exception as exc:
                if not already_failed:
                    self.failed.emit(f"Erro na transcrição ao vivo: {exc}")
                    already_failed = True
            elapsed_s += ADVANCE_BYTES / BYTES_PER_SECOND
            first_window = False

    def _read_chunk(self) -> bytes | None:
        if self._stdout is None:
            return None
        try:
            data = self._stdout.read(READ_CHUNK_BYTES)
        except (OSError, ValueError):
            return None
        return data or None

    def _transcribe_window(
        self, model, window: bytes, window_start_s: float, is_first_window: bool
    ) -> None:
        import numpy as np

        audio = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        segments = list(segments)
        last_idx = len(segments) - 1
        for i, seg in enumerate(segments):
            if not should_emit(seg.end, is_first_window):
                continue
            text = seg.text.strip()
            if not text:
                continue
            is_last = i == last_idx
            finalized = (not is_last) or (WINDOW_S - seg.end > TRAILING_SILENCE_S)
            self.segment.emit(
                LiveSegment(
                    text=text,
                    start_s=window_start_s + seg.start,
                    end_s=window_start_s + seg.end,
                    is_final=finalized,
                )
            )
