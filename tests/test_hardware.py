import subprocess
from unittest.mock import MagicMock

import pytest

from alex_transcritor import hardware


def _nvidia_smi(mocker, stdout="4096\n", returncode=0):
    return mocker.patch(
        "alex_transcritor.hardware.subprocess.run",
        return_value=MagicMock(returncode=returncode, stdout=stdout, stderr=""),
    )


# ── gpu_vram_gb ───────────────────────────────────────────────────────────────

def test_gpu_vram_converts_mib_to_gb(mocker):
    _nvidia_smi(mocker, "4096\n")
    assert hardware.gpu_vram_gb() == pytest.approx(4.0)


def test_gpu_vram_uses_first_gpu(mocker):
    _nvidia_smi(mocker, "8192\n24576\n")
    assert hardware.gpu_vram_gb() == pytest.approx(8.0)


def test_gpu_vram_zero_without_nvidia_smi(mocker):
    mocker.patch("alex_transcritor.hardware.subprocess.run", side_effect=FileNotFoundError)
    assert hardware.gpu_vram_gb() == 0.0


def test_gpu_vram_zero_on_command_failure(mocker):
    _nvidia_smi(mocker, "", returncode=9)
    assert hardware.gpu_vram_gb() == 0.0


def test_gpu_vram_zero_on_unexpected_output(mocker):
    _nvidia_smi(mocker, "sem GPU aqui\n")
    assert hardware.gpu_vram_gb() == 0.0


def test_gpu_vram_zero_on_timeout(mocker):
    mocker.patch(
        "alex_transcritor.hardware.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10),
    )
    assert hardware.gpu_vram_gb() == 0.0


# ── pick_device ───────────────────────────────────────────────────────────────

def test_pick_device_honours_explicit_preference(mocker):
    probe = mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=0.0)
    assert hardware.pick_device("turbo", "cuda") == "cuda"
    assert hardware.pick_device("small", "cpu") == "cpu"
    probe.assert_not_called()


def test_pick_device_cpu_without_gpu(mocker):
    mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=0.0)
    assert hardware.pick_device("small") == "cpu"


def test_pick_device_gpu_when_model_fits(mocker):
    mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=4.0)
    assert hardware.pick_device("small") == "cuda"


def test_pick_device_cpu_when_model_does_not_fit(mocker):
    """Verificado numa GTX 1650: turbo e medium abortam com CUDA out of memory."""
    mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=4.0)
    assert hardware.pick_device("turbo") == "cpu"
    assert hardware.pick_device("medium") == "cpu"


def test_pick_device_gpu_for_large_card(mocker):
    mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=24.0)
    assert hardware.pick_device("large-v3") == "cuda"


def test_pick_device_unknown_model_is_conservative(mocker):
    mocker.patch("alex_transcritor.hardware.gpu_vram_gb", return_value=4.0)
    assert hardware.pick_device("modelo-desconhecido") == "cpu"
