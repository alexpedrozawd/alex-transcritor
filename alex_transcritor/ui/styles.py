_BASE = """
QMainWindow, QDialog, QWidget {
    background-color: #111111;
    color: #e0e0e0;
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
QLineEdit, QPlainTextEdit {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    color: #e0e0e0;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #6a6a6a; }
QComboBox {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 12px;
    color: #e0e0e0;
}
QComboBox:disabled { color: #5a5a5a; background-color: #171717; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    color: #e0e0e0;
    selection-background-color: #333333;
}
QCheckBox { font-size: 12px; color: #c8c8c8; }
QLabel#label_hint {
    font-size: 11px;
    color: #8a8a8a;
    font-weight: 400;
    letter-spacing: 0;
}
"""

STYLE = _BASE + """
QLabel#label_title {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 2px;
}
QLabel#label_field {
    font-size: 10px;
    color: #8a8a8a;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#label_status { font-size: 12px; color: #9a9a9a; }
QPushButton#btn_record {
    background-color: #c0392b;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 11px 0;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QPushButton#btn_record:hover  { background-color: #e74c3c; }
QPushButton#btn_record:disabled { background-color: #2a2a2a; color: #6a6a6a; }
QPushButton#btn_stop {
    background-color: #1e1e1e;
    color: #d0d0d0;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 11px 0;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#btn_stop:hover   { background-color: #2a2a2a; color: #ffffff; }
QPushButton#btn_stop:disabled { color: #5a5a5a; border-color: #232323; }
QPushButton#btn_dir {
    background-color: #1e1e1e;
    color: #b0b0b0;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 12px;
}
QPushButton#btn_dir:hover { background-color: #2a2a2a; color: #ffffff; }
QPushButton#btn_file {
    background-color: #1e1e1e;
    color: #b0b0b0;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 7px 4px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#btn_file:hover { background-color: #2a2a2a; color: #ffffff; }
QFrame#separator { background-color: #1e1e1e; border: none; max-height: 1px; }
QPushButton#btn_settings {
    background-color: transparent;
    color: #9a9a9a;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    font-size: 14px;
    padding: 0;
}
QPushButton#btn_settings:hover { background-color: #1e1e1e; color: #ffffff; border-color: #666; }
QProgressBar {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background-color: #f39c12; border-radius: 3px; }
QLabel#label_version { font-size: 9px; color: #6a6a6a; padding: 0; margin: 0; }
QTextEdit#livePanel {
    background-color: #161616;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 12px;
    color: #d0d0d0;
}
"""

DIALOG_STYLE = _BASE + """
QLabel {
    font-size: 10px;
    color: #9a9a9a;
    font-weight: 600;
    letter-spacing: 1px;
}
QTabWidget::pane { border: 1px solid #2a2a2a; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #161616;
    color: #9a9a9a;
    padding: 8px 18px;
    border: 1px solid #2a2a2a;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 12px;
}
QTabBar::tab:selected { background: #1e1e1e; color: #ffffff; }
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
QPushButton#btn_secondary {
    background-color: #1e1e1e;
    color: #d0d0d0;
    border: 1px solid #3a3a3a;
}
QPushButton#btn_secondary:hover { background-color: #2a2a2a; color: #ffffff; }
"""
