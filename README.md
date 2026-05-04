# Alex Transcritor

A lightweight Linux desktop app for **automatic audio recording and transcription** using [OpenAI Whisper](https://github.com/openai/whisper). Fully offline — no API keys, no cloud, no subscriptions.

---

## What it does

- Captures system audio (PulseAudio/PipeWire monitor source) via FFmpeg
- Transcribes automatically using Whisper (`small` model)
- Minimal dark-themed GUI with system tray support
- Remembers the last output directory
- Auto-detects the available audio monitor device

## System requirements

| Requirement | Minimum version |
|---|---|
| Linux (Ubuntu, Debian, Fedora, Arch, etc.) | — |
| Python | 3.10+ |
| FFmpeg | any modern version |
| PulseAudio or PipeWire | with `pactl` available |
| Disk space | ~500 MB (venv + Whisper model) |

## Installation

```bash
git clone https://github.com/alexpedrozawd/alex-transcritor
cd alex-transcritor
chmod +x install.sh && bash install.sh
```

The installer handles everything: system dependencies, Python virtual environment, Whisper model download, and desktop menu integration.

See the [User Manual](docs/MANUAL_USUARIO.md) for detailed step-by-step instructions.

## How to use

1. Launch the app from the application menu or by typing `alex-transcritor` in the terminal
2. On first run: right-click the tray icon → **Settings** → select your audio device
3. Enter a file name and choose an output directory
4. Click **Record** → when done, click **Stop**
5. Wait for transcription — **Audio** and **Text** buttons will appear once complete

## Project structure

```
alex-transcritor/
├── alex_transcritor/      ← main Python package
│   ├── app.py             ← entry point and dependency check
│   ├── config.py          ← configuration and audio detection
│   ├── constants.py       ← paths and constants
│   ├── worker.py          ← transcription thread (Whisper)
│   └── ui/                ← interface components
├── tests/                 ← test suite (65 tests, 100% coverage)
├── assets/                ← application icon
├── scripts/               ← utilities (icon generation)
├── docs/                  ← user and developer manuals
├── main.py                ← entry point (3 lines)
├── install.sh             ← installer
├── uninstall.sh           ← uninstaller
├── requirements.txt       ← production dependencies
└── requirements-dev.txt   ← development dependencies
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ --cov --cov-report=term-missing
```

## Uninstall

```bash
bash uninstall.sh
```

## License

Personal use. Project by Alexandre Pedroza.
