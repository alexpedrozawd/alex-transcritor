#!/usr/bin/env bash
set -euo pipefail

UNIT="$HOME/.config/systemd/user/alex-transcritor-server.service"
ENV_FILE="$HOME/.config/alex-transcritor/server.env"

echo "Isso desativa o servidor remoto e remove sua unidade e token."
echo "O ambiente .server-env e o cache do Whisper serão preservados."
read -rp "Confirmar? [s/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[Ss]$ ]] || { echo "Cancelado."; exit 0; }

systemctl --user disable --now alex-transcritor-server.service 2>/dev/null || true
[[ -f "$UNIT" ]] && rm -f "$UNIT"
[[ -f "$ENV_FILE" ]] && rm -f "$ENV_FILE"
systemctl --user daemon-reload
echo "Servidor remoto desinstalado. Ambiente e modelo preservados."
