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

#: Contexto deslizante da diarização ao vivo. Precisa ser bem maior que a
#: janela de transcrição: com poucos segundos o pyannote não tem material para
#: separar vozes de forma consistente, e execuções consecutivas precisam
#: compartilhar bastante áudio para o SpeakerTracker casar quem é quem.
DIARIZE_CONTEXT_S = 45.0
DIARIZE_CONTEXT_BYTES = int(DIARIZE_CONTEXT_S * BYTES_PER_SECOND)

#: A diarização roda a cada N janelas transcritas, não em todas: ela custa bem
#: mais que a transcrição de uma janela, e os rótulos mudam devagar. Ajustar
#: se o atraso crescer — cada aumento aqui reduz o custo por bloco.
DIARIZE_EVERY_N_WINDOWS = 2


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


#: O pipeline do pyannote é carregado uma vez e reaproveitado: ao vivo ele é
#: chamado a cada poucos segundos, e recarregar o modelo toda vez dominaria o
#: tempo de resposta. Ao contrário do passe em lote, que roda uma vez por job.
_pipeline_cache: dict = {}


def load_diarization_pipeline(hf_token: str):
    if "pipeline" not in _pipeline_cache:
        import torch

        from . import diarize as diarize_module

        if diarize_module.Pipeline is None:
            raise RuntimeError("pyannote.audio não está instalado no servidor.")
        pipeline = diarize_module.Pipeline.from_pretrained(
            diarize_module.PIPELINE_ID, token=hf_token
        )
        pipeline.to(torch.device("cuda"))
        _pipeline_cache["pipeline"] = pipeline
    return _pipeline_cache["pipeline"]


def diarize_pcm(pcm: bytes, hf_token: str) -> list[tuple[float, float, str]]:
    """Roda a diarização sobre PCM bruto em memória.

    Diferente de ``diarize.run_pipeline``, que recebe um caminho de arquivo:
    aqui o áudio nunca chega a existir em disco — é o trecho deslizante que já
    está na memória da sessão. Evita escrever gravação em disco a cada bloco.
    """
    import numpy as np
    import torch

    pipeline = load_diarization_pipeline(hf_token)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    waveform = torch.from_numpy(samples).unsqueeze(0)  # (canal, tempo)
    annotation = pipeline({"waveform": waveform, "sample_rate": 16000})
    return [
        (segment.start, segment.end, speaker)
        for segment, _, speaker in annotation.itertracks(yield_label=True)
    ]


class SpeakerTracker:
    """Mantém "Pessoa N" apontando para a mesma pessoa ao longo da sessão.

    O pyannote agrupa vozes **dentro do áudio que recebe**: os rótulos
    (``SPEAKER_00``...) são locais a cada execução. Rodando sobre uma janela
    deslizante, nada garante que ``SPEAKER_00`` de agora seja o mesmo de 6 s
    atrás — e um rótulo que troca de pessoa é pior que rótulo nenhum, porque
    parece confiável e não é.

    A estabilidade vem da sobreposição: execuções consecutivas compartilham
    quase todo o áudio, então cada rótulo novo é casado com a pessoa que já
    ocupava aqueles mesmos instantes na execução anterior. Só quando nada
    coincide é que uma pessoa nova é criada.

    Puro, sem GPU e sem modelo — testável com dados sintéticos.
    """

    def __init__(self) -> None:
        self._history: list[tuple[float, float, str]] = []
        self._count = 0

    def label_turns(
        self, turns: list[tuple[float, float, str]]
    ) -> list[tuple[float, float, str]]:
        """Converte turnos com rótulo bruto em turnos com "Pessoa N" estável."""
        mapping: dict[str, str] = {}
        for raw in _ordered_raw_labels(turns):
            intervals = [(s, e) for s, e, label in turns if label == raw]
            person = self._best_match(intervals, taken=set(mapping.values()))
            if person is None:
                self._count += 1
                person = f"Pessoa {self._count}"
            mapping[raw] = person

        labeled = [(s, e, mapping[raw]) for s, e, raw in turns]
        # O histórico guarda só a rodada mais recente: é o que descreve os
        # instantes que a próxima execução vai reencontrar na sobreposição.
        self._history = labeled
        return labeled

    def _best_match(
        self, intervals: list[tuple[float, float]], taken: set[str]
    ) -> str | None:
        scores: dict[str, float] = {}
        for start, end in intervals:
            for h_start, h_end, person in self._history:
                if person in taken:  # uma pessoa não pode receber dois rótulos
                    continue
                overlap = min(end, h_end) - max(start, h_start)
                if overlap > 0:
                    scores[person] = scores.get(person, 0.0) + overlap
        if not scores:
            return None
        return max(scores, key=scores.get)


def _ordered_raw_labels(turns: list[tuple[float, float, str]]) -> list[str]:
    """Rótulos brutos por ordem de primeira fala, sem repetir."""
    seen: list[str] = []
    for _start, _end, label in sorted(turns, key=lambda t: t[0]):
        if label not in seen:
            seen.append(label)
    return seen


def speaker_for(start_s: float, end_s: float, turns: list[tuple[float, float, str]]) -> str:
    """Quem fala num trecho: o turno com maior sobreposição temporal."""
    best, best_overlap = "", 0.0
    for t_start, t_end, person in turns:
        overlap = min(end_s, t_end) - max(start_s, t_start)
        if overlap > best_overlap:
            best, best_overlap = person, overlap
    return best


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
