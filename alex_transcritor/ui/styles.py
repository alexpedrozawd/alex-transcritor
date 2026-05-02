STYLE = """
QMainWindow, QWidget {
    background-color: #111111;
    color: #e0e0e0;
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
QLabel#label_title {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 2px;
}
QLabel#label_field {
    font-size: 10px;
    color: #555;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#label_status {
    font-size: 12px;
    color: #555;
}
QLineEdit {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    color: #e0e0e0;
}
QLineEdit:focus {
    border-color: #444;
    outline: none;
}
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
QPushButton#btn_record:disabled { background-color: #2a2a2a; color: #444; }
QPushButton#btn_stop {
    background-color: #1e1e1e;
    color: #aaa;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 11px 0;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#btn_stop:hover   { background-color: #2a2a2a; color: #e0e0e0; }
QPushButton#btn_stop:disabled { color: #333; border-color: #1e1e1e; }
QPushButton#btn_dir {
    background-color: #1e1e1e;
    color: #666;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 12px;
}
QPushButton#btn_dir:hover { background-color: #2a2a2a; color: #ccc; }
QPushButton#btn_file {
    background-color: #1e1e1e;
    color: #888;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 7px 0;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#btn_file:hover { background-color: #2a2a2a; color: #e0e0e0; }
QFrame#separator { background-color: #1e1e1e; border: none; max-height: 1px; }
QPushButton#btn_settings {
    background-color: transparent;
    color: #3a3a3a;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    font-size: 14px;
    padding: 0;
}
QPushButton#btn_settings:hover { background-color: #1e1e1e; color: #888; border-color: #444; }
QLabel#label_version {
    font-size: 9px;
    color: #2a2a2a;
    padding: 0;
    margin: 0;
}
"""
