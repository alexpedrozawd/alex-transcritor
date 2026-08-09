from pathlib import Path

from alex_transcritor import constants


def test_prefers_venv_binary(tmp_path, monkeypatch):
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "whisper").write_text("")
    monkeypatch.setattr(constants, "INSTALL_DIR", tmp_path)
    assert constants.whisper_bin() == str(venv_bin / "whisper")


def test_falls_back_to_interpreter_sibling(tmp_path, monkeypatch):
    """Rodando do repositório clonado não existe venv/ dentro do projeto."""
    bindir = tmp_path / "outro" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "whisper").write_text("")
    (bindir / "python").write_text("")
    monkeypatch.setattr(constants, "INSTALL_DIR", tmp_path / "sem-venv")
    monkeypatch.setattr(constants.sys, "executable", str(bindir / "python"))
    assert constants.whisper_bin() == str(bindir / "whisper")


def test_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "INSTALL_DIR", tmp_path / "sem-venv")
    monkeypatch.setattr(constants.sys, "executable", str(tmp_path / "py" / "python"))
    monkeypatch.setattr(constants.shutil, "which", lambda cmd: "/usr/bin/whisper")
    assert constants.whisper_bin() == "/usr/bin/whisper"


def test_last_resort_points_at_expected_venv_path(tmp_path, monkeypatch):
    """Mesmo sem encontrar nada, devolve um caminho para a mensagem de erro."""
    monkeypatch.setattr(constants, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(constants.sys, "executable", str(tmp_path / "py" / "python"))
    monkeypatch.setattr(constants.shutil, "which", lambda cmd: None)
    assert constants.whisper_bin() == str(tmp_path / "venv" / "bin" / "whisper")


def test_every_model_has_a_vram_estimate():
    assert set(constants.WHISPER_MODELS) <= set(constants.MODEL_VRAM_GB)


def test_default_audio_format_is_lossless():
    assert constants.DEFAULT_AUDIO_FORMAT == "flac"
    assert "flac" in constants.AUDIO_FORMATS[constants.DEFAULT_AUDIO_FORMAT]
