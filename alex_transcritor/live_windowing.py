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
#: (ver ``should_emit``), não reemitido.
#:
#: O piso de latência é WINDOW_S + tempo de inferência, mas encurtar a janela
#: **destrói a qualidade**: o Whisper foi treinado com 30 s de contexto e
#: degrada muito com trechos curtos isolados. Medido na RX 9070 com a mesma
#: frase, modelo "small":
#:
#:   2 s → "Vamos começar a reunir a união" / "pois alemos sob o cronóter"
#:   4 s → "Bom dia a todos. Vamos começar a reunião de hoje."
#:   6 s → frase inteira correta, incluindo "o primeiro ponto é o relatório"
#:
#: 6 s é o valor escolhido: foi o único que transcreveu a frase inteira sem
#: erro no teste acima. Texto ilegível não serve para nada, por mais rápido
#: que chegue — e ~6 s de atraso ainda dá para acompanhar uma reunião.
#: Baixar para 4 s troca precisão por ~2 s de latência, se preferir.
WINDOW_S = 6.0
OVERLAP_S = 1.5
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
    speaker: str = ""  # "Pessoa 1", "Pessoa 2"... vazio quando não há diarização


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
