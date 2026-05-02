from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton
from PyQt6.QtCore import Qt

from ..config import load_config, save_config, list_monitor_sources

_DIALOG_STYLE = """
    QDialog, QWidget {
        background-color: #111111;
        color: #e0e0e0;
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    QLabel {
        font-size: 11px;
        color: #888;
        font-weight: 600;
        letter-spacing: 1px;
    }
    QComboBox {
        background-color: #1e1e1e;
        border: 1px solid #2a2a2a;
        border-radius: 6px;
        padding: 7px 10px;
        font-size: 12px;
        color: #e0e0e0;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background-color: #1e1e1e;
        color: #e0e0e0;
        selection-background-color: #2a2a2a;
    }
    QPushButton {
        background-color: #c0392b;
        color: #fff;
        border: none;
        border-radius: 6px;
        padding: 9px 24px;
        font-size: 13px;
        font-weight: 700;
    }
    QPushButton:hover { background-color: #e74c3c; }
"""

_NO_SOURCE_PLACEHOLDER = "(nenhuma fonte encontrada)"


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setFixedSize(460, 160)
        self.setStyleSheet(_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        layout.addWidget(QLabel("DISPOSITIVO DE ÁUDIO (MONITOR)"))

        self.combo = QComboBox()
        sources = list_monitor_sources()
        current = load_config().get("monitor", "")

        if not sources:
            self.combo.addItem(_NO_SOURCE_PLACEHOLDER)
        else:
            for s in sources:
                self.combo.addItem(s)
            if current in sources:
                self.combo.setCurrentText(current)

        layout.addWidget(self.combo)
        layout.addSpacing(8)

        btn_save = QPushButton("Salvar")
        btn_save.clicked.connect(self._save)
        layout.addWidget(btn_save, alignment=Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        source = self.combo.currentText()
        if source and source != _NO_SOURCE_PLACEHOLDER:
            save_config({**load_config(), "monitor": source})
        self.accept()
