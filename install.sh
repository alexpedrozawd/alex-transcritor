#!/usr/bin/env bash
set -euo pipefail

# ─── Cores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ─── Caminhos ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/alex-transcritor"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
APP_NAME="alex-transcritor"

# ─── Helpers ──────────────────────────────────────────────────────────────────
step()  { echo -e "${BLUE}[*]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
ask()   { echo -e "${YELLOW}[?]${NC} $*"; }

# ─── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║      Alex Transcritor — Instalador       ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ─── 1. Verificar origem ──────────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/main.py" ]]; then
    err "Execute este script dentro da pasta do projeto (onde está main.py)"
fi

# ─── 2. Dependências do sistema ───────────────────────────────────────────────
step "Verificando dependências do sistema..."

if command -v apt-get &>/dev/null; then
    PKG_INSTALL="sudo apt-get install -y"
    PKG_UPDATE="sudo apt-get update -qq"
elif command -v dnf &>/dev/null; then
    PKG_INSTALL="sudo dnf install -y"
    PKG_UPDATE="sudo dnf check-update -q || true"
elif command -v pacman &>/dev/null; then
    PKG_INSTALL="sudo pacman -S --noconfirm"
    PKG_UPDATE="sudo pacman -Sy"
else
    warn "Gerenciador de pacotes não reconhecido. Instale manualmente: python3 python3-venv python3-pip ffmpeg"
    PKG_INSTALL=""
    PKG_UPDATE=""
fi

# Python 3.10+
if ! command -v python3 &>/dev/null; then
    step "Instalando python3..."
    if [[ -n "$PKG_UPDATE" ]]; then $PKG_UPDATE; fi
    if [[ -n "$PKG_INSTALL" ]]; then
        $PKG_INSTALL python3 python3-pip python3-venv || err "Falha ao instalar python3"
    fi
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
PYVER_MAJOR=$(echo "$PYVER" | cut -d. -f1)
PYVER_MINOR=$(echo "$PYVER" | cut -d. -f2)

if [[ "$PYVER_MAJOR" -lt 3 ]] || { [[ "$PYVER_MAJOR" -eq 3 ]] && [[ "$PYVER_MINOR" -lt 10 ]]; }; then
    err "Python 3.10 ou superior é necessário (encontrado: $PYVER)"
fi
ok "Python $PYVER"

# python3-venv
if ! python3 -m venv --help &>/dev/null 2>&1; then
    step "Instalando python3-venv..."
    if [[ -n "$PKG_INSTALL" ]]; then
        $PKG_INSTALL python3-venv || err "Falha ao instalar python3-venv"
    fi
fi

# ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    step "Instalando ffmpeg..."
    if [[ -n "$PKG_UPDATE" ]]; then $PKG_UPDATE; fi
    if [[ -n "$PKG_INSTALL" ]]; then
        $PKG_INSTALL ffmpeg || err "Falha ao instalar ffmpeg"
    fi
else
    FFVER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
    ok "ffmpeg $FFVER"
fi

# PulseAudio / PipeWire
if command -v pactl &>/dev/null; then
    ok "PulseAudio/PipeWire (pactl disponível)"
else
    warn "pactl não encontrado — instale 'pulseaudio' ou 'pipewire-pulse'"
fi

# ─── 3. Criar diretórios ──────────────────────────────────────────────────────
step "Criando diretórios de instalação..."
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/assets" "$BIN_DIR" "$DESKTOP_DIR" "$HOME/transcricoes"
ok "Diretórios criados"

# ─── 4. Copiar arquivos do app ────────────────────────────────────────────────
step "Copiando arquivos do app para $INSTALL_DIR..."
cp "$SCRIPT_DIR/main.py" "$INSTALL_DIR/"

# Pacote Python principal
cp -r "$SCRIPT_DIR/alex_transcritor" "$INSTALL_DIR/"

# Scripts utilitários
if [[ -d "$SCRIPT_DIR/scripts" ]]; then
    cp -r "$SCRIPT_DIR/scripts" "$INSTALL_DIR/"
fi

# Assets
if [[ -f "$SCRIPT_DIR/assets/icon.png" ]]; then
    cp "$SCRIPT_DIR/assets/icon.png" "$INSTALL_DIR/assets/"
fi

ok "Arquivos copiados"

# ─── 5. Criar ambiente virtual Python ────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    warn "Venv já existe em $VENV_DIR — reutilizando"
else
    step "Criando venv em $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    ok "Venv criado"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

step "Atualizando pip..."
"$PIP" install --upgrade pip -q
ok "pip atualizado"

# ─── 6. Instalar dependências Python ─────────────────────────────────────────
step "Instalando dependências Python (PyQt6 + OpenAI Whisper)..."
"$PIP" install -r "$SCRIPT_DIR/requirements.txt" -q
ok "Dependências instaladas"

# ─── 7. PyTorch com CUDA (opcional) ──────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    step "GPU NVIDIA detectada — verificando CUDA..."
    CUDA_VER=$(nvidia-smi 2>/dev/null | grep -oE "CUDA Version: [0-9]+" | grep -oE "[0-9]+$" | head -1 || echo "0")
    if [[ "$CUDA_VER" -ge 12 ]]; then
        step "Instalando PyTorch com CUDA $CUDA_VER..."
        "$PIP" install torch --index-url https://download.pytorch.org/whl/cu121 -q
        ok "PyTorch com CUDA 12 instalado (aceleração GPU ativada)"
    elif [[ "$CUDA_VER" -ge 11 ]]; then
        step "Instalando PyTorch com CUDA $CUDA_VER..."
        "$PIP" install torch --index-url https://download.pytorch.org/whl/cu118 -q
        ok "PyTorch com CUDA 11 instalado (aceleração GPU ativada)"
    else
        warn "CUDA $CUDA_VER não suportado — usando CPU"
    fi
else
    warn "GPU NVIDIA não detectada — Whisper usará CPU (transcrição mais lenta)"
fi

# ─── 8. Remover __pycache__ copiado do source ────────────────────────────────
# Garante que o Python compile os .pyc com os caminhos corretos do destino
find "$INSTALL_DIR/alex_transcritor" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ─── 9. Gerar ícone se necessário ────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/assets/icon.png" ]]; then
    step "Gerando ícone da aplicação..."
    if [[ -f "$INSTALL_DIR/scripts/create_icon.py" ]]; then
        "$PYTHON" "$INSTALL_DIR/scripts/create_icon.py" 2>/dev/null && ok "Ícone gerado" \
            || warn "Não foi possível gerar o ícone"
    fi
fi

# ─── 10. Garantir ~/.local/bin no PATH ───────────────────────────────────────
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin não está no PATH — adicionando ao ~/.bashrc e ~/.profile"
    grep -qF 'local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    grep -qF 'local/bin' "$HOME/.profile" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile" 2>/dev/null || true
    ok "PATH atualizado (reabra o terminal para efetivar)"
fi

# ─── 11. Baixar modelo Whisper (opcional) ────────────────────────────────────
echo ""
WHISPER_MODEL_FILE="$HOME/.cache/whisper/small.pt"
if [[ -f "$WHISPER_MODEL_FILE" ]]; then
    ok "Modelo Whisper 'small' já está baixado (~/.cache/whisper/small.pt)"
else
    ask "Baixar o modelo Whisper 'small' agora? (~244 MB, necessário na 1ª transcrição) [s/N]: "
    read -r DOWNLOAD_MODEL
    if [[ "$DOWNLOAD_MODEL" =~ ^[Ss]$ ]]; then
        step "Baixando modelo Whisper small (~244 MB)..."
        "$PYTHON" -c "import whisper; whisper.load_model('small')" && ok "Modelo baixado com sucesso"
    else
        warn "Modelo não baixado — será baixado automaticamente na primeira transcrição"
    fi
fi

# ─── 12. Detectar dispositivo de áudio ───────────────────────────────────────
echo ""
if command -v pactl &>/dev/null; then
    MONITORS=$(pactl list sources short 2>/dev/null | awk '{print $2}' | grep -i "monitor" || true)
    if [[ -n "$MONITORS" ]]; then
        step "Fontes de áudio monitor detectadas:"
        echo "$MONITORS" | while IFS= read -r src; do echo "    • $src"; done
        warn "Configure o dispositivo em: Menu tray → Configurações"
    else
        warn "Nenhuma fonte monitor encontrada. Configure após conectar o dispositivo."
    fi
fi

# ─── 13. Criar launcher ──────────────────────────────────────────────────────
# Criado por último: o app só fica acessível após tudo estar instalado e pronto
step "Criando launcher em $BIN_DIR/$APP_NAME..."
cat > "$BIN_DIR/$APP_NAME" << LAUNCHER
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/main.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/$APP_NAME"
ok "Launcher criado"

# ─── 14. Criar .desktop ──────────────────────────────────────────────────────
# Criado por último: o ícone no menu só aparece quando tudo está pronto
step "Criando entrada no menu de aplicativos..."
cat > "$DESKTOP_DIR/$APP_NAME.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Alex Transcritor
GenericName=Transcritor de Áudio
Comment=Gravação e transcrição de áudio com Whisper AI
Exec=$BIN_DIR/$APP_NAME
Icon=$INSTALL_DIR/assets/icon.png
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=transcrição;audio;whisper;gravação;reconhecimento;fala;
StartupNotify=true
StartupWMClass=alex-transcritor
DESKTOP
chmod +x "$DESKTOP_DIR/$APP_NAME.desktop"
command -v update-desktop-database &>/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
ok "Entrada no menu criada"

# ─── Conclusão ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║    Instalação concluída com sucesso! ✓   ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Como iniciar:${NC}"
echo -e "    • Menu de aplicativos: ${CYAN}Alex Transcritor${NC}"
echo -e "    • Terminal: ${CYAN}alex-transcritor${NC}"
echo ""
echo -e "  ${BOLD}Arquivos instalados em:${NC} ${CYAN}$INSTALL_DIR${NC}"
echo ""
echo -e "  ${YELLOW}IMPORTANTE:${NC} Na primeira execução, acesse"
echo -e "  ${BOLD}Menu tray → Configurações${NC} para selecionar"
echo -e "  o dispositivo de áudio correto."
echo ""
