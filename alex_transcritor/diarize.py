"""Diarização (identificação de locutores) — opcional, só usada quando pedida.

Módulo separado de ``server.py`` por dois motivos: mantém o algoritmo de
junção testável sem FastAPI/GPU no caminho, e isola o import do
``pyannote.audio`` (pesado, opcional) do resto do servidor — se ele faltar ou
falhar, só a diarização fica indisponível; a transcrição comum continua
funcionando (ver ``server.py::JobManager._run_diarization_and_merge``, que
trata qualquer exceção daqui como best-effort, nunca fatal).
"""

from __future__ import annotations

try:
    from pyannote.audio import Pipeline
except ImportError:  # pragma: no cover — exercitado via monkeypatch nos testes
    Pipeline = None

#: Modelo com acesso restrito no Hugging Face — a conta dona do token precisa
#: aceitar os termos em huggingface.co uma vez antes do primeiro uso.
PIPELINE_ID = "pyannote/speaker-diarization-3.1"


def run_pipeline(audio_path: str, hf_token: str, device: str = "cuda") -> list[tuple[float, float, str]]:
    """Roda a diarização e devolve turnos ``(start, end, rótulo_do_locutor)``.

    Levanta em qualquer falha (pyannote ausente, token inválido, modelo com
    acesso negado, OOM) — o chamador trata isso como best-effort, nunca fatal.

    O áudio é pré-carregado via ``soundfile`` e passado como waveform em vez
    do caminho do arquivo: o carregamento nativo do pyannote (via torchaudio)
    depende do `torchcodec`, que nesta versão exige bibliotecas CUDA
    (`libnvrtc`) ausentes num sistema ROCm — soundfile não tem essa
    dependência e já é usado internamente pelo próprio pyannote.
    """
    if Pipeline is None:
        raise RuntimeError("pyannote.audio não está instalado no servidor.")
    import soundfile as sf
    import torch

    pipeline = Pipeline.from_pretrained(PIPELINE_ID, token=hf_token)
    pipeline.to(torch.device(device))

    data, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T)  # (tempo, canal) -> (canal, tempo)
    annotation = pipeline({"waveform": waveform, "sample_rate": sample_rate})
    return [
        (segment.start, segment.end, speaker)
        for segment, _, speaker in annotation.itertracks(yield_label=True)
    ]


def merge_with_transcript(segments: list[dict], turns: list[tuple[float, float, str]]) -> str:
    """Função pura: casa segmentos do whisper com turnos de fala do pyannote.

    Para cada segmento, escolhe o turno com maior sobreposição temporal; sem
    nenhuma sobreposição (segmento caiu num silêncio entre turnos), herda o
    locutor do segmento anterior. Rótulos brutos do pyannote (``SPEAKER_00``,
    arbitrários) viram "Pessoa N" pela ordem de primeira fala — não pela
    numeração interna do pyannote. Segmentos consecutivos do mesmo locutor
    formam um só parágrafo.
    """
    labeled: list[tuple[str, str]] = []
    previous_speaker = "UNKNOWN"
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        speaker = _best_speaker(seg["start"], seg["end"], turns) or previous_speaker
        previous_speaker = speaker
        labeled.append((speaker, text))

    if not labeled:
        return ""

    label_map: dict[str, str] = {}

    def friendly(raw: str) -> str:
        if raw not in label_map:
            label_map[raw] = f"Pessoa {len(label_map) + 1}"
        return label_map[raw]

    paragraphs: list[str] = []
    current_speaker: str | None = None
    current_parts: list[str] = []
    for speaker, text in labeled:
        if speaker != current_speaker:
            if current_parts:
                paragraphs.append(f"{friendly(current_speaker)}: {' '.join(current_parts)}")
            current_speaker = speaker
            current_parts = [text]
        else:
            current_parts.append(text)
    if current_parts:
        paragraphs.append(f"{friendly(current_speaker)}: {' '.join(current_parts)}")

    return "\n\n".join(paragraphs)


def _best_speaker(start: float, end: float, turns: list[tuple[float, float, str]]) -> str | None:
    best_speaker = None
    best_overlap = 0.0
    for t_start, t_end, speaker in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker
