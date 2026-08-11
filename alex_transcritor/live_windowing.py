"""Janelamento/deduplicação de áudio ao vivo — puro, sem Qt e sem motor de
transcrição, para ser reaproveitado tanto pelo cliente (``live.py``, PyQt6 +
faster-whisper) quanto pelo servidor (``live_server.py``, openai-whisper via
ROCm). Nenhum desses dois deve ser dependência um do outro.
"""

from __future__ import annotations

from dataclasses import dataclass

#: PCM s16le mono a 16 kHz: 2 bytes por amostra, 16000 amostras/segundo.
BYTES_PER_SECOND = 16000 * 2

#: Janela de decodificação e sobreposição usada só como contexto acústico —
#: o texto da sobreposição já foi emitido pela janela anterior e é descartado
#: (ver ``should_emit``), não reemitido. O piso mínimo de latência é
#: WINDOW_S + tempo de transcrição — reduzir a janela é o jeito mais direto
#: de acelerar a resposta, à custa de um pouco menos de contexto por trecho
#: decodificado (mais chance de fragmentação, principalmente em CPU).
WINDOW_S = 2.0
OVERLAP_S = 0.5
WINDOW_BYTES = int(WINDOW_S * BYTES_PER_SECOND)
OVERLAP_BYTES = int(OVERLAP_S * BYTES_PER_SECOND)
ADVANCE_BYTES = WINDOW_BYTES - OVERLAP_BYTES

#: Quanto silêncio ao final da janela para considerar a fala finalizada (pausa
#: real) em vez de cortada no meio — só afeta o rótulo ``is_final``.
TRAILING_SILENCE_S = 0.3


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
