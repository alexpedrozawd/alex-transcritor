import pytest

import alex_transcritor.config as cfg
from alex_transcritor.ui.settings_dialog import SettingsDialog, NO_SOURCE_PLACEHOLDER


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg, "DEFAULT_OUTPUT_DIR", str(tmp_path / "transcricoes"))


@pytest.fixture(autouse=True)
def fake_hardware(monkeypatch):
    monkeypatch.setattr("alex_transcritor.ui.settings_dialog.gpu_vram_gb", lambda: 4.0)


@pytest.fixture
def sources(monkeypatch):
    def _set(monitors=("monitor_a", "monitor_b"), mics=("mic_a",)):
        monkeypatch.setattr(
            "alex_transcritor.ui.settings_dialog.list_monitor_sources", lambda: list(monitors)
        )
        monkeypatch.setattr(
            "alex_transcritor.ui.settings_dialog.list_input_sources", lambda: list(mics)
        )
    return _set


@pytest.fixture
def dialog(qtbot, sources):
    def _make(**config):
        sources()
        if config:
            cfg.update_config(**config)
        dlg = SettingsDialog()
        qtbot.addWidget(dlg)
        return dlg
    return _make


# ── Carregamento ──────────────────────────────────────────────────────────────

def test_monitors_populated(dialog):
    dlg = dialog()
    assert [dlg.combo_monitor.itemText(i) for i in range(dlg.combo_monitor.count())] == [
        "monitor_a", "monitor_b"
    ]


def test_mics_populated(dialog):
    dlg = dialog()
    assert dlg.combo_mic.itemText(0) == "mic_a"


def test_placeholder_when_no_sources(qtbot, sources):
    sources(monitors=(), mics=())
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.combo_monitor.currentText() == NO_SOURCE_PLACEHOLDER
    assert dlg.combo_mic.currentText() == NO_SOURCE_PLACEHOLDER


def test_saved_monitor_is_preselected(dialog):
    dlg = dialog(monitor="monitor_b")
    assert dlg.combo_monitor.currentText() == "monitor_b"


def test_saved_model_is_preselected(dialog):
    dlg = dialog(model="tiny")
    assert dlg.combo_model.currentData() == "tiny"


def test_defaults_are_preselected(dialog):
    dlg = dialog()
    assert dlg.combo_model.currentData() == cfg.DEFAULTS["model"]
    assert dlg.combo_language.currentData() == "pt"
    assert dlg.combo_format.currentData() == "flac"
    assert dlg.combo_device.currentData() == "auto"
    assert dlg.check_enhance.isChecked()


def test_live_transcription_fields_preselected(dialog):
    dlg = dialog(live_transcription=True, live_model="tiny")
    assert dlg.check_live.isChecked()
    assert dlg.combo_live_model.currentData() == "tiny"


def test_live_transcription_defaults_off(dialog):
    dlg = dialog()
    assert not dlg.check_live.isChecked()
    assert dlg.combo_live_model.currentData() == cfg.DEFAULTS["live_model"]


def test_vocabulary_and_replacements_loaded(dialog):
    dlg = dialog(vocabulary="PipeWire", replacements="a => b")
    assert dlg.edit_vocabulary.toPlainText() == "PipeWire"
    assert dlg.edit_replacements.toPlainText() == "a => b"


# ── Modo de origem ────────────────────────────────────────────────────────────

def test_system_mode_disables_mic_field(dialog):
    dlg = dialog(source_mode="system")
    assert dlg.combo_monitor.isEnabled()
    assert not dlg.combo_mic.isEnabled()


def test_mic_mode_disables_monitor_field(dialog):
    dlg = dialog(source_mode="mic")
    assert not dlg.combo_monitor.isEnabled()
    assert dlg.combo_mic.isEnabled()


def test_both_mode_enables_everything(dialog):
    dlg = dialog(source_mode="both")
    assert dlg.combo_monitor.isEnabled() and dlg.combo_mic.isEnabled()


def test_changing_mode_updates_fields(dialog):
    dlg = dialog(source_mode="system")
    dlg.combo_source.setCurrentIndex(dlg.combo_source.findData("mic"))
    assert not dlg.combo_monitor.isEnabled() and dlg.combo_mic.isEnabled()


def test_remote_backend_enables_server_fields(dialog):
    dlg = dialog(transcription_backend="remote")
    assert dlg.input_remote_url.isEnabled()
    assert dlg.input_remote_token.isEnabled()
    assert not dlg.combo_device.isEnabled()


# ── Salvar ────────────────────────────────────────────────────────────────────

def test_save_writes_every_field(dialog):
    dlg = dialog()
    dlg.combo_monitor.setCurrentText("monitor_a")
    dlg.combo_source.setCurrentIndex(dlg.combo_source.findData("both"))
    dlg.combo_model.setCurrentIndex(dlg.combo_model.findData("medium"))
    dlg.combo_language.setCurrentIndex(dlg.combo_language.findData("en"))
    dlg.combo_device.setCurrentIndex(dlg.combo_device.findData("cpu"))
    dlg.combo_format.setCurrentIndex(dlg.combo_format.findData("mp3"))
    dlg.combo_backend.setCurrentIndex(dlg.combo_backend.findData("remote"))
    dlg.input_remote_url.setText("http://100.84.64.122:8300/")
    dlg.input_remote_token.setText("x" * 32)
    dlg.check_enhance.setChecked(False)
    dlg.edit_vocabulary.setPlainText("Kubernetes")
    dlg.edit_replacements.setPlainText("errado => certo")
    dlg.check_live.setChecked(True)
    dlg.combo_live_model.setCurrentIndex(dlg.combo_live_model.findData("base"))
    dlg._save()

    saved = cfg.load_config()
    assert saved["monitor"] == "monitor_a"
    assert saved["mic"] == "mic_a"
    assert saved["source_mode"] == "both"
    assert saved["model"] == "medium"
    assert saved["language"] == "en"
    assert saved["device"] == "cpu"
    assert saved["audio_format"] == "mp3"
    assert saved["enhance_audio"] is False
    assert saved["vocabulary"] == "Kubernetes"
    assert saved["replacements"] == "errado => certo"
    assert saved["transcription_backend"] == "remote"
    assert saved["remote_url"] == "http://100.84.64.122:8300"
    assert saved["remote_token"] == "x" * 32
    assert saved["live_transcription"] is True
    assert saved["live_model"] == "base"


def test_save_does_not_store_placeholder_as_device(qtbot, sources):
    sources(monitors=(), mics=())
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    dlg._save()
    assert cfg.load_config()["monitor"] == ""


def test_save_preserves_unrelated_keys(dialog):
    dlg = dialog(last_dir="/algum/lugar")
    dlg._save()
    assert cfg.load_config()["last_dir"] == "/algum/lugar"


def test_cancel_does_not_persist_changes(dialog):
    dlg = dialog(model="tiny")
    dlg.combo_model.setCurrentIndex(dlg.combo_model.findData("turbo"))
    dlg.reject()
    assert cfg.load_config()["model"] == "tiny"


# ── Dica de hardware ──────────────────────────────────────────────────────────

def test_hardware_hint_mentions_gpu_when_present(dialog):
    assert "4.0 GB" in dialog()._hardware_hint()


def test_hardware_hint_mentions_cpu_without_gpu(qtbot, sources, monkeypatch):
    sources()
    monkeypatch.setattr("alex_transcritor.ui.settings_dialog.gpu_vram_gb", lambda: 0.0)
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert "CPU" in dlg._hardware_hint()
