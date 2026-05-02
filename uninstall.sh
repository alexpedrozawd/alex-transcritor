#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

INSTALL_DIR="$HOME/.local/share/alex-transcritor"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
APP_NAME="alex-transcritor"

echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║     Alex Transcritor — Desinstalador     ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Isso removerá:${NC}"
echo "  • $INSTALL_DIR (app + venv)"
echo "  • $BIN_DIR/$APP_NAME (launcher)"
echo "  • $DESKTOP_DIR/$APP_NAME.desktop"
echo "  • $HOME/.config/alex-transcritor (configurações)"
echo ""
echo -e "${YELLOW}Não serão removidos:${NC} ~/.cache/whisper (modelos Whisper)"
echo ""
read -rp "Confirmar desinstalação? [s/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[Ss]$ ]] || { echo "Cancelado."; exit 0; }

echo ""
[[ -d "$INSTALL_DIR" ]]                         && { rm -rf "$INSTALL_DIR"; echo -e "${GREEN}[✓]${NC} $INSTALL_DIR removido"; }
[[ -f "$BIN_DIR/$APP_NAME" ]]                   && { rm -f "$BIN_DIR/$APP_NAME"; echo -e "${GREEN}[✓]${NC} Launcher removido"; }
[[ -f "$DESKTOP_DIR/$APP_NAME.desktop" ]]       && { rm -f "$DESKTOP_DIR/$APP_NAME.desktop"; echo -e "${GREEN}[✓]${NC} Entrada de menu removida"; }
[[ -d "$HOME/.config/alex-transcritor" ]]       && { rm -rf "$HOME/.config/alex-transcritor"; echo -e "${GREEN}[✓]${NC} Configurações removidas"; }

command -v update-desktop-database &>/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo -e "${GREEN}${BOLD}Desinstalação concluída.${NC}"
echo ""
