"""Testes do LiveTranscriber e das funções puras de janelamento."""

import io

import pytest

from alex_transcritor import live


# ── accumulate / should_emit — puras, sem ffmpeg nem modelo ───────────────────

def test_accumulate_waits_until_window_is_full():
    buffer, window = live.accumulate(b"", b"\x00" * (live.WINDOW_BYTES - 100))
    assert window is None
    assert len(buffer) == live.WINDOW_BYTES - 100


def test_accumulate_extracts_window_and_keeps_overlap_as_context():
    buffer, window = live.accumulate(b"\x00" * (live.WINDOW_BYTES - 100), b"\x00" * 100)
    assert window is not None
    assert len(window) == live.WINDOW_BYTES
    assert len(buffer) == live.OVERLAP_BYTES


def test_accumulate_handles_chunk_larger_than_remaining_window():
    buffer, window = live.accumulate(b"", b"\x00" * (live.WINDOW_BYTES + 5000))
    assert len(window) == live.WINDOW_BYTES
    assert len(buffer) == live.OVERLAP_BYTES + 5000


def test_should_emit_always_true_on_first_window():
    assert live.should_emit(0.1, is_first_window=True) is True


def test_should_emit_skips_text_inside_the_overlap():
    assert live.should_emit(live.OVERLAP_S - 0.1, is_first_window=False) is False


def test_should_emit_allows_text_past_the_overlap():
    assert live.should_emit(live.OVERLAP_S + 0.1, is_first_window=False) is True


# ── LiveTranscriber — engine ausente ───────────────────────────────────────────

def test_run_emits_failed_when_faster_whisper_missing(qtbot, monkeypatch):
    monkeypatch.setattr(live, "WhisperModel", None)
    transcriber = live.LiveTranscriber(io.BytesIO(b""))
    with qtbot.waitSignal(transcriber.failed, timeout=2000) as blocker:
        transcriber.start()
    assert "faster-whisper" in blocker.args[0]
    transcriber.wait(2000)


# ── LiveTranscriber — sinal de segmento, com modelo falso ──────────────────────

class _FakeSegment:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text = text
        self.start = start
        self.end = end


class _FakeModel:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def transcribe(self, audio, **kwargs):
        return [_FakeSegment("olá mundo", 0.1, 1.0)], None


def test_run_emits_segment_for_the_first_window(qtbot, monkeypatch):
    monkeypatch.setattr(live, "WhisperModel", _FakeModel)
    stdout = io.BytesIO(b"\x00" * live.WINDOW_BYTES)
    transcriber = live.LiveTranscriber(stdout)
    with qtbot.waitSignal(transcriber.segment, timeout=3000) as blocker:
        transcriber.start()
    seg = blocker.args[0]
    assert seg.text == "olá mundo"
    assert seg.start_s == pytest.approx(0.1)
    assert seg.end_s == pytest.approx(1.0)
    assert seg.is_final is True
    transcriber.wait(2000)


def test_stop_before_start_makes_run_return_immediately(qtbot, monkeypatch):
    monkeypatch.setattr(live, "WhisperModel", _FakeModel)
    transcriber = live.LiveTranscriber(io.BytesIO(b"\x00" * live.WINDOW_BYTES))
    transcriber.stop()
    transcriber.start()
    assert transcriber.wait(2000)
