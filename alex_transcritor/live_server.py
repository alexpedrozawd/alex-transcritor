"""Motor de transcrição ao vivo processado no servidor.

Reaproveita a matemática de janelamento/deduplicação por sobreposição já
testada em ``alex_transcritor/live.py`` (``accumulate``, ``should_emit``,
``LiveSegment``) — isso não muda com o motor de inferência. O que muda é o
motor em si: aqui é ``openai-whisper`` via API Python (não a CLI), rodando
na GPU ROCm do servidor, em vez de ``faster-whisper`` no cliente — o
CTranslate2 por trás do faster-whisper não tem suporte ROCm liberado ainda
(o próprio repositório oficial de suporte a AMD não tem nenhum release
publicado), então não dá para usar o mesmo motor da fase anterior aqui.
"""

from __future__ import annotations

from .live_windowing import (
    ADVANCE_BYTES,
    BYTES_PER_SECOND,
    TRAILING_SILENCE_S,
    WINDOW_S,
    LiveSegment,
    accumulate,
    should_emit,
)

__all__ = [
    "ADVANCE_BYTES",
    "BYTES_PER_SECOND",
    "LiveSegment",
    "accumulate",
    "load_model",
    "should_emit",
    "transcribe_window",
]


def load_model(model_name: str):
    """Carrega o whisper na GPU do servidor — uma vez por sessão WS.

    Import de ``whisper`` fica aqui dentro (não no topo do módulo) para não
    tornar esse módulo pesado de importar quando só a transcrição em lote
    está em uso; ``server.py`` já importa ``whisper`` indiretamente via CLI,
    mas aqui é a API Python direta.
    """
    import whisper

    return whisper.load_model(model_name, device="cuda")


#: Abaixo deste RMS (em áudio normalizado -1..1) a janela é tratada como sem
#: fala e nem chega ao modelo. Whisper foi treinado com janelas de 30s e faz
#: padding com silêncio nas curtas — alimentar silêncio quase puro é a receita
#: clássica de alucinação ("Legendas pela comunidade...", tokens CJK soltos).
#: Também economiza GPU: janela muda não custa inferência nenhuma.
SILENCE_RMS = 0.005

#: Segmento que o próprio modelo considera provável não-fala é descartado.
#: O limiar interno do Whisper não basta quando cada janela é decodificada
#: isoladamente, sem o contexto de 30s que ele espera.
MAX_NO_SPEECH_PROB = 0.6


def is_silent(window: bytes) -> bool:
    """True quando a janela não tem energia suficiente para conter fala."""
    import numpy as np

    samples = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return True
    return float(np.sqrt(np.mean(samples**2))) < SILENCE_RMS


def transcribe_window(model, window: bytes, language: str, initial_prompt: str = "") -> list[dict]:
    """Roda uma janela de PCM bruto pelo whisper; devolve os segmentos brutos
    (``start``/``end``/``text``, mesmo shape usado no merge de diarização).

    As flags espelham o passe em lote (``server.py::JobManager._run_whisper``),
    que produz texto limpo nesta mesma GPU. A diferença mais importante é
    ``temperature=0``: com o padrão do Whisper, uma decodificação que bate nos
    limiares internos é refeita com temperatura crescente até 1.0 — e
    temperatura alta numa janela curta gera exatamente o texto alucinado, com
    caracteres de outros alfabetos, visto em uso real.
    """
    import numpy as np

    audio_array = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
    result = model.transcribe(
        audio_array,
        # "auto" não é um código de idioma: o Whisper espera None para
        # detectar sozinho. O passe em lote já trata assim, omitindo a flag.
        language=None if language in ("", "auto") else language,
        initial_prompt=initial_prompt or None,
        temperature=0.0,
        beam_size=5,
        condition_on_previous_text=False,
        fp16=True,
    )
    return [
        seg for seg in result["segments"]
        if seg.get("no_speech_prob", 0.0) <= MAX_NO_SPEECH_PROB
    ]


def segments_to_live_segments(
    raw_segments: list[dict], window_start_s: float, is_first_window: bool
) -> list[LiveSegment]:
    """Filtra a sobreposição já emitida e converte para ``LiveSegment`` —
    mesma lógica de finalização usada no cliente (``live.py::_transcribe_window``),
    extraída aqui como função pura para ser testável sem WebSocket/GPU."""
    live_segments: list[LiveSegment] = []
    last_idx = len(raw_segments) - 1
    for i, seg in enumerate(raw_segments):
        if not should_emit(seg["end"], is_first_window):
            continue
        text = seg["text"].strip()
        if not text:
            continue
        is_last = i == last_idx
        finalized = (not is_last) or (WINDOW_S - seg["end"] > TRAILING_SILENCE_S)
        live_segments.append(
            LiveSegment(
                text=text,
                start_s=window_start_s + seg["start"],
                end_s=window_start_s + seg["end"],
                is_final=finalized,
            )
        )
    return live_segments
