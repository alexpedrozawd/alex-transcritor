import json
import stat
import subprocess
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


def _written(tmp_path) -> dict:
    return json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))


# ── load_config ───────────────────────────────────────────────────────────────

def test_load_config_absent_returns_defaults():
    assert cfg.load_config() == cfg.DEFAULTS


def test_load_config_valid_merges_over_defaults(tmp_path):
    (tmp_path / "config.json").write_text('{"monitor": "test_monitor"}')
    config = cfg.load_config()
    assert config["monitor"] == "test_monitor"
    assert config["model"] == cfg.DEFAULTS["model"]


def test_load_config_corrupted_returns_defaults(tmp_path):
    (tmp_path / "config.json").write_text("{invalid json}")
    assert cfg.load_config() == cfg.DEFAULTS


def test_load_config_non_dict_returns_defaults(tmp_path):
    (tmp_path / "config.json").write_text("[1, 2, 3]")
    assert cfg.load_config() == cfg.DEFAULTS


def test_load_config_ignores_wrong_types(tmp_path):
    (tmp_path / "config.json").write_text(
        '{"monitor": {"a": 1}, "enhance_audio": "sim", "vocabulary": 42}'
    )
    config = cfg.load_config()
    assert config["monitor"] == ""
    assert config["enhance_audio"] is True
    assert config["vocabulary"] == ""


def test_load_config_rejects_unknown_enum_values(tmp_path):
    (tmp_path / "config.json").write_text(
        '{"model": "gpt-9", "device": "tpu", "audio_format": "ogg", "source_mode": "telepatia"}'
    )
    config = cfg.load_config()
    assert config["model"] == cfg.DEFAULTS["model"]
    assert config["device"] == "auto"
    assert config["audio_format"] == "flac"
    assert config["source_mode"] == "system"


def test_load_config_drops_unknown_keys(tmp_path):
    (tmp_path / "config.json").write_text('{"comando_malicioso": "rm -rf /"}')
    assert "comando_malicioso" not in cfg.load_config()


def test_load_config_rejects_unknown_live_enum_values(tmp_path):
    (tmp_path / "config.json").write_text('{"live_model": "gpt-9", "live_device": "tpu"}')
    config = cfg.load_config()
    assert config["live_model"] == cfg.DEFAULTS["live_model"]
    assert config["live_device"] == cfg.DEFAULTS["live_device"]


def test_load_config_live_transcription_defaults_off():
    assert cfg.load_config()["live_transcription"] is False


def test_load_config_diarize_speakers_defaults_off():
    assert cfg.load_config()["diarize_speakers"] is False


def test_load_config_ignores_wrong_type_diarize_speakers(tmp_path):
    (tmp_path / "config.json").write_text('{"diarize_speakers": "sim"}')
    assert cfg.load_config()["diarize_speakers"] is False


# ── save_config ───────────────────────────────────────────────────────────────

def test_save_config_creates_file(tmp_path):
    cfg.save_config({"monitor": "my_monitor"})
    assert _written(tmp_path) == {"monitor": "my_monitor"}


