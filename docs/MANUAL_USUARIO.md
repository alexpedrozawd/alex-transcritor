# Manual do Usuário — Alex Transcritor

Guia completo para instalar, configurar e usar o Alex Transcritor.

---

## O que é

O Alex Transcritor é um aplicativo desktop para Linux que **grava o áudio do seu computador e transcreve automaticamente para texto** usando inteligência artificial (OpenAI Whisper).

Ideal para gravar aulas, reuniões, podcasts ou qualquer áudio que você queira transformar em texto.

---

## Pré-requisitos

Antes de instalar, verifique se seu sistema tem:

- **Linux** (Ubuntu, Debian, Linux Mint, Fedora, Arch, etc.)
- **Python 3.10 ou superior**
- **Conexão com a internet** (para baixar as dependências e o modelo de IA na primeira vez)
- **~500 MB de espaço livre em disco**

Para verificar sua versão do Python:
```
python3 --version
```

---

## Instalação passo a passo

### Passo 1 — Obter os arquivos do projeto

Copie a pasta `alex-transcritor` para o seu computador (via pendrive, download, etc.) e abra um terminal nela.

### Passo 2 — Executar o instalador

No terminal, dentro da pasta do projeto:

```
bash install.sh
```

O instalador irá:

```
╔══════════════════════════════════════════╗
║      Alex Transcritor — Instalador       ║
╚══════════════════════════════════════════╝

[*] Verificando dependências do sistema...
[✓] Python 3.12
[✓] ffmpeg 6.1.1
[✓] PulseAudio/PipeWire (pactl disponível)

[*] Criando diretórios de instalação...
[*] Copiando arquivos do app...
[*] Criando venv...
[*] Instalando PyQt6...
[*] Instalando OpenAI Whisper (pode demorar alguns minutos)...
```

> **Atenção:** A instalação do Whisper pode levar de 5 a 15 minutos dependendo da sua conexão. Aguarde até o final.

### Passo 3 — Baixar o modelo de IA

O instalador verifica automaticamente se o modelo já está baixado:

- **Modelo já existe** → exibe `[✓] Modelo Whisper 'small' já está baixado` e segue em frente
- **Modelo ausente** → pergunta se quer baixar agora:

```
[?] Baixar o modelo Whisper 'small' agora? (~244 MB) [s/N]:
```

Digite **s** para baixar agora (recomendado na primeira instalação). Se escolher não, o modelo será baixado automaticamente na primeira transcrição.

### Passo 4 — Concluído!

```
╔══════════════════════════════════════════╗
║    Instalação concluída com sucesso! ✓   ║
╚══════════════════════════════════════════╝

  Como iniciar:
    • Menu de aplicativos: Alex Transcritor
    • Terminal: alex-transcritor
```

O aplicativo já aparece no **menu de aplicativos** do seu sistema, na categoria **Áudio e Vídeo**.

---

## Primeira configuração — Dispositivo de áudio

Na **primeira vez** que usar o app, você precisa configurar qual dispositivo de áudio será gravado.

### Como configurar

1. Abra o Alex Transcritor
2. Na janela principal, clique no botão **⚙** no canto superior direito
3. Na janela de Configurações, selecione o dispositivo de áudio no menu suspenso:

```
┌─────────────────────────────────────────────┐
│  DISPOSITIVO DE ÁUDIO (MONITOR)             │
│  ┌─────────────────────────────────────┐    │
│  │ alsa_output.usb-headset.monitor   ▼ │    │
│  └─────────────────────────────────────┘    │
│                              [ Salvar ]     │
└─────────────────────────────────────────────┘
```

4. Clique em **Salvar**

> **Dica:** Escolha o dispositivo que corresponde ao seu headset, fone ou saída de áudio. Itens com `.monitor` no nome capturam o áudio que está sendo reproduzido pelo dispositivo.

---

## Como gravar e transcrever

### Interface principal

```
┌──────────────────────────────────────┐
│   ALEX-TRANSCRITOR              [⚙]  │
│──────────────────────────────────────│
│  NOME DO ARQUIVO                     │
│  ┌──────────────────────────────┐    │
│  │ ex: aula-01                  │    │
│  └──────────────────────────────┘    │
│                                      │
│  DIRETÓRIO DE SAÍDA                  │
│  ┌─────────────────────────┐ […]    │
│  │ /home/user/transcricoes │        │
│  └─────────────────────────┘        │
│                                      │
│  [ ⏺ Gravar ]   [ ⏹ Parar ]        │
│                                      │
│        Aguardando...                 │
│                               v2.1.0 │
└──────────────────────────────────────┘
```

