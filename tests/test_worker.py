"""Testes do WhisperThread.

Em vez de mockar ``subprocess``, a maior parte dos casos roda um Whisper falso —
um script Python que reproduz os comportamentos reais observados no binário:
barra de progresso em stderr com ``\\r``, saída nomeada a partir do arquivo de
entrada e o código de retorno 0 mesmo quando nada é transcrito.
"""

import os
import sys
import textwrap
from pathlib import Path

import pytest

from alex_transcritor.worker import WhisperThread


# ── Whisper falso ─────────────────────────────────────────────────────────────

FAKE_WHISPER = textwrap.dedent(
    """
    import os, sys, time
    args = sys.argv[1:]
    source = args[0]
    outdir = args[args.index("--output_dir") + 1]
    device = args[args.index("--device") + 1]
    mode = os.environ.get("FAKE_MODE", "ok")

    if mode == "gpu_fails" and device == "cuda":
        # Reproduz o Whisper real: engole a exceção, avisa e sai com 0.
        sys.stderr.write("Skipping arquivo due to torch.OutOfMemoryError\\n")
        sys.exit(0)
    if mode == "silent_failure":
        sys.stderr.write("Skipping arquivo due to ValueError: logits NaN\\n")
        sys.exit(0)
    if mode == "crash":
        sys.stderr.write("erro fatal do whisper\\n")
        sys.exit(2)
    if mode == "hang":
        time.sleep(120)

    for pct in (0, 50, 100):
        sys.stderr.write(f"\\r {pct}%|#####| {pct}/100 [00:00<00:00, 9.9frames/s]")
        sys.stderr.flush()
        time.sleep(0.02)
    with open(os.path.join(outdir, os.path.basename(source).rsplit(".", 1)[0] + ".txt"),
              "w", encoding="utf-8") as f:
        f.write(f"transcricao em {device}\\n")
    """
)


@pytest.fixture
def fake_whisper(tmp_path):
    script = tmp_path / "fake_whisper.py"
    script.write_text(FAKE_WHISPER, encoding="utf-8")
    launcher = tmp_path / "whisper"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    return str(launcher)


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "gravacao.flac"
    path.write_bytes(b"audio-falso")
    return str(path)


@pytest.fixture(autouse=True)
def no_external_probes(mocker):
    """Neutraliza ffprobe/ffmpeg: os testes não dependem de áudio real."""
    mocker.patch("alex_transcritor.audio.probe_duration", return_value=10.0)
    mocker.patch("alex_transcritor.audio.needed_gain_db", return_value=0.0)


def _run(thread: WhisperThread) -> dict:
    """Executa a thread de verdade e coleta os sinais emitidos."""
    events: dict = {"succeeded": [], "failed": [], "progress": []}
    thread.succeeded.connect(events["succeeded"].append)
    thread.failed.connect(events["failed"].append)
    thread.progress.connect(lambda p, label: events["progress"].append((p, label)))
    thread.run()  # síncrono: mantém a cobertura e torna o teste determinístico
    return events


def _thread(fake_whisper, audio_file, tmp_path, **kwargs) -> WhisperThread:
    kwargs.setdefault("txt_path", str(tmp_path / "saida" / "gravacao.txt"))
    kwargs.setdefault("device", "cpu")
    kwargs.setdefault("enhance", False)
    return WhisperThread(audio_path=audio_file, whisper_bin=fake_whisper, **kwargs)


# ── Caminho feliz ─────────────────────────────────────────────────────────────

def test_success_writes_to_requested_path(fake_whisper, audio_file, tmp_path):
    thread = _thread(fake_whisper, audio_file, tmp_path)
    events = _run(thread)
    assert events["failed"] == []
    assert events["succeeded"] == [str(tmp_path / "saida" / "gravacao.txt")]
    assert (tmp_path / "saida" / "gravacao.txt").read_text(encoding="utf-8").startswith("transcricao")


