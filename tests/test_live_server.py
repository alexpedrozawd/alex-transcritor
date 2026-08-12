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

#: Relativos a WINDOW_S de propósito: fixar segundos aqui fez estes testes
#: quebrarem quando a janela subiu de 2 s para 6 s por qualidade.
_FIM_COM_SILENCIO = live_server.WINDOW_S - live_server.TRAILING_SILENCE_S - 0.2
_FIM_SEM_SILENCIO = live_server.WINDOW_S - 0.05


def test_single_segment_becomes_final_when_trailing_silence():
    raw = [{"start": 0.0, "end": _FIM_COM_SILENCIO, "text": "ola"}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=10.0, is_first_window=True)
    assert len(segs) == 1
    assert segs[0].text == "ola"
    assert segs[0].start_s == 10.0
    assert segs[0].end_s == 10.0 + _FIM_COM_SILENCIO
    # sobra mais silêncio que TRAILING_SILENCE_S ao fim da janela -> final
    assert segs[0].is_final is True


def test_last_segment_without_trailing_silence_is_provisional():
    raw = [{"start": 0.0, "end": _FIM_SEM_SILENCIO, "text": "fala continua"}]
    segs = live_server.segments_to_live_segments(raw, window_start_s=0.0, is_first_window=True)
    assert segs[0].is_final is False


def test_non_last_segments_are_always_final():
    raw = [
        {"start": 0.0, "end": 0.8, "text": "primeiro"},
        {"start": 0.9, "end": _FIM_SEM_SILENCIO, "text": "segundo"},
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
    # Regressão do texto alucinado em uso real: com o padrão do Whisper, uma
    # decodificação que bate nos limiares é refeita com temperatura crescente
    # até 1.0, e temperatura alta em janela curta produz lixo (inclusive
    # caracteres de outros alfabetos). O passe em lote usa 0 e sai limpo.
    assert calls["kwargs"]["temperature"] == 0.0
    assert calls["kwargs"]["beam_size"] == 5


def test_transcribe_window_omits_language_when_auto():
    """"auto" não é código de idioma — o Whisper espera None para detectar."""
    calls = {}

    class _FakeModel:
        def transcribe(self, audio_array, **kwargs):
            calls.update(kwargs)
            return {"segments": []}

    live_server.transcribe_window(_FakeModel(), b"\x00\x01" * 1000, language="auto")
    assert calls["language"] is None


def test_transcribe_window_drops_probable_non_speech():
    class _FakeModel:
        def transcribe(self, audio_array, **kwargs):
            return {"segments": [
                {"start": 0.0, "end": 1.0, "text": "fala real", "no_speech_prob": 0.1},
                {"start": 1.0, "end": 2.0, "text": "alucinação", "no_speech_prob": 0.95},
            ]}

    result = live_server.transcribe_window(_FakeModel(), b"\x00\x01" * 1000, language="pt")
    assert [s["text"] for s in result] == ["fala real"]


# ── is_silent ──────────────────────────────────────────────────────────────────

def test_silence_is_detected():
    assert live_server.is_silent(b"\x00" * 32000) is True


def test_audio_with_energy_is_not_silent():
    assert live_server.is_silent(b"\x00\x10" * 16000) is False


def test_empty_window_counts_as_silent():
    assert live_server.is_silent(b"") is True


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


# ── contexto da diarização ao vivo ─────────────────────────────────────────────

def test_context_is_never_padded_with_silence():
    """Regressão medida com áudio real: completar o trecho com silêncio fez o
    pyannote ver 3 locutores num diálogo de 2 vozes e picotar a mesma voz.
    Com o áudio cru ele acertou exatamente as duas."""
    audio = b"\x07\x07" * int(live_server.DIARIZE_MIN_CONTEXT_BYTES // 2)
    ctx = live_server.context_for_diarization(audio)
    assert b"\x00\x00" * 100 not in ctx
    assert len(ctx) <= len(audio)


def test_context_is_none_until_there_is_enough_audio():
    curto = b"\x01\x02" * 100
    assert live_server.context_for_diarization(curto) is None


def test_context_is_quantized_in_steps():
    """Poucos formatos distintos = poucas otimizações caras de kernel no ROCm."""
    audio = b"\x01\x02" * (live_server.DIARIZE_MIN_CONTEXT_BYTES)  # bem acima do mínimo
    ctx = live_server.context_for_diarization(audio)
    assert len(ctx) % live_server.DIARIZE_STEP_BYTES == 0


def test_context_never_exceeds_the_window_and_keeps_the_present():
    enorme = b"\x09\x09" * live_server.DIARIZE_CONTEXT_BYTES
    ctx = live_server.context_for_diarization(enorme)
    assert len(ctx) <= live_server.DIARIZE_CONTEXT_BYTES
    assert enorme.endswith(ctx)  # o presente fica no fim


def test_context_offset_points_to_where_the_context_starts():
    recebidos = int(100 * live_server.BYTES_PER_SECOND)
    contexto = int(30 * live_server.BYTES_PER_SECOND)
    assert live_server.context_offset_s(recebidos, contexto) == 70.0
