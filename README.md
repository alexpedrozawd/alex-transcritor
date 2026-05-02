# Alex Transcritor

Aplicativo desktop Linux para **gravação e transcrição automática de áudio** usando [OpenAI Whisper](https://github.com/openai/whisper).

---

## O que faz

- Grava o áudio do sistema (monitor PulseAudio/PipeWire) via FFmpeg
- Transcreve automaticamente em português usando Whisper (modelo `small`)
- Interface gráfica minimalista com tema escuro
- Fica na bandeja do sistema (system tray) quando minimizado
- Lembra o último diretório de saída usado
- Detecta automaticamente o dispositivo de áudio disponível

## Requisitos de sistema

| Requisito | Versão mínima |
|---|---|
| Linux (Ubuntu, Debian, Fedora, Arch, etc.) | — |
| Python | 3.10+ |
| FFmpeg | qualquer versão moderna |
| PulseAudio ou PipeWire | com `pactl` disponível |
| Espaço em disco | ~500 MB (venv + modelo Whisper) |

## Instalação rápida

```bash
git clone <repositório> alex-transcritor
cd alex-transcritor
bash install.sh
```

O instalador cuida de tudo: dependências do sistema, ambiente Python, Whisper e integração com o menu de aplicativos.

Consulte o [Manual do Usuário](docs/MANUAL_USUARIO.md) para instruções detalhadas passo a passo.

## Como usar

1. Abra o app pelo menu de aplicativos ou digitando `alex-transcritor` no terminal
2. Na primeira execução: clique com o botão direito no ícone do tray → **Configurações** → selecione o dispositivo de áudio
3. Digite o nome do arquivo e escolha o diretório de saída
4. Clique **Gravar** → quando terminar, clique **Parar**
5. Aguarde a transcrição — os botões **Áudio** e **Texto** aparecerão quando concluída

## Estrutura do projeto

```
alex-transcritor/
├── alex_transcritor/      ← pacote Python principal
│   ├── app.py             ← ponto de entrada e verificação de deps
│   ├── config.py          ← configuração e detecção de áudio
│   ├── constants.py       ← caminhos e constantes
│   ├── worker.py          ← thread de transcrição (Whisper)
│   └── ui/                ← componentes de interface
├── tests/                 ← suite de testes (65 testes, 100% cobertura)
├── assets/                ← ícone da aplicação
├── scripts/               ← utilitários (geração de ícone)
├── docs/                  ← manuais
├── main.py                ← entry point (3 linhas)
├── install.sh             ← instalador
├── uninstall.sh           ← desinstalador
├── requirements.txt       ← dependências de produção
└── requirements-dev.txt   ← dependências de desenvolvimento
```

## Rodando os testes

```bash
# Instalar dependências de desenvolvimento
pip install -r requirements-dev.txt

# Executar testes com cobertura
pytest tests/ --cov --cov-report=term-missing
```

## Desinstalar

```bash
bash uninstall.sh
```

## Licença

Uso pessoal. Projeto de Alexandre Pedroza.
