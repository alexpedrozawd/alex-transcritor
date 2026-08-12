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
#: degrada muito com trechos curtos isolados.
#:
#: Escolhido medindo taxa de erro de palavra (WER) contra texto conhecido, com
#: o modelo "turbo" na RX 9070, num áudio de 44 s:
#:
#:   janela 12 s → 9,4% de erro (atraso ~13 s)   ← escolhido
#:   janela 16 s → 25,5%
#:   janela 20 s → 20,8%
#:   janela 25 s → 9,4%
#:   janela 30 s → 5,7% de erro (atraso ~31 s)
#:
#: 30 s é o contexto de treino do Whisper e onde ele erra menos — mesmo
#: patamar do passe em lote (5,8% com voz real). Ainda assim, 12 s é a
#: escolha certa **para o uso real**: o painel existe para acompanhar a
#: reunião enquanto o assunto está em pauta. Com 30 s de janela, somados ao
#: tempo de análise, o comentário chegaria quase um minuto depois — o mesmo
#: problema que motivou o projeto. Os 3,7 pontos de erro a mais custam bem
#: menos que 18 s de defasagem.
#:
#: A sobreposição não é só contexto acústico: é o que evita cortar palavra no
#: meio da emenda entre janelas. Curta demais parte palavras; longa demais faz
#: o mesmo trecho ser transcrito duas vezes, com resultados diferentes — foi
#: exatamente isso que apareceu em uso como "trocou palavras simples".
WINDOW_S = 12.0
OVERLAP_S = 3.0
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