### Passo a passo

**1. Defina o nome do arquivo**
Digite um nome para identificar a gravação (ex: `reuniao-segunda`, `aula-01`). Caracteres especiais como `/` são removidos automaticamente.

**2. Escolha o diretório de saída**
Por padrão é `~/transcricoes`. Clique no botão **…** para escolher outra pasta. O app lembra o último diretório usado.

**3. Clique em ⏺ Gravar**
O indicador muda para:
```
🔴  Gravando...
```
O áudio está sendo capturado.

**4. Clique em ⏹ Parar**
O indicador muda para:
```
⏳  Transcrevendo...
```
O Whisper está processando o áudio. Aguarde — pode levar alguns segundos ou minutos dependendo do tamanho da gravação.

**5. Transcrição concluída!**
```
✅  Transcrição concluída!
```
Três botões aparecem:

| Botão | O que abre |
|---|---|
| 🎵 Áudio | O arquivo MP3 gravado |
| 📄 Texto | O arquivo TXT com a transcrição |
| 📋 Ver Log de Erro | Só aparece se houver erro |

---

## Onde ficam os arquivos

Por padrão, os arquivos são salvos em `~/transcricoes/`:

```
~/transcricoes/
├── aula-01.mp3          ← gravação de áudio
├── aula-01.txt          ← transcrição em texto
└── aula-01_erro.txt     ← log de erro (só se houver problema)
```

Você pode mudar o diretório a qualquer momento pelo campo **Diretório de Saída**.

---

## Fechar o aplicativo

Quando você fecha a janela principal, o app **encerra completamente**.

Para abrir novamente, use o menu de aplicativos ou o terminal:
```
alex-transcritor
```

---

## Solução de problemas

### "Nenhum dispositivo de áudio configurado"

O app não encontrou um monitor de áudio configurado.

**Solução:**
1. Certifique-se de que seu headset/fone está conectado
2. Clique em **⚙ Configurações** (canto superior direito) → selecione o dispositivo → Salvar
3. Se a lista estiver vazia, verifique se o PulseAudio ou PipeWire está em execução:
   ```
   pactl list sources short
   ```

---

### "ffmpeg não encontrado"

O FFmpeg não está instalado no sistema.

**Solução:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg
```

---

### Transcrição lenta

O Whisper está rodando em **CPU** (sem GPU). Isso é normal — um áudio de 10 minutos pode levar 2-5 minutos para transcrever.

Para acelerar, se você tem uma GPU NVIDIA, reinstale o PyTorch com suporte CUDA:
```bash
~/.local/share/alex-transcritor/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu121
```

---

### Erro na transcrição — botão "Ver Log de Erro"

Clique em **📋 Ver Log de Erro** para ver a mensagem completa. Causas comuns:

| Mensagem no log | Causa | Solução |
|---|---|---|
| "Binário do Whisper não encontrado" | Whisper não instalado no venv | Execute `bash install.sh` novamente |
| "returncode 1" + texto de erro | Arquivo de áudio corrompido ou muito curto | Grave por pelo menos 2 segundos |
| "Tempo limite excedido" | Gravação muito longa (>1 hora) | Divida em partes menores |

---

### O app não abre / já está aberto

O app detecta se já está rodando. Se tentar abrir uma segunda instância, a janela existente será trazida para o primeiro plano automaticamente.

Se o app travou e não abre mais:
```bash
# Limpar socket órfão
rm -f /tmp/alex-transcritor-instance
alex-transcritor
```

---

### Dependências ausentes ao abrir

Se um aviso aparecer ao iniciar listando dependências ausentes, instale o que estiver faltando:

```bash
# ffmpeg
sudo apt install ffmpeg

# pactl (PulseAudio)
sudo apt install pulseaudio-utils

# ou PipeWire
sudo apt install pipewire-pulse
```

---

## Desinstalar

Para remover completamente o app do seu computador:

```bash
cd alex-transcritor
bash uninstall.sh
```

O desinstalador removerá:
- Os arquivos do app (`~/.local/share/alex-transcritor/`)
- O launcher (`~/.local/bin/alex-transcritor`)
- A entrada no menu de aplicativos
- As configurações (`~/.config/alex-transcritor/`)

**Não serão removidos:** os modelos do Whisper em `~/.cache/whisper/` (~244 MB). Para remover também:
```bash
rm -rf ~/.cache/whisper
```