def test_save_config_creates_dir(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b"
    monkeypatch.setattr(cfg, "CONFIG_DIR", nested)
    monkeypatch.setattr(cfg, "CONFIG_FILE", nested / "config.json")
    cfg.save_config({"key": "value"})
    assert (nested / "config.json").exists()


def test_save_config_uses_restrictive_permissions(tmp_path):
    cfg.save_config({"monitor": "m"})
    mode = stat.S_IMODE((tmp_path / "config.json").stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_save_config_leaves_no_temp_files(tmp_path):
    cfg.save_config({"monitor": "m"})
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_save_config_keeps_previous_content_on_failure(tmp_path, monkeypatch):
    cfg.save_config({"monitor": "original"})
    monkeypatch.setattr(cfg.json, "dump", MagicMock(side_effect=OSError("disco cheio")))
    with pytest.raises(OSError):
        cfg.save_config({"monitor": "novo"})
    assert _written(tmp_path) == {"monitor": "original"}
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_update_config_preserves_other_keys(tmp_path):
    cfg.save_config({**cfg.DEFAULTS, "monitor": "mon"})
    cfg.update_config(last_dir="/dir")
    saved = _written(tmp_path)
    assert saved["monitor"] == "mon"
    assert saved["last_dir"] == "/dir"


# ── Fontes de áudio ───────────────────────────────────────────────────────────

PACTL_OUTPUT = (
    "0\talsa_input.usb-mic-00.analog\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
    "1\talsa_output.usb-headset-00.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
    "2\talsa_output.usb-speaker-01.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
)


@pytest.fixture
def pactl(mocker):
    def _set(stdout=PACTL_OUTPUT, **kwargs):
        return mocker.patch(
            "alex_transcritor.config.subprocess.run",
            return_value=MagicMock(stdout=stdout),
            **kwargs,
        )
    return _set


def test_list_monitor_sources_returns_monitors(pactl):
    pactl()
    sources = cfg.list_monitor_sources()
    assert len(sources) == 2
    assert all("monitor" in s.lower() for s in sources)


def test_list_input_sources_excludes_monitors(pactl):
    pactl()
    assert cfg.list_input_sources() == ["alsa_input.usb-mic-00.analog"]


def test_list_monitor_sources_empty_output(pactl):
    pactl(stdout="")
    assert cfg.list_monitor_sources() == []


def test_list_monitor_sources_handles_names_with_spaces(pactl):
    pactl(stdout="0\tfonte com espaco.monitor\tPipeWire\ts16le\tIDLE\n")
    assert cfg.list_monitor_sources() == ["fonte com espaco.monitor"]


def test_list_monitor_sources_pactl_not_found(mocker):
    mocker.patch("alex_transcritor.config.subprocess.run", side_effect=FileNotFoundError)
    assert cfg.list_monitor_sources() == []


def test_list_monitor_sources_timeout(mocker):
    mocker.patch(
        "alex_transcritor.config.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pactl", timeout=5),
    )
    assert cfg.list_monitor_sources() == []


# ── get_monitor / get_mic ─────────────────────────────────────────────────────

def test_get_monitor_keeps_saved_when_still_present(tmp_path, pactl):
    (tmp_path / "config.json").write_text(
        '{"monitor": "alsa_output.usb-speaker-01.analog-stereo.monitor"}'
    )
    pactl()
    assert cfg.get_monitor() == "alsa_output.usb-speaker-01.analog-stereo.monitor"


def test_get_monitor_replaces_device_that_disappeared(tmp_path, pactl):
    """Dispositivo salvo que não existe mais faria o ffmpeg gravar a fonte errada."""
    (tmp_path / "config.json").write_text('{"monitor": "fone_desconectado.monitor"}')
    pactl()
    result = cfg.get_monitor()
    assert result == "alsa_output.usb-headset-00.analog-stereo.monitor"
    assert _written(tmp_path)["monitor"] == result


def test_get_monitor_auto_detect_saves(tmp_path, pactl):
    pactl(stdout="1\tauto.monitor\tPipeWire\n")
    assert cfg.get_monitor() == "auto.monitor"
    assert _written(tmp_path)["monitor"] == "auto.monitor"


def test_get_monitor_none_available(mocker):
    mocker.patch("alex_transcritor.config.subprocess.run", side_effect=FileNotFoundError)
    assert cfg.get_monitor() == ""


def test_get_mic_returns_input_source(pactl):
    pactl()
    assert cfg.get_mic() == "alsa_input.usb-mic-00.analog"


# ── Diretório de saída ────────────────────────────────────────────────────────

def test_get_last_output_dir_default(tmp_path):
    assert cfg.get_last_output_dir() == str(tmp_path / "transcricoes")


def test_get_last_output_dir_from_config(tmp_path):
    (tmp_path / "config.json").write_text('{"last_dir": "/custom/path"}')
    assert cfg.get_last_output_dir() == "/custom/path"


def test_save_last_output_dir(tmp_path):
    cfg.save_last_output_dir("/my/path")
    assert _written(tmp_path)["last_dir"] == "/my/path"


# ── Vocabulário e correções ───────────────────────────────────────────────────

def test_initial_prompt_empty_when_no_vocabulary():
    assert cfg.get_initial_prompt() == ""


def test_initial_prompt_lists_terms(tmp_path):
    (tmp_path / "config.json").write_text('{"vocabulary": "PipeWire, Pedroza\\nKubernetes"}')
    prompt = cfg.get_initial_prompt()
    assert "PipeWire" in prompt and "Pedroza" in prompt and "Kubernetes" in prompt


def test_initial_prompt_ignores_blank_terms(tmp_path):
    (tmp_path / "config.json").write_text('{"vocabulary": " , ,PipeWire, "}')
    assert cfg.get_initial_prompt().count(",") == 0  # apenas um termo, sem separador


def test_replacements_parses_pairs(tmp_path):
    (tmp_path / "config.json").write_text(
        '{"replacements": "pipe lady => PipeWire\\npedrona=>Pedroza"}'
    )
    assert cfg.get_replacements() == [("pipe lady", "PipeWire"), ("pedrona", "Pedroza")]


def test_replacements_ignores_malformed_lines(tmp_path):
    (tmp_path / "config.json").write_text('{"replacements": "linha sem seta\\n => vazio"}')
    assert cfg.get_replacements() == []


def test_initial_prompt_is_capped(tmp_path):
    """Prompt maior que o contexto do Whisper desperdiça tokens sem beneficiar ninguém."""
    (tmp_path / "config.json").write_text(
        json.dumps({"vocabulary": ", ".join(f"termo{i}" for i in range(500))})
    )
    prompt = cfg.get_initial_prompt()
    assert 0 < len(prompt) <= cfg.MAX_PROMPT_CHARS
    assert prompt.endswith(".")
    assert "termo0" in prompt


def test_initial_prompt_empty_when_single_term_is_absurd(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"vocabulary": "A" * 5000}))
    assert cfg.get_initial_prompt() == ""
