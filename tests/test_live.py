"""Testes do LiveTranscriber e das funções puras de janelamento."""

import io
import os
import threading
import time

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


# ── Regressão: leitura do pipe não pode esperar a transcrição ─────────────────

class _SlowFakeModel:
    """Simula um modelo lento o bastante para nunca acompanhar tempo real."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def transcribe(self, audio, **kwargs):
        time.sleep(0.5)
        return [], None


def test_pipe_is_drained_without_waiting_for_slow_transcription(qtbot, monkeypatch):
    """Reproduz o bug relatado em uso real: se a leitura do pipe esperasse a
    transcrição terminar, o ffmpeg do outro lado travaria no write() assim
    que o buffer do pipe do SO enchesse (~64 KB) — travando a GRAVAÇÃO
    inteira, não só o painel ao vivo, porque é o mesmo processo ffmpeg
    escrevendo o arquivo principal e o pipe ao mesmo tempo.
    """
    monkeypatch.setattr(live, "WhisperModel", _SlowFakeModel)

    read_fd, write_fd = os.pipe()
    stdout = os.fdopen(read_fd, "rb")

    # Bem mais que o buffer padrão de um pipe (64 KB no Linux) e mais do que
    # dá para transcrever a 0,5s por janela dentro do prazo do teste.
    payload = b"\x00" * (live.WINDOW_BYTES * 4)
    write_done = threading.Event()

    def _write_like_ffmpeg():
        with os.fdopen(write_fd, "wb") as w:
            w.write(payload)
        write_done.set()

    writer = threading.Thread(target=_write_like_ffmpeg, daemon=True)

    transcriber = live.LiveTranscriber(stdout)
    transcriber.start()
    writer.start()

    # Com a leitura desacoplada, a escrita termina quase de imediato — ela só
    # depende do leitor drenar o pipe, nunca da transcrição. Com o bug antigo
    # (leitura e transcrição na mesma thread/loop), a escrita ficaria presa
    # esperando ciclos de "ler + dormir 0,5s", levando vários segundos.
    assert write_done.wait(timeout=1.5), (
        "escrita no pipe travou — leitura ficou acoplada à velocidade da transcrição"
    )

    transcriber.stop()
    assert transcriber.wait(5000)
    writer.join(timeout=2)


# ── Fallback de device: GPU indisponível cai para CPU ─────────────────────────

def test_gpu_load_failure_falls_back_to_cpu(qtbot, monkeypatch):
    """Reproduz o caso real: bibliotecas CUDA ausentes no venv do cliente
    (libcublas.so.12 etc.) não podem deixar a transcrição ao vivo morta —
    tenta CPU antes de desistir."""
    attempts = []

    class _FallbackModel:
        def __init__(self, model_size, device, compute_type):
            attempts.append(device)
            if device != "cpu":
                raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")

        def transcribe(self, audio, **kwargs):
            return [_FakeSegment("funcionou na cpu", 0.1, 1.0)], None

    monkeypatch.setattr(live, "WhisperModel", _FallbackModel)
    stdout = io.BytesIO(b"\x00" * live.WINDOW_BYTES)
    transcriber = live.LiveTranscriber(stdout, device="cuda")
    with qtbot.waitSignal(transcriber.segment, timeout=3000) as blocker:
        transcriber.start()
    assert attempts == ["cuda", "cpu"]
    assert blocker.args[0].text == "funcionou na cpu"
    transcriber.wait(2000)


def test_gpu_and_cpu_load_failure_emits_failed_once(qtbot, monkeypatch):
    class _AlwaysFailsModel:
        def __init__(self, model_size, device, compute_type):
            raise RuntimeError(f"sem suporte a {device}")

    monkeypatch.setattr(live, "WhisperModel", _AlwaysFailsModel)
    transcriber = live.LiveTranscriber(io.BytesIO(b""), device="cuda")
    with qtbot.waitSignal(transcriber.failed, timeout=2000) as blocker:
        transcriber.start()
    assert "cpu" in blocker.args[0]
    transcriber.wait(2000)


def test_cpu_load_failure_does_not_retry(qtbot, monkeypatch):
    """Já pedindo CPU, uma falha não tenta de novo — só faz sentido reter
    quando a primeira tentativa era GPU."""
    attempts = []

    class _FailsOnce:
        def __init__(self, model_size, device, compute_type):
            attempts.append(device)
            raise RuntimeError("sem suporte")

    monkeypatch.setattr(live, "WhisperModel", _FailsOnce)
    transcriber = live.LiveTranscriber(io.BytesIO(b""), device="cpu")
    with qtbot.waitSignal(transcriber.failed, timeout=2000):
        transcriber.start()
    assert attempts == ["cpu"]
    transcriber.wait(2000)


def test_falls_back_to_skipping_when_backlog_grows_too_large(qtbot, monkeypatch):
    """Regressão: sem limite de acúmulo, uma transcrição lenta nunca alcança o
    tempo real — a cada janela processada, mais áudio novo já se acumulou, e
    ao clicar Parar o app fica minutos tentando esvaziar um atraso que já não
    serve pra nada. Com 20 janelas de acúmulo a 0,5s cada, processar tudo sem
    descartar levaria 10s+; com o limite, tem que sair bem mais rápido.
    """
    monkeypatch.setattr(live, "WhisperModel", _SlowFakeModel)
    huge_payload = b"\x00" * (live.WINDOW_BYTES * 20)
    transcriber = live.LiveTranscriber(io.BytesIO(huge_payload))
    transcriber.start()
    qtbot.wait(300)  # deixa o acúmulo se formar e o consumo começar
    transcriber.stop()
    assert transcriber.wait(3000), (
        "não saiu a tempo — parece estar processando o acúmulo inteiro em vez de descartá-lo"
    )


def test_backlog_limit_fits_a_full_window():
    """Regressão: com o teto fixo em 50, encher uma janela de 6s (47 blocos)
    deixava 3 de folga e o menor atraso já descartava áudio bom."""
    blocos_por_janela = live.WINDOW_BYTES // live.READ_CHUNK_BYTES
    assert live.MAX_QUEUED_CHUNKS >= 2 * blocos_por_janela, (
        f"teto {live.MAX_QUEUED_CHUNKS} não comporta nem 2 janelas de {blocos_por_janela} blocos"
    )
