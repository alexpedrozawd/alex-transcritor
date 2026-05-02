import json
import subprocess
from pathlib import Path

CONFIG_DIR: Path = Path.home() / ".config" / "alex-transcritor"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
DEFAULT_OUTPUT_DIR: str = str(Path.home() / "transcricoes")


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def list_monitor_sources() -> list[str]:
    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return [
            parts[1]
            for line in result.stdout.splitlines()
            if (parts := line.split()) and len(parts) >= 2 and "monitor" in parts[1].lower()
        ]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def get_monitor() -> str:
    config = load_config()
    if monitor := config.get("monitor"):
        return str(monitor)
    sources = list_monitor_sources()
    if sources:
        save_config({**config, "monitor": sources[0]})
        return sources[0]
    return ""


def get_last_output_dir() -> str:
    return str(load_config().get("last_dir", DEFAULT_OUTPUT_DIR))


def save_last_output_dir(path: str) -> None:
    save_config({**load_config(), "last_dir": path})
