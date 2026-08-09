import subprocess
from unittest.mock import MagicMock

import pytest

from alex_transcritor import audio


# ── unique_path ───────────────────────────────────────────────────────────────

def test_unique_path_uses_plain_name_when_free(tmp_path):
    assert audio.unique_path(str(tmp_path), "aula", ".flac") == tmp_path / "aula.flac"


def test_unique_path_avoids_overwriting_existing(tmp_path):
    (tmp_path / "aula.flac").write_bytes(b"")
    assert audio.unique_path(str(tmp_path), "aula", ".flac") == tmp_path / "aula-2.flac"


def test_unique_path_increments_until_free(tmp_path):
    for name in ("aula.flac", "aula-2.flac", "aula-3.flac"):
        (tmp_path / name).write_bytes(b"")
    assert audio.unique_path(str(tmp_path), "aula", ".flac") == tmp_path / "aula-4.flac"


# ── record_command ────────────────────────────────────────────────────────────

def test_record_command_system_only():
    cmd = audio.record_command("/out/a.flac", monitor="mon")
    assert cmd[:4] == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    assert cmd.count("-i") == 1
    assert "mon" in cmd
    assert "-filter_complex" not in cmd
    assert cmd[-1] == "/out/a.flac"


def test_record_command_mic_only():
    cmd = audio.record_command("/out/a.flac", mic="mic")
    assert "mic" in cmd
    assert cmd.count("-i") == 1


def test_record_command_mixes_both_sources():
    cmd = audio.record_command("/out/a.flac", monitor="mon", mic="mic")
    assert cmd.count("-i") == 2
    assert "amix=inputs=2:duration=longest:normalize=0,aresample=async=1" in cmd


def test_record_command_forces_mono_16khz():
    cmd = audio.record_command("/out/a.flac", monitor="mon")
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "16000"


@pytest.mark.parametrize(
    "fmt,codec", [("flac", "flac"), ("wav", "pcm_s16le"), ("mp3", "libmp3lame")]
)
def test_record_command_codec_per_format(fmt, codec):
    cmd = audio.record_command(f"/out/a.{fmt}", monitor="mon", audio_format=fmt)
    assert cmd[cmd.index("-c:a") + 1] == codec


def test_record_command_unknown_format_falls_back_to_flac():
    cmd = audio.record_command("/out/a.xyz", monitor="mon", audio_format="xyz")
    assert cmd[cmd.index("-c:a") + 1] == "flac"


def test_record_command_without_sources_raises():
    with pytest.raises(ValueError):
        audio.record_command("/out/a.flac")


def test_record_command_never_uses_shell_metacharacters_as_string():
    """Nome de dispositivo hostil vira um argumento isolado, não parte de um shell."""
    cmd = audio.record_command("/out/a.flac", monitor="; rm -rf ~")
    assert "; rm -rf ~" in cmd  # argumento único, preservado literalmente


# ── Medição de nível ──────────────────────────────────────────────────────────

def _volumedetect(stderr: str) -> MagicMock:
    return MagicMock(returncode=0, stdout="", stderr=stderr)


def test_peak_db_parses_output(mocker):
    mocker.patch(
        "alex_transcritor.audio.subprocess.run",
        return_value=_volumedetect("mean_volume: -43.0 dB\nmax_volume: -24.1 dB\n"),
    )
    assert audio.peak_db("/a.flac") == -24.1


def test_peak_db_none_when_unparseable(mocker):
    mocker.patch("alex_transcritor.audio.subprocess.run", return_value=_volumedetect("nada"))
    assert audio.peak_db("/a.flac") is None


def test_peak_db_none_when_ffmpeg_missing(mocker):
    mocker.patch("alex_transcritor.audio.subprocess.run", side_effect=FileNotFoundError)
    assert audio.peak_db("/a.flac") is None


def test_needed_gain_for_quiet_audio(mocker):
    mocker.patch("alex_transcritor.audio.peak_db", return_value=-24.1)
    assert audio.needed_gain_db("/a.flac") == pytest.approx(21.1)


def test_no_gain_for_audio_already_loud(mocker):
    """Aplicar ganho em áudio adequado piora a transcrição — medido em WER."""
    mocker.patch("alex_transcritor.audio.peak_db", return_value=-2.0)
    assert audio.needed_gain_db("/a.flac") == 0.0


def test_no_gain_below_minimum_threshold(mocker):
    mocker.patch("alex_transcritor.audio.peak_db", return_value=-5.0)
    assert audio.needed_gain_db("/a.flac") == 0.0


def test_no_gain_when_measurement_fails(mocker):
    mocker.patch("alex_transcritor.audio.peak_db", return_value=None)
    assert audio.needed_gain_db("/a.flac") == 0.0


def test_gain_command_applies_pure_volume():
    cmd = audio.gain_command("/in.flac", "/out.flac", 12.5)
    assert cmd[cmd.index("-af") + 1] == "volume=12.5dB"
    assert cmd[cmd.index("-c:a") + 1] == "flac"


# ── probe_duration ────────────────────────────────────────────────────────────

def test_probe_duration_parses_seconds(mocker):
    mocker.patch(
        "alex_transcritor.audio.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="39.52\n", stderr=""),
    )
    assert audio.probe_duration("/a.flac") == pytest.approx(39.52)


def test_probe_duration_zero_when_not_a_number(mocker):
    mocker.patch(
        "alex_transcritor.audio.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="N/A", stderr=""),
    )
    assert audio.probe_duration("/a.flac") == 0.0


def test_probe_duration_zero_on_timeout(mocker):
    mocker.patch(
        "alex_transcritor.audio.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=60),
    )
    assert audio.probe_duration("/a.flac") == 0.0