def test_success_reports_progress(fake_whisper, audio_file, tmp_path):
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert 100 in [percent for percent, _ in events["progress"]]


def test_output_name_follows_recording_not_temp_file(fake_whisper, audio_file, tmp_path, mocker):
    """Com o áudio normalizado num temporário, o .txt ainda leva o nome da gravação."""
    mocker.patch("alex_transcritor.audio.needed_gain_db", return_value=12.0)
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        side_effect=lambda cmd, **kw: _write_stub(cmd),
    )
    thread = _thread(fake_whisper, audio_file, tmp_path, enhance=True)
    events = _run(thread)
    assert events["succeeded"] == [str(tmp_path / "saida" / "gravacao.txt")]


def _write_stub(cmd):
    from unittest.mock import MagicMock
    Path(cmd[-1]).write_bytes(b"audio-normalizado")
    return MagicMock(returncode=0, stdout="", stderr="")


def test_replacements_are_applied(fake_whisper, audio_file, tmp_path):
    thread = _thread(
        fake_whisper, audio_file, tmp_path, replacements=[("transcricao", "TRANSCRIÇÃO")]
    )
    _run(thread)
    assert "TRANSCRIÇÃO" in (tmp_path / "saida" / "gravacao.txt").read_text(encoding="utf-8")


def test_replacements_ignore_case(fake_whisper, audio_file, tmp_path):
    thread = _thread(fake_whisper, audio_file, tmp_path, replacements=[("TRANSCRICAO", "X")])
    _run(thread)
    assert "X em cpu" in (tmp_path / "saida" / "gravacao.txt").read_text(encoding="utf-8")


def test_replacement_value_is_literal_not_regex(fake_whisper, audio_file, tmp_path):
    """Uma correção com \\1 ou & não pode ser interpretada como referência de grupo."""
    thread = _thread(fake_whisper, audio_file, tmp_path, replacements=[("transcricao", r"\1 & C++")])
    _run(thread)
    assert r"\1 & C++" in (tmp_path / "saida" / "gravacao.txt").read_text(encoding="utf-8")


# ── Falhas ────────────────────────────────────────────────────────────────────

def test_missing_audio_file_fails_clearly(fake_whisper, tmp_path):
    thread = _thread(fake_whisper, str(tmp_path / "nao_existe.flac"), tmp_path)
    events = _run(thread)
    assert events["succeeded"] == []
    assert "não encontrado" in events["failed"][0]


def test_empty_recording_is_reported(fake_whisper, audio_file, tmp_path, mocker):
    mocker.patch("alex_transcritor.audio.probe_duration", return_value=0.1)
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert "vazia" in events["failed"][0]


def test_zero_exit_without_output_is_a_failure(fake_whisper, audio_file, tmp_path, monkeypatch):
    """O Whisper real sai com 0 depois de 'Skipping ... due to ...' e nada gera."""
    monkeypatch.setenv("FAKE_MODE", "silent_failure")
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert events["succeeded"] == []
    assert "Skipping" in events["failed"][0]


