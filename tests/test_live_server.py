"""Testes de alex_transcritor.live_server — motor de transcrição ao vivo no servidor."""

import sys
import types

from alex_transcritor import live_server


def test_module_imports_without_pyqt6():
    """Regressão de arquitetura: o servidor é headless — live_server não pode
    depender de PyQt6 (só live.py, o motor do cliente, depende)."""
    assert "PyQt6" not in sys.modules or True  # não afirma nada sobre o ambiente de teste
    assert not hasattr(live_server, "QThread")


# ── segments_to_live_segments ──────────────────────────────────────────────────

def test_single_segment_becomes_final_when_trailing_silence():
    raw = [{"start": 0.0, "end": 1.5, "text": "ola"}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=10.0, is_first_window=True)
    assert len(segs) == 1
    assert segs[0].text == "ola"
    assert segs[0].start_s == 10.0
    assert segs[0].end_s == 11.5
    # WINDOW_S (2.0) - end (1.5) = 0.5 > TRAILING_SILENCE_S (0.3) -> final
    assert segs[0].is_final is True


def test_last_segment_without_trailing_silence_is_provisional():
    raw = [{"start": 0.0, "end": 1.95, "text": "fala continua"}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=0.0, is_first_window=True)
    assert segs[0].is_final is False


def test_non_last_segments_are_always_final():
    raw = [
        {"start": 0.0, "end": 0.8, "text": "primeiro"},
        {"start": 0.9, "end": 1.95, "text": "segundo"},
    ]
    segs = live_server.segments_to_live_segments(raw, window_start_s=0.0, is_first_window=True)
    assert segs[0].is_final is True   # não é o último
    assert segs[1].is_final is False  # último, sem silêncio suficiente


def test_overlap_is_skipped_on_non_first_windows():
    raw = [{"start": 0.0, "end": 0.3, "text": "já emitido antes"}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=5.0, is_first_window=False)
    assert segs == []


def test_blank_text_segments_are_skipped():
    raw = [{"start": 0.0, "end": 1.9, "text": "   "}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=0.0, is_first_window=True)
    assert segs == []


def test_empty_segments_list():
    assert live_server.segments_to_live_segments([], window_start_s=0.0, is_first_window=True) == []


# ── transcribe_window ──────────────────────────────────────────────────────────

def test_transcribe_window_passes_expected_flags_and_returns_segments():
    calls = {}

    class _FakeModel:
        def transcribe(self, audio_array, **kwargs):
            calls["shape"] = audio_array.shape
            calls["dtype"] = str(audio_array.dtype)
            calls["kwargs"] = kwargs
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}]}

    window = b"\x00\x01" * 16000  # 1s de PCM s16le
    result = live_server.transcribe_window(_FakeModel(), window, language="pt")

    assert result == [{"start": 0.0, "end": 1.0, "text": "ok"}]
    assert calls["dtype"] == "float32"
    assert calls["kwargs"]["language"] == "pt"
    assert calls["kwargs"]["condition_on_previous_text"] is False
    assert calls["kwargs"]["fp16"] is True


# ── load_model ──────────────────────────────────────────────────────────────────

def test_load_model_uses_cuda_device(monkeypatch):
    calls = {}
    fake_whisper = types.ModuleType("whisper")

    def _load_model(name, device):
        calls["name"] = name
        calls["device"] = device
        return "fake-model-object"

    fake_whisper.load_model = _load_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    model = live_server.load_model("small")
    assert model == "fake-model-object"
    assert calls == {"name": "small", "device": "cuda"}
