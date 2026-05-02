import subprocess
from unittest.mock import MagicMock

import pytest

from alex_transcritor.worker import WhisperThread


@pytest.fixture
def thread():
    return WhisperThread(
        audio_path="/tmp/test.mp3",
        output_dir="/tmp",
        whisper_bin="/fake/venv/bin/whisper",
    )


# run() é chamado diretamente (síncrono) para garantir cobertura,
# pois QThread usa C++ threads que não são rastreados pelo coverage.py.

def test_run_success(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        return_value=MagicMock(returncode=0, stderr=""),
    )
    results = []
    thread.finished.connect(lambda: results.append("done"))
    thread.run()
    assert results == ["done"]


def test_run_error_returncode(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        return_value=MagicMock(returncode=1, stderr="some whisper error"),
    )
    errors = []
    thread.error.connect(errors.append)
    thread.run()
    assert errors and "some whisper error" in errors[0]


def test_run_error_no_stderr(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        return_value=MagicMock(returncode=1, stderr=""),
    )
    errors = []
    thread.error.connect(errors.append)
    thread.run()
    assert errors and errors[0]  # mensagem não vazia


def test_run_file_not_found(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        side_effect=FileNotFoundError,
    )
    errors = []
    thread.error.connect(errors.append)
    thread.run()
    assert errors and "/fake/venv/bin/whisper" in errors[0]


def test_run_timeout_expired(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="whisper", timeout=3600),
    )
    errors = []
    thread.error.connect(errors.append)
    thread.run()
    assert errors and "limite" in errors[0].lower()


def test_run_unexpected_exception(thread, mocker):
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        side_effect=RuntimeError("boom"),
    )
    errors = []
    thread.error.connect(errors.append)
    thread.run()
    assert errors and "boom" in errors[0]


def test_thread_via_start_emits_signal(qtbot, thread, mocker):
    """Verifica o comportamento assíncrono real do QThread."""
    mocker.patch(
        "alex_transcritor.worker.subprocess.run",
        return_value=MagicMock(returncode=0, stderr=""),
    )
    with qtbot.waitSignal(thread.finished, timeout=3000):
        thread.start()
        thread.wait()
