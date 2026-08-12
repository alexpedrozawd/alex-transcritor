import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .constants import AUDIO_FORMATS, DEFAULT_AUDIO_FORMAT, WHISPER_MODELS

CONFIG_DIR: Path = Path.home() / ".config" / "alex-transcritor"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
DEFAULT_OUTPUT_DIR: str = str(Path.home() / "transcricoes")

SOURCE_MODES: tuple[str, ...] = ("system", "mic", "both")
DEVICES: tuple[str, ...] = ("auto", "cuda", "cpu")
TRANSCRIPTION_BACKENDS: tuple[str, ...] = ("local", "remote")
REMOTE_TOKEN_KEY = "remote_" + "token"

#: Valor padrão de cada chave. Também define o tipo esperado: um valor lido do
#: disco com tipo divergente é descartado em favor do padrão.
DEFAULTS: dict = {
    "monitor": "",
    "mic": "",
    "source_mode": "system",
    "last_dir": "",           # vazio → DEFAULT_OUTPUT_DIR (resolvido em runtime)
    # "turbo" reduziu o WER de 22,1% para 5,8% num trecho em português medido
    # contra transcrição de referência. Em GPU pequena ele roda em CPU, perto de
    # 1,2x a duração do áudio; "small" continua a um clique para quem prefere.
    "model": "turbo",
    "language": "pt",
    "audio_format": DEFAULT_AUDIO_FORMAT,
    "enhance_audio": True,
    "vocabulary": "",
    "replacements": "",
    "device": "auto",
    "transcription_backend": "local",
    "remote_url": "http://100.84.64.122:8300",
    REMOTE_TOKEN_KEY: "",
    "diarize_speakers": False,  # opt-in, remoto apenas — exige token HF configurado no servidor
    "live_transcription": False,  # opt-in — remoto usa websocket-client; local exige faster-whisper
    # "small" equilibra qualidade e velocidade no caminho principal (servidor
    # com GPU). Em modo local, que roda em CPU, pode valer baixar para "tiny".
    "live_model": "small",
}


# ── Persistência ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Lê o config do disco, ignorando valores ausentes, corrompidos ou de tipo errado."""
    raw: dict = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                raw = data
        except (json.JSONDecodeError, OSError, ValueError):
            raw = {}

    config = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        if isinstance(default, bool):
            if isinstance(value, bool):
                config[key] = value
        elif isinstance(value, str):
            config[key] = value
    return _coerce_enums(config)


def _coerce_enums(config: dict) -> dict:
    """Reverte para o padrão qualquer chave enumerada com valor fora do domínio."""
    for key, allowed in (
        ("source_mode", SOURCE_MODES),
        ("device", DEVICES),
        ("audio_format", tuple(AUDIO_FORMATS)),
        ("model", WHISPER_MODELS),
        ("transcription_backend", TRANSCRIPTION_BACKENDS),
        ("live_model", WHISPER_MODELS),
    ):
        if config[key] not in allowed:
            config[key] = DEFAULTS[key]
    return config


def save_config(data: dict) -> None:
    """Grava o config de forma atômica e com permissão 0600.

    Escreve em arquivo temporário no mesmo diretório e faz ``os.replace``: uma
    falha no meio da gravação preserva o config anterior em vez de deixar um
    arquivo truncado.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)

    fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".config-", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update_config(**changes) -> dict:
    """Aplica alterações pontuais preservando as demais chaves."""
    config = load_config()
    config.update(changes)
    save_config(config)
    return config


# ── Dispositivos de áudio ─────────────────────────────────────────────────────

def _list_sources() -> list[tuple[str, str]]:
    """Retorna ``(nome, descrição)`` de cada fonte reportada pelo pactl."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    sources = []
    for line in result.stdout.splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 2 and parts[1]:
            sources.append((parts[1], parts[1]))
    return sources


def list_monitor_sources() -> list[str]:
    """Fontes de saída (o que o sistema está reproduzindo)."""
    return [name for name, _ in _list_sources() if "monitor" in name.lower()]


def list_input_sources() -> list[str]:
    """Fontes de entrada (microfones) — tudo que não é monitor."""
    return [name for name, _ in _list_sources() if "monitor" not in name.lower()]


def get_monitor() -> str:
    """Monitor configurado, validado contra os dispositivos existentes agora.

    Um dispositivo salvo que não existe mais (fone desconectado, placa trocada)
    é substituído pelo primeiro disponível — sem isso o ffmpeg grava
    silenciosamente da fonte padrão, que raramente é a desejada.
    """
    return _resolve_device("monitor", list_monitor_sources())


def get_mic() -> str:
    """Microfone configurado, validado contra os dispositivos existentes agora."""
    return _resolve_device("mic", list_input_sources())


def _resolve_device(key: str, available: list[str]) -> str:
    config = load_config()
    saved = config.get(key, "")
    if saved and saved in available:
        return saved
    if not available:
        return ""
    if saved != available[0]:
        update_config(**{key: available[0]})
    return available[0]


# ── Acessores de conveniência ─────────────────────────────────────────────────

def get_last_output_dir() -> str:
    return load_config().get("last_dir") or DEFAULT_OUTPUT_DIR


def save_last_output_dir(path: str) -> None:
    update_config(last_dir=path)


#: O Whisper só aceita cerca de 224 tokens de prompt e descarta o excesso; um
#: vocabulário gigante ocuparia o contexto sem beneficiar termo nenhum.
MAX_PROMPT_CHARS = 700


def get_initial_prompt() -> str:
    """Monta o ``initial_prompt`` do Whisper a partir do vocabulário do usuário.

    O prompt não é uma instrução: é um texto que o modelo trata como se tivesse
    acabado de ouvir, o que enviesa a decodificação em favor desses termos.
    """
    terms = [t.strip() for t in re.split(r"[,\n;]", load_config()["vocabulary"]) if t.strip()]
    if not terms:
        return ""
    prefix = "Transcrição em português do Brasil. Termos que aparecem: "
    body = ""
    for term in terms:
        candidate = f"{body}, {term}" if body else term
        if len(prefix) + len(candidate) + 1 > MAX_PROMPT_CHARS:
            break
        body = candidate
    return f"{prefix}{body}." if body else ""


def get_replacements() -> list[tuple[str, str]]:
    """Substituições pós-transcrição no formato ``errado => certo`` por linha."""
    pairs = []
    for line in load_config()["replacements"].splitlines():
        if "=>" not in line:
            continue
        wrong, _, right = line.partition("=>")
        if wrong.strip():
            pairs.append((wrong.strip(), right.strip()))
    return pairs
