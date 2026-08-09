# Alex Transcritor

A lightweight Linux desktop app for **automatic audio recording and transcription** using [OpenAI Whisper](https://github.com/openai/whisper). Fully offline — no API keys, no cloud, no subscriptions.

---

## What it does

- Captures system audio, microphone, or **both mixed together** (PulseAudio/PipeWire via FFmpeg)
- Records **lossless FLAC** at 16 kHz mono — the exact format Whisper consumes
- Transcribes locally, picking GPU or CPU automatically based on available VRAM
- Accepts a **custom vocabulary** so proper nouns and jargon come out right
- Applies user-defined find/replace corrections to the final text
- Shows live progress and never overwrites an existing recording

## Accuracy

Transcription quality is dominated by the model and by whether the audio reaches Whisper intact. Measured on a Brazilian-Portuguese sample against a reference transcript (86 words, Intel i5-10300H + GTX 1650):

| Configuration | WER |
|---|---|
| `small` model, 24 kb/s MP3, no vocabulary | 22.1% |
| `small` model, lossless, with vocabulary prompt | 19.8% |
| **`turbo` model, lossless, with vocabulary prompt** | **5.8%** |

Quiet recordings benefit further from the built-in adaptive gain: on a sample peaking at −24 dBFS, WER dropped from 23.3% to 12.8%. The gain is applied **only** when the audio is genuinely quiet — normalizing already-adequate audio measured *worse* (19.8% → 24.4%), so the app measures first.

## System requirements

| Requirement | Minimum |
|---|---|
| Linux (Ubuntu, Debian, Fedora, Arch, …) | — |
| Python | 3.10+ |
| FFmpeg + ffprobe | any modern version |
| PulseAudio or PipeWire | with `pactl` available |
| Disk space | ~4 GB (venv + Whisper model) |

An NVIDIA GPU is optional. Models that do not fit in VRAM run on CPU automatically — slower, same accuracy.

## Installation

```bash
git clone https://github.com/alexpedrozawd/alex-transcritor
cd alex-transcritor
bash install.sh
```

The installer handles system dependencies, the Python virtual environment, the Whisper model download, desktop menu integration, and a final smoke test.

See the [User Manual](docs/MANUAL_USUARIO.md) (Portuguese) for step-by-step instructions.

## How to use

1. Launch from the application menu or run `alex-transcritor`
2. Click **⚙** (top right) → pick your audio device and **add your vocabulary**
3. Enter a file name and choose an output directory
4. **Record** → **Stop** → watch the progress bar
5. **Audio** and **Text** buttons appear when the transcription is ready

## Project structure

```
alex-transcritor/
├── alex_transcritor/      ← main Python package
│   ├── app.py             ← entry point, dependency check, single-instance guard
│   ├── audio.py           ← ffmpeg command building and level measurement
│   ├── config.py          ← validated, atomically-written configuration
│   ├── constants.py       ← paths, formats, model metadata
│   ├── hardware.py        ← GPU detection and device selection
│   ├── worker.py          ← transcription thread (progress, CPU fallback, cancel)
│   └── ui/                ← main window, settings dialog, styles
├── tests/                 ← test suite (201 tests, 99% coverage)
├── assets/                ← application icon
├── scripts/               ← utilities (icon generation)
├── docs/                  ← user and developer manuals
├── main.py                ← thin entry point
├── install.sh             ← installer
└── uninstall.sh           ← uninstaller
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ --cov --cov-report=term-missing
bandit -c pyproject.toml -r alex_transcritor
pip-audit -r requirements.txt
```

## Uninstall

```bash
bash uninstall.sh
```

Removes the app, launcher, menu entry and configuration. Whisper models in `~/.cache/whisper` and your recordings are left untouched.

## Privacy

Audio never leaves the machine. The model is downloaded once and every transcription runs locally. Configuration and error logs are written with owner-only permissions.

## License

Personal use. Project by Alexandre Pedroza.
