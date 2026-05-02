import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import alex_transcritor.config as cfg


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redireciona CONFIG_DIR e CONFIG_FILE para tmp_path em todos os testes."""
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "transcricoes"))


# ── load_config ───────────────────────────────────────────────────────────────

def test_load_config_file_absent(tmp_path):
    assert cfg.load_config() == {}


def test_load_config_valid(tmp_path):
    (tmp_path / "config.json").write_text('{"monitor": "test_monitor"}')
    assert cfg.load_config() == {"monitor": "test_monitor"}


def test_load_config_corrupted(tmp_path):
    (tmp_path / "config.json").write_text("{invalid json}")
    assert cfg.load_config() == {}


def test_load_config_non_dict(tmp_path):
    (tmp_path / "config.json").write_text("[1, 2, 3]")
    assert cfg.load_config() == {}


# ── save_config ───────────────────────────────────────────────────────────────

def test_save_config_creates_file(tmp_path):
    cfg.save_config({"monitor": "my_monitor"})
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved == {"monitor": "my_monitor"}


def test_save_config_creates_dir(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b"
    monkeypatch.setattr(cfg, "CONFIG_DIR", nested)
    monkeypatch.setattr(cfg, "CONFIG_FILE", nested / "config.json")
    cfg.save_config({"key": "value"})
    assert (nested / "config.json").exists()


def test_save_config_overwrites(tmp_path):
    cfg.save_config({"a": 1})
    cfg.save_config({"b": 2})
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved == {"b": 2}


# ── list_monitor_sources ──────────────────────────────────────────────────────

PACTL_OUTPUT = (
    "0\talsa_input.usb-mic-00.analog\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
    "1\talsa_output.usb-headset-00.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
    "2\talsa_output.usb-speaker-01.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
)


def test_list_monitor_sources_returns_monitors(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        return_value=MagicMock(stdout=PACTL_OUTPUT),
    )
    sources = cfg.list_monitor_sources()
    assert len(sources) == 2
    assert all("monitor" in s.lower() for s in sources)


def test_list_monitor_sources_empty_output(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        return_value=MagicMock(stdout=""),
    )
    assert cfg.list_monitor_sources() == []


def test_list_monitor_sources_no_monitors(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        return_value=MagicMock(stdout="0\talsa_input.usb-mic\tPipeWire\n"),
    )
    assert cfg.list_monitor_sources() == []


def test_list_monitor_sources_pactl_not_found(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        side_effect=FileNotFoundError,
    )
    assert cfg.list_monitor_sources() == []


def test_list_monitor_sources_timeout(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pactl", timeout=5),
    )
    assert cfg.list_monitor_sources() == []


# ── get_monitor ───────────────────────────────────────────────────────────────

def test_get_monitor_from_config(tmp_path, mocker):
    (tmp_path / "config.json").write_text('{"monitor": "saved_monitor"}')
    mock_pactl = mocker.patch("alex_transcritor.config.subprocess.run")
    result = cfg.get_monitor()
    assert result == "saved_monitor"
    mock_pactl.assert_not_called()


def test_get_monitor_auto_detect_saves(tmp_path, mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        return_value=MagicMock(stdout="1\tauto_monitor\tPipeWire\n"),
    )
    result = cfg.get_monitor()
    assert result == "auto_monitor"
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["monitor"] == "auto_monitor"


def test_get_monitor_none_available(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        side_effect=FileNotFoundError,
    )
    assert cfg.get_monitor() == ""


# ── get_last_output_dir / save_last_output_dir ────────────────────────────────

def test_get_last_output_dir_default(tmp_path):
    result = cfg.get_last_output_dir()
    assert result == str(tmp_path / "transcricoes")


def test_get_last_output_dir_from_config(tmp_path):
    (tmp_path / "config.json").write_text('{"last_dir": "/custom/path"}')
    assert cfg.get_last_output_dir() == "/custom/path"


def test_save_last_output_dir(tmp_path):
    cfg.save_last_output_dir("/my/path")
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["last_dir"] == "/my/path"


def test_save_last_output_dir_preserves_other_keys(tmp_path):
    (tmp_path / "config.json").write_text('{"monitor": "mon"}')
    cfg.save_last_output_dir("/dir")
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["monitor"] == "mon"
    assert saved["last_dir"] == "/dir"