def test_nonzero_exit_is_reported(fake_whisper, audio_file, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert events["succeeded"] == []
    assert "erro fatal" in events["failed"][0]


def test_missing_binary_is_reported(audio_file, tmp_path):
    thread = _thread("/caminho/inexistente/whisper", audio_file, tmp_path)
    events = _run(thread)
    assert "não encontrado" in events["failed"][0]


def test_timeout_kills_process(fake_whisper, audio_file, tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("FAKE_MODE", "hang")
    mocker.patch("alex_transcritor.worker.MIN_TIMEOUT_S", 1)
    mocker.patch("alex_transcritor.audio.probe_duration", return_value=0.0)
    thread = _thread(fake_whisper, audio_file, tmp_path)
    events = _run(thread)
    assert "Tempo limite" in events["failed"][0]
    assert thread._process.poll() is not None


def test_unexpected_exception_becomes_failed_signal(fake_whisper, audio_file, tmp_path, mocker):
    mocker.patch(
        "alex_transcritor.audio.probe_duration", side_effect=RuntimeError("boom")
    )
    thread = _thread(fake_whisper, audio_file, tmp_path)
    events = _run(thread)
    assert "boom" in events["failed"][0]


# ── Fallback de GPU para CPU ──────────────────────────────────────────────────

def test_gpu_failure_falls_back_to_cpu(fake_whisper, audio_file, tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("FAKE_MODE", "gpu_fails")
    mocker.patch("alex_transcritor.worker.pick_device", return_value="cuda")
    thread = _thread(fake_whisper, audio_file, tmp_path, device="cuda")
    events = _run(thread)
    assert events["failed"] == []
    assert (tmp_path / "saida" / "gravacao.txt").read_text(encoding="utf-8").strip().endswith("cpu")
    assert any("CPU" in label for _, label in events["progress"])


def test_cpu_failure_does_not_retry(fake_whisper, audio_file, tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("FAKE_MODE", "crash")
    mocker.patch("alex_transcritor.worker.pick_device", return_value="cpu")
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert len(events["failed"]) == 1


# ── Cancelamento ──────────────────────────────────────────────────────────────

def test_cancel_kills_child_and_stays_silent(fake_whisper, audio_file, tmp_path, monkeypatch, qtbot):
    """QThread.terminate() deixaria o Whisper órfão segurando GPU e RAM."""
    monkeypatch.setenv("FAKE_MODE", "hang")
    thread = _thread(fake_whisper, audio_file, tmp_path)
    events: dict = {"succeeded": [], "failed": []}
    thread.succeeded.connect(events["succeeded"].append)
    thread.failed.connect(events["failed"].append)

    thread.start()
    qtbot.waitUntil(lambda: thread._process is not None and thread._process.poll() is None,
                    timeout=5000)
    child_pid = thread._process.pid
    thread.cancel()
    assert thread.wait(10000)

    assert events["succeeded"] == [] and events["failed"] == []
    with pytest.raises(OSError):
        os.kill(child_pid, 0)  # processo filho não sobreviveu ao cancelamento


def test_cancel_before_start_is_harmless(fake_whisper, audio_file, tmp_path):
    thread = _thread(fake_whisper, audio_file, tmp_path)
    thread.cancel()  # não deve levantar exceção


# ── Montagem do comando ───────────────────────────────────────────────────────

def test_command_disables_hallucination_prone_options(fake_whisper, audio_file, tmp_path, mocker):
    captured: list[list[str]] = []
    mocker.patch.object(
        WhisperThread, "_stream_process",
        lambda self, cmd, timeout, device: captured.append(cmd) or "",
    )
    _run(_thread(fake_whisper, audio_file, tmp_path, initial_prompt="PipeWire, Pedroza"))
    cmd = captured[0]
    assert cmd[cmd.index("--condition_on_previous_text") + 1] == "False"
    assert cmd[cmd.index("--fp16") + 1] == "False"
    assert cmd[cmd.index("--temperature") + 1] == "0"
    assert cmd[cmd.index("--initial_prompt") + 1] == "PipeWire, Pedroza"
    assert cmd[cmd.index("--language") + 1] == "pt"


def test_auto_language_is_not_forced(fake_whisper, audio_file, tmp_path, mocker):
    captured: list[list[str]] = []
    mocker.patch.object(
        WhisperThread, "_stream_process",
        lambda self, cmd, timeout, device: captured.append(cmd) or "",
    )
    _run(_thread(fake_whisper, audio_file, tmp_path, language="auto"))
    assert "--language" not in captured[0]


def test_empty_prompt_is_omitted(fake_whisper, audio_file, tmp_path, mocker):
    captured: list[list[str]] = []
    mocker.patch.object(
        WhisperThread, "_stream_process",
        lambda self, cmd, timeout, device: captured.append(cmd) or "",
    )
    _run(_thread(fake_whisper, audio_file, tmp_path, initial_prompt=""))
    assert "--initial_prompt" not in captured[0]


def test_timeout_scales_with_audio_duration(fake_whisper, audio_file, tmp_path, mocker):
    """Uma hora de áudio em CPU passa de uma hora de processamento."""
    mocker.patch("alex_transcritor.audio.probe_duration", return_value=3600.0)
    captured: list[float] = []
    mocker.patch.object(
        WhisperThread, "_stream_process",
        lambda self, cmd, timeout, device: captured.append(timeout) or "",
    )
    _run(_thread(fake_whisper, audio_file, tmp_path))
    assert captured[0] > 3600


# ── Normalização de áudio ─────────────────────────────────────────────────────

def test_enhance_skipped_when_audio_already_loud(fake_whisper, audio_file, tmp_path, mocker):
    """Amplificar áudio já adequado piora a transcrição — medido em WER."""
    mocker.patch("alex_transcritor.audio.needed_gain_db", return_value=0.0)
    run = mocker.patch("alex_transcritor.worker.subprocess.run")
    events = _run(_thread(fake_whisper, audio_file, tmp_path, enhance=True))
    assert events["failed"] == []
    run.assert_not_called()


def test_transcription_proceeds_when_normalization_fails(fake_whisper, audio_file, tmp_path, mocker):
    mocker.patch("alex_transcritor.audio.needed_gain_db", return_value=12.0)
    mocker.patch("alex_transcritor.worker.subprocess.run", side_effect=FileNotFoundError)
    events = _run(_thread(fake_whisper, audio_file, tmp_path, enhance=True))
    assert events["succeeded"] and events["failed"] == []


def test_transcription_proceeds_when_normalization_returns_error(
    fake_whisper, audio_file, tmp_path, mocker
):
    from unittest.mock import MagicMock
    mocker.patch("alex_transcritor.audio.needed_gain_db", return_value=12.0)
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="", stderr="falhou"),
    )
    events = _run(_thread(fake_whisper, audio_file, tmp_path, enhance=True))
    assert events["succeeded"] and events["failed"] == []


# ── Falhas ao iniciar o processo ──────────────────────────────────────────────

def test_oserror_starting_whisper_is_reported(fake_whisper, audio_file, tmp_path, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.Popen", side_effect=OSError("sem descritores")
    )
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert "sem descritores" in events["failed"][0]


def test_publish_failure_is_reported(fake_whisper, audio_file, tmp_path, mocker):
    mocker.patch.object(
        WhisperThread, "_publish", side_effect=OSError("permissão negada")
    )
    events = _run(_thread(fake_whisper, audio_file, tmp_path))
    assert "permissão negada" in events["failed"][0]


def test_kill_escalates_when_terminate_is_ignored(fake_whisper, audio_file, tmp_path, mocker):
    import subprocess as sp
    from unittest.mock import MagicMock
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [sp.TimeoutExpired(cmd="whisper", timeout=5), 0]
    thread = _thread(fake_whisper, audio_file, tmp_path)
    thread._process = process
    thread._kill_process()
    process.kill.assert_called_once()


def test_kill_tolerates_process_already_gone(fake_whisper, audio_file, tmp_path):
    from unittest.mock import MagicMock
    process = MagicMock()
    process.poll.return_value = None
    process.terminate.side_effect = OSError("processo já morreu")
    thread = _thread(fake_whisper, audio_file, tmp_path)
    thread._process = process
    thread._kill_process()  # não deve levantar exceção


def test_cancel_mid_stream_produces_no_signal(fake_whisper, audio_file, tmp_path, mocker):
    """Cancelar durante a leitura do stderr não pode emitir sucesso nem erro."""
    thread = _thread(fake_whisper, audio_file, tmp_path)
    original = thread._emit_progress

    def cancel_then_emit(buffer, label):
        thread._cancelled = True
        original(buffer, label)

    mocker.patch.object(thread, "_emit_progress", cancel_then_emit)
    events = _run(thread)
    assert events["succeeded"] == [] and events["failed"] == []
