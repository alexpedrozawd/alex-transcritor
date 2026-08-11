"""Testes de alex_transcritor.diarize — foco em merge_with_transcript (função
pura, sem pyannote/torch no caminho)."""

import pytest

from alex_transcritor import diarize


def test_run_pipeline_raises_clearly_when_pyannote_missing(monkeypatch):
    monkeypatch.setattr(diarize, "Pipeline", None)
    with pytest.raises(RuntimeError, match="pyannote"):
        diarize.run_pipeline("/tmp/audio.flac", "token")


def test_run_pipeline_loads_waveform_instead_of_file_path(monkeypatch, tmp_path):
    """Regressão: o pyannote.audio 4.x delega a decodificação nativa ao
    torchcodec, que não carrega em sistemas ROCm (falta lib CUDA). run_pipeline
    tem que pré-carregar o áudio via soundfile e passar um dict de waveform —
    nunca o caminho do arquivo direto."""
    sf = pytest.importorskip("soundfile")
    torch = pytest.importorskip("torch")
    import numpy as np

    audio_path = tmp_path / "audio.wav"
    sf.write(str(audio_path), np.zeros(1600, dtype="float32"), 16000)

    calls = {}

    class FakeSegment:
        def __init__(self, start, end):
            self.start, self.end = start, end

    class FakeAnnotation:
        def itertracks(self, yield_label=True):
            yield FakeSegment(0.0, 1.0), None, "SPEAKER_00"

    class FakePipeline:
        def to(self, device):
            calls["device"] = device
            return self

        def __call__(self, file):
            calls["file"] = file
            return FakeAnnotation()

    class FakePipelineClass:
        @staticmethod
        def from_pretrained(model_id, token):
            calls["model_id"] = model_id
            calls["token"] = token
            return FakePipeline()

    monkeypatch.setattr(diarize, "Pipeline", FakePipelineClass)
    turns = diarize.run_pipeline(str(audio_path), "hf_token", device="cpu")

    assert turns == [(0.0, 1.0, "SPEAKER_00")]
    assert calls["model_id"] == diarize.PIPELINE_ID
    assert calls["token"] == "hf_token"
    assert str(calls["device"]) == "cpu"
    # nunca o caminho do arquivo — sempre o waveform pré-carregado
    assert isinstance(calls["file"], dict)
    assert calls["file"]["sample_rate"] == 16000
    assert isinstance(calls["file"]["waveform"], torch.Tensor)
    assert calls["file"]["waveform"].shape == (1, 1600)


def test_single_speaker_throughout():
    segments = [{"start": 0.0, "end": 1.0, "text": "oi"}, {"start": 1.0, "end": 2.0, "text": "tudo bem"}]
    turns = [(0.0, 2.0, "SPEAKER_00")]
    assert diarize.merge_with_transcript(segments, turns) == "Pessoa 1: oi tudo bem"


def test_alternating_speakers_clean_boundaries():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "oi"},
        {"start": 1.0, "end": 2.0, "text": "oi de volta"},
        {"start": 2.0, "end": 3.0, "text": "tudo bem?"},
    ]
    turns = [(0.0, 1.0, "SPEAKER_01"), (1.0, 2.0, "SPEAKER_00"), (2.0, 3.0, "SPEAKER_01")]
    result = diarize.merge_with_transcript(segments, turns)
    assert result == "Pessoa 1: oi\n\nPessoa 2: oi de volta\n\nPessoa 1: tudo bem?"


def test_pessoa_1_is_whoever_speaks_first_regardless_of_raw_id_order():
    segments = [{"start": 0.0, "end": 1.0, "text": "primeiro"}, {"start": 1.0, "end": 2.0, "text": "segundo"}]
    # SPEAKER_05 fala primeiro mesmo tendo um número interno maior.
    turns = [(0.0, 1.0, "SPEAKER_05"), (1.0, 2.0, "SPEAKER_01")]
    result = diarize.merge_with_transcript(segments, turns)
    assert result.startswith("Pessoa 1: primeiro")
    assert "Pessoa 2: segundo" in result


def test_segment_spanning_speaker_change_picks_max_overlap():
    # Segmento de 0 a 3s: 1s com SPEAKER_00, 2s com SPEAKER_01 -> vence SPEAKER_01.
    segments = [{"start": 0.0, "end": 3.0, "text": "trecho ambíguo"}]
    turns = [(0.0, 1.0, "SPEAKER_00"), (1.0, 3.0, "SPEAKER_01")]
    assert diarize.merge_with_transcript(segments, turns) == "Pessoa 1: trecho ambíguo"


def test_segment_in_silence_gap_inherits_previous_speaker():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 5.0, "end": 6.0, "text": "b"}]
    turns = [(0.0, 1.0, "SPEAKER_00")]  # nada cobre 5.0-6.0
    assert diarize.merge_with_transcript(segments, turns) == "Pessoa 1: a b"


def test_first_segment_in_silence_gap_falls_back_to_unknown():
    segments = [{"start": 5.0, "end": 6.0, "text": "sozinho"}]
    turns = []
    assert diarize.merge_with_transcript(segments, turns) == "Pessoa 1: sozinho"


def test_no_turns_at_all():
    segments = [{"start": 0.0, "end": 1.0, "text": "x"}, {"start": 1.0, "end": 2.0, "text": "y"}]
    assert diarize.merge_with_transcript(segments, []) == "Pessoa 1: x y"


def test_empty_segments_returns_empty_string():
    assert diarize.merge_with_transcript([], []) == ""


def test_blank_text_segments_are_skipped():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "  "},
        {"start": 1.0, "end": 2.0, "text": "válido"},
    ]
    turns = [(0.0, 2.0, "SPEAKER_00")]
    assert diarize.merge_with_transcript(segments, turns) == "Pessoa 1: válido"
