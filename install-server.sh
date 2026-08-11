#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$PROJECT_DIR/.server-env"
CONDA_BIN="${ALEX_CONDA_BIN:-/var/home/apsrv/Projetos/ap-ai-studio/miniconda3/bin/conda}"
ROCM_SOURCE_ENV="${ALEX_ROCM_SOURCE_ENV:-/var/home/apsrv/Projetos/ap-ai-studio/miniconda3/envs/vfx-pipeline}"
CONFIG_DIR="$HOME/.config/alex-transcritor"
ENV_FILE="$CONFIG_DIR/server.env"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/alex-transcritor-server.service"
SERVER_IP="${ALEX_SERVER_IP:-$(tailscale ip -4 | head -1)}"
CLIENT_IP="${ALEX_CLIENT_IP:-100.88.218.16}"
PORT="${ALEX_SERVER_PORT:-8300}"

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
    [[ -x "$CONDA_BIN" && -x "$ROCM_SOURCE_ENV/bin/python" ]] || {
        echo "Conda ou ambiente ROCm de origem não encontrado." >&2
        exit 1
    }
    echo "Criando ambiente ROCm isolado em $ENV_DIR..."
    "$CONDA_BIN" create -y -p "$ENV_DIR" --clone "$ROCM_SOURCE_ENV"
fi
SERVER_IP_VALUE="$SERVER_IP" CLIENT_IP_VALUE="$CLIENT_IP" PORT_VALUE="$PORT" \
    "$ENV_DIR/bin/python" - <<'PY'
import ipaddress
import os

tailnet = ipaddress.ip_network("100.64.0.0/10")
for name in ("SERVER_IP_VALUE", "CLIENT_IP_VALUE"):
    address = ipaddress.ip_address(os.environ[name])
    if address not in tailnet:
        raise SystemExit(f"{name} não pertence à faixa Tailscale: {address}")
port = int(os.environ["PORT_VALUE"])
if not 1 <= port <= 65535:
    raise SystemExit(f"Porta inválida: {port}")
PY

"$ENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements-server.txt"
"$ENV_DIR/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("PyTorch ROCm não reconheceu a GPU.")
name = torch.cuda.get_device_name(0)
if "AMD" not in name.upper():
    raise SystemExit(f"GPU inesperada: {name}")
print(f"GPU validada: {name} · torch {torch.__version__} · HIP {torch.version.hip}")
PY
mkdir -p "$CONFIG_DIR" "$UNIT_DIR" "$HOME/.cache/whisper" "$HOME/.cache/miopen"
chmod 700 "$CONFIG_DIR"

SERVER_ENV_FILE="$ENV_FILE" CLIENT_IP_VALUE="$CLIENT_IP" WHISPER_BIN_VALUE="$ENV_DIR/bin/whisper" \
    "$ENV_DIR/bin/python" - <<'PY'
import os
import secrets
from pathlib import Path

path = Path(os.environ["SERVER_ENV_FILE"])
values = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
token = values.get("ALEX_TRANSCRITOR_TOKEN", "")
if len(token) < 32:
    token = secrets.token_urlsafe(48)
values = {
    "ALEX_TRANSCRITOR_TOKEN": token,
    "ALEX_TRANSCRITOR_ALLOWED_IP": os.environ["CLIENT_IP_VALUE"],
    "ALEX_TRANSCRITOR_WHISPER_BIN": os.environ["WHISPER_BIN_VALUE"],
}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as output:
    for key, value in values.items():
        output.write(f"{key}={value}\n")
PY
chmod 600 "$ENV_FILE"

umask 077
printf '%s\n' \
    '[Unit]' \
    'Description=Alex Transcritor — servidor privado de transcrição' \
    'After=network-online.target tailscaled.service' \
    'Wants=network-online.target' \
    '' \
    '[Service]' \
    'Type=simple' \
    "WorkingDirectory=$PROJECT_DIR" \
    "EnvironmentFile=$ENV_FILE" \
    "ExecStart=$ENV_DIR/bin/uvicorn --factory alex_transcritor.server:create_app --host $SERVER_IP --port $PORT --no-server-header" \
    'Restart=on-failure' \
    'RestartSec=5' \
    'UMask=0077' \
    'NoNewPrivileges=true' \
    'PrivateTmp=true' \
    'ProtectSystem=strict' \
    'ProtectHome=read-only' \
    'ProtectControlGroups=true' \
    'ProtectKernelLogs=true' \
    'ProtectKernelModules=true' \
    'ProtectKernelTunables=true' \
    'LockPersonality=true' \
    'RestrictRealtime=true' \
    'RestrictSUIDSGID=true' \
    'CapabilityBoundingSet=' \
    "ReadWritePaths=$HOME/.cache/whisper $HOME/.cache/miopen" \
    'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6' \
    'MemoryHigh=20G' \
    'MemoryMax=24G' \
    'OOMScoreAdjust=200' \
    '' \
    '[Install]' \
    'WantedBy=default.target' \
    > "$UNIT_FILE"
chmod 600 "$UNIT_FILE"

systemctl --user daemon-reload
systemctl --user enable alex-transcritor-server.service
systemctl --user restart alex-transcritor-server.service
for _ in {1..20}; do
    systemctl --user is-active --quiet alex-transcritor-server.service || break
    if timeout 1 bash -c "</dev/tcp/$SERVER_IP/$PORT" 2>/dev/null; then
        break
    fi
    sleep 0.25
done
if ! systemctl --user is-active --quiet alex-transcritor-server.service || \
   ! timeout 1 bash -c "</dev/tcp/$SERVER_IP/$PORT" 2>/dev/null; then
    systemctl --user status alex-transcritor-server.service --no-pager >&2 || true
    exit 1
fi
echo "Servidor instalado em http://$SERVER_IP:$PORT (cliente permitido: $CLIENT_IP)."
echo "Token preservado em $ENV_FILE; ele não foi exibido."
