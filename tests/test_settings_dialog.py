import json

import pytest

import alex_transcritor.config as cfg
from alex_transcritor.ui.settings_dialog import SettingsDialog, _NO_SOURCE_PLACEHOLDER


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")


@pytest.fixture
def dialog_no_sources(qtbot, monkeypatch):
    monkeypatch.setattr("alex_transcritor.ui.settings_dialog.list_monitor_sources", lambda: [])
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    return dlg


@pytest.fixture
def dialog_with_sources(qtbot, monkeypatch):
    sources = ["monitor_a", "monitor_b"]
    monkeypatch.setattr("alex_transcritor.ui.settings_dialog.list_monitor_sources", lambda: sources)
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    return dlg


# ── Carregamento ──────────────────────────────────────────────────────────────

def test_no_sources_shows_placeholder(dialog_no_sources):
    assert dialog_no_sources.combo.count() == 1
    assert dialog_no_sources.combo.currentText() == _NO_SOURCE_PLACEHOLDER


def test_sources_populated(dialog_with_sources):
    assert dialog_with_sources.combo.count() == 2
    items = [dialog_with_sources.combo.itemText(i) for i in range(2)]
    assert "monitor_a" in items
    assert "monitor_b" in items


def test_saved_monitor_is_preselected(tmp_path, qtbot, monkeypatch):
    (tmp_path / "config.json").write_text('{"monitor": "monitor_b"}')
    sources = ["monitor_a", "monitor_b"]
    monkeypatch.setattr("alex_transcritor.ui.settings_dialog.list_monitor_sources", lambda: sources)
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.combo.currentText() == "monitor_b"


# ── Salvar ────────────────────────────────────────────────────────────────────

def test_save_writes_monitor_to_config(tmp_path, dialog_with_sources):
    dialog_with_sources.combo.setCurrentText("monitor_a")
    dialog_with_sources._save()
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["monitor"] == "monitor_a"


def test_save_placeholder_does_not_write_config(tmp_path, dialog_no_sources):
    dialog_no_sources._save()
    assert not (tmp_path / "config.json").exists()


def test_save_preserves_existing_keys(tmp_path, dialog_with_sources):
    (tmp_path / "config.json").write_text('{"last_dir": "/some/path"}')
    dialog_with_sources.combo.setCurrentText("monitor_b")
    dialog_with_sources._save()
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["last_dir"] == "/some/path"
    assert saved["monitor"] == "monitor_b"
