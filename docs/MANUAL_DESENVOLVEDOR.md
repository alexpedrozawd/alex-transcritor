# Manual do Desenvolvedor — Alex Transcritor

Documentação técnica completa do código após a versão 2.1.0.

---

## Sumário

1. [Arquitetura](#arquitetura)
2. [Módulos e responsabilidades](#módulos-e-responsabilidades)
3. [Fluxo de dados completo](#fluxo-de-dados-completo)
4. [Sistema de configuração](#sistema-de-configuração)
5. [Thread de transcrição](#thread-de-transcrição)
6. [Interface gráfica](#interface-gráfica)
7. [Ponto de entrada e instância única](#ponto-de-entrada-e-instância-única)
8. [Dependências](#dependências)
9. [Como rodar os testes](#como-rodar-os-testes)
10. [Como estender o projeto](#como-estender-o-projeto)

---

## Arquitetura

```
alex-transcritor/
├── main.py                        ← thin entry point
├── alex_transcritor/
│   ├── __init__.py                ← __version__ = "2.1.0"
│   ├── constants.py               ← caminhos absolutos derivados de __file__
│   ├── config.py                  ← persistência JSON + detecção pactl
│   ├── worker.py                  ← WhisperThread (QThread)
│   └── ui/
│       ├── styles.py              ← string CSS (STYLE)
│       ├── settings_dialog.py     ← QDialog de seleção de dispositivo
│       └── main_window.py        ← QMainWindow principal
├── tests/                         ← pytest (65 testes, 100% cobertura)
├── assets/icon.png                ← ícone PNG 256×256
├── scripts/create_icon.py         ← gerador de ícone (dev)
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml                 ← config pytest/coverage/bandit
```

**Princípio de design:** cada módulo tem uma única responsabilidade. O `config.py` não sabe nada de Qt. O `worker.py` não sabe nada de UI. A `MainWindow` orquestra mas não implementa a lógica de áudio diretamente.

---

## Módulos e Responsabilidades

### `alex_transcritor/constants.py`

Define todos os caminhos absolutos do projeto em um único lugar:

```python
INSTALL_DIR: Path  # diretório raiz onde main.py está instalado
WHISPER_BIN: str   # <INSTALL_DIR>/venv/bin/whisper
ICON_PATH:   str   # <INSTALL_DIR>/assets/icon.png
SOCKET_NAME: str   # "alex-transcritor-instance" (para instância única)
```

**Como funciona:** `INSTALL_DIR = Path(__file__).parent.parent` — dois níveis acima de `constants.py` (que está em `alex_transcritor/`), chegando à raiz do projeto. Isso funciona tanto no ambiente de desenvolvimento quanto no instalado em `~/.local/share/alex-transcritor/`.

---

### `alex_transcritor/config.py`

Responsável por toda persistência e detecção de dispositivos de áudio.

**Variáveis de módulo** (patcháveis em testes):
```python
CONFIG_DIR:          Path  # ~/.config/alex-transcritor/
CONFIG_FILE:         Path  # ~/.config/alex-transcritor/config.json
DEFAULT_OUTPUT_DIR:  str   # ~/transcricoes
```

**Funções:**

#### `load_config() -> dict`
Lê `config.json`. Retorna `{}` se o arquivo não existir, estiver corrompido ou não for um objeto JSON. A verificação `isinstance(data, dict)` rejeita JSON válido mas não-objeto (ex: arrays).

#### `save_config(data: dict) -> None`
Escreve `data` em `config.json`, criando `CONFIG_DIR` se necessário. Sobrescreve todo o arquivo — o chamador é responsável por mesclar dados existentes:
```python
save_config({**load_config(), "nova_chave": "valor"})
```

#### `list_monitor_sources() -> list[str]`
Executa `pactl list sources short` com `timeout=5s` e filtra linhas cujo segundo campo contém `"monitor"`. Retorna `[]` em caso de `FileNotFoundError`, `TimeoutExpired` ou `OSError` (pactl ausente ou sem permissão).

#### `get_monitor() -> str`
Retorna o monitor configurado em `config.json["monitor"]`. Se não existir, chama `list_monitor_sources()`, usa o primeiro resultado e o persiste. Retorna `""` se nenhum monitor for encontrado.

#### `get_last_output_dir() -> str`
Retorna `config.json["last_dir"]` ou `DEFAULT_OUTPUT_DIR` se ausente.

#### `save_last_output_dir(path: str) -> None`
Persiste o diretório de saída usado, preservando outras chaves do config.

---

### `alex_transcritor/worker.py`

#### `class WhisperThread(QThread)`

Thread que executa a transcrição em background para não bloquear a UI.

**Construtor:**
```python
def __init__(self, audio_path: str, output_dir: str, whisper_bin: str)
```
Recebe `whisper_bin` como parâmetro (não captura global) — facilita testes e flexibilidade.

**Sinais:**
- `finished: pyqtSignal()` — emitido quando `returncode == 0`
- `error: pyqtSignal(str)` — emitido com mensagem descritiva em qualquer falha

**Método `run()`:**
Executa `whisper <audio> --language Portuguese --model small --output_format txt --output_dir <dir> --fp16 False` via `subprocess.run` com `timeout=3600` (1 hora). Tratamentos específicos:

| Exceção | Mensagem emitida |
|---|---|
| `FileNotFoundError` | "Binário do Whisper não encontrado: \<path\>" |
| `TimeoutExpired` | "Tempo limite de transcrição excedido (1 hora)." |
| `Exception` genérica | "Erro inesperado na transcrição: \<str(exc)\>" |

**Por que `--fp16 False`?** Whisper tenta usar FP16 por padrão para GPUs. Em CPUs, isso causa aviso e fallback automático. A flag explícita elimina o ruído no stderr.

---

### `alex_transcritor/ui/styles.py`

Contém apenas a constante `STYLE` (string CSS Qt). Separada para não poluir `main_window.py` com ~50 linhas de CSS. Nenhuma lógica.

---

### `alex_transcritor/ui/settings_dialog.py`

#### `class SettingsDialog(QDialog)`

Diálogo simples para seleção de dispositivo de áudio.

**Comportamento:**
1. Chama `list_monitor_sources()` para popular o `QComboBox`
2. Se não houver fontes, exibe `"(nenhuma fonte encontrada)"` e desabilita salvamento
3. Pré-seleciona o monitor salvo no config, se existir
4. `_save()` — persiste a seleção via `save_config({**load_config(), "monitor": source})` e fecha o diálogo

**Constante interna:** `_NO_SOURCE_PLACEHOLDER = "(nenhuma fonte encontrada)"` — usada tanto na exibição quanto na validação do `_save()` para evitar salvar o placeholder acidentalmente.

---

### `alex_transcritor/ui/main_window.py`

#### Função `_sanitize_filename(name: str) -> str`

Remove caracteres problemáticos do nome de arquivo digitado pelo usuário:
- `/`, `\`, `<`, `>`, `:`, `"`, `|`, `?`, `*`
- Caracteres de controle (`\x00`–`\x1f`)
- Remove espaços e pontos das extremidades

Retorna `"gravacao"` se o resultado estiver vazio.

**Segurança:** previne path traversal — sem essa sanitização, `"../etc/passwd"` resultaria em `output_dir + "/../etc/passwd.mp3"`.

#### `class MainWindow(QMainWindow)`

**Construtor:** inicializa atributos de estado (`recording_process`, `whisper_thread`, `audio_path`, `txt_path`, `log_path`) e chama `_build_ui()`.

**Construção da UI:** `_build_ui()` é um orchestrador que chama métodos `_make_*` para cada seção:

| Método | Widget criado | Atributo exposto |
|---|---|---|
| `_make_title()` | `QLabel` + `QPushButton` ⚙ | — |
| `_make_separator()` | `QFrame` | — |
| `_make_filename_section()` | `QLabel` + `QLineEdit` | `self.input_name` |
| `_make_directory_section()` | `QLabel` + `QLineEdit` + `QPushButton` | `self.input_dir` |
| `_make_controls_section()` | 2× `QPushButton` | `self.btn_record`, `self.btn_stop` |
| `_make_status_label()` | `QLabel` | `self.lbl_status` |
| `_make_file_buttons()` | `QWidget` com 3× `QPushButton` | `self.widget_files`, `self.btn_open_audio`, `self.btn_open_text`, `self.btn_open_log` |
| `_make_version_label()` | `QLabel` (rodapé, direita) | — |

**`closeEvent`:** encerra o app normalmente (`event.accept()`). Se houver gravação em andamento, exibe confirmação antes de encerrar.

**`_start_recording()`:**
```
1. Sanitiza nome via _sanitize_filename()
2. Valida se output_dir não está vazio
3. os.makedirs(output_dir) — captura PermissionError e OSError
4. get_monitor() — se vazio, exibe warning e retorna
5. subprocess.Popen(["ffmpeg", "-y", "-f", "pulse", "-i", monitor, ...])
   — captura FileNotFoundError se ffmpeg não instalado
6. Atualiza estado dos botões e lbl_status
```

**`_stop_recording()`:**
```
1. Termina o processo ffmpeg (terminate + wait)
2. Salva o último diretório usado via save_last_output_dir()
3. Cria WhisperThread com whisper_bin=WHISPER_BIN
4. Conecta finished → _on_done, error → _on_error
5. Inicia a thread
```

---

### `alex_transcritor/app.py`

#### `_check_dependencies() -> list[str]`

Usa `shutil.which()` para verificar `ffmpeg` e `pactl` no PATH. Verifica `Path(WHISPER_BIN).exists()` para o executável Whisper. Retorna lista de dependências ausentes.

#### `_is_already_running() -> bool`

Tenta conectar ao servidor `QLocalServer` pelo `SOCKET_NAME`. Se conectar com sucesso, envia `b"show"` para que a instância existente mostre a janela, fecha o socket e retorna `True`.

#### `_on_new_connection(server, window)`

Handler do sinal `server.newConnection`. Lê a mensagem da conexão e chama `window._show_window()`.

#### `main()`

Ponto de entrada principal:
1. Cria `QApplication`
2. Verifica instância única via `_is_already_running()`
3. Chama `_check_dependencies()` — exibe `QMessageBox.Warning` se alguma ausente
4. Cria `QLocalServer` para detectar futuras instâncias
5. Cria e exibe `MainWindow`
6. Conecta `server.newConnection`
7. Inicia o event loop (`app.exec()`)

---

## Fluxo de Dados Completo

```
Usuário clica "Gravar"
    │
    ▼
MainWindow._start_recording()
    ├── _sanitize_filename(input_name) → "nome-do-arquivo"
    ├── os.makedirs(output_dir)
    ├── get_monitor() → "alsa_output.usb-headset.monitor"
    │       └── load_config()["monitor"] ou list_monitor_sources()[0]
    └── subprocess.Popen(["ffmpeg", "-f", "pulse", "-i", monitor, ..., audio_path])
            → grava audio_path.mp3 em tempo real

Usuário clica "Parar"
    │
    ▼
MainWindow._stop_recording()
    ├── recording_process.terminate() + wait()
    ├── save_last_output_dir(output_dir) → config.json["last_dir"]
    └── WhisperThread(audio_path, output_dir, WHISPER_BIN).start()

[thread separada]
WhisperThread.run()
    └── subprocess.run(["whisper", audio_path, "--language", "Portuguese", ...])
            ├── returncode == 0 → emit finished()
            └── returncode != 0 / exceção → emit error(msg)

MainWindow._on_done()                   MainWindow._on_error(msg)
    ├── UI: "✅ Transcrição concluída"       ├── UI: "❌ Erro na transcrição"
    └── mostra btn_open_audio/text          ├── open(log_path).write(msg)
                                            └── mostra btn_open_log
```

---

## Sistema de Configuração

**Arquivo:** `~/.config/alex-transcritor/config.json`

**Estrutura:**
```json
{
  "monitor": "alsa_output.usb-headset-00.analog-stereo.monitor",
  "last_dir": "/home/usuario/transcricoes/aulas"
}
```

| Chave | Tipo | Descrição | Quem escreve | Quem lê |
|---|---|---|---|---|
| `monitor` | string | Nome do source PulseAudio/PipeWire | `get_monitor()`, `SettingsDialog._save()` | `get_monitor()` |
| `last_dir` | string | Último diretório de saída usado | `save_last_output_dir()` | `get_last_output_dir()` |

**Estratégia de merge:** `save_config({**load_config(), "chave": "valor"})` — lê o config atual, mescla a nova chave e sobrescreve. Evita perder chaves não relacionadas.

---

## Thread de Transcrição

`WhisperThread` herda de `QThread`. O método `run()` é executado em um thread C++ gerenciado pelo Qt.

**Atenção para testes:** `coverage.py` não rastreia código executado em C++ threads (QThread). Para 100% de cobertura, os testes chamam `thread.run()` diretamente (síncrono). O comportamento assíncrono real é verificado pelo teste `test_thread_via_start_emits_signal`.

---

## Interface Gráfica

**Framework:** PyQt6 6.x (Qt 6.x)

**Tamanho fixo:** 360×365px. `setFixedSize` impede redimensionamento, adequado para um app utilitário com layout determinístico.

**Tema:** dark manual via CSS string em `styles.py`. Não usa `QDarkStyle` ou similar para evitar dependência extra.

**Sem tray icon:** o app não usa `QSystemTrayIcon`. Fechar a janela encerra o app (`setQuitOnLastWindowClosed(True)` em `app.py`). O botão ⚙ Configurações fica permanentemente visível no canto superior direito da janela.

---

## Ponto de Entrada e Instância Única

O mecanismo de instância única usa `QLocalServer`/`QLocalSocket` (sockets de domínio Unix em `~/.local/share/alex-transcritor-instance`):

1. Instância nova tenta conectar ao socket
2. Se conectar → envia `b"show"` e encerra
3. Se não conectar → cria o servidor e continua a execução
4. Instância existente detecta a conexão via `newConnection`, lê a mensagem e chama `_show_window()`

`QLocalServer.removeServer(SOCKET_NAME)` é chamado antes de `listen()` para limpar sockets órfãos de crashes anteriores.

---

## Dependências

### Produção (`requirements.txt`)

| Pacote | Versão mínima | Propósito |
|---|---|---|
| `PyQt6` | 6.7.0 | Framework GUI |
| `openai-whisper` | 20240930 | Motor de transcrição |

`openai-whisper` instala automaticamente: `torch`, `numpy`, `tiktoken`, `tqdm`, `regex`, `ffmpeg-python`.

**Nota sobre torch:** instalado automaticamente pelo Whisper. Para GPU, o `install.sh` instala versão CUDA específica. Sem GPU, usa CPU (mais lento mas funcional).

### Desenvolvimento (`requirements-dev.txt`)

| Pacote | Propósito |
|---|---|
| `pytest` | Runner de testes |
| `pytest-qt` | Fixtures para testar widgets PyQt6 (`qtbot`) |
| `pytest-mock` | `mocker` fixture para mocking |
| `pytest-cov` | Relatório de cobertura |
| `bandit` | Análise estática de segurança |
| `pip-audit` | Varredura de CVEs em dependências |

### Sistema (binários)

| Binário | Propósito | Instalação |
|---|---|---|
| `ffmpeg` | Captura de áudio via PulseAudio | `sudo apt install ffmpeg` |
| `pactl` | Listar dispositivos de áudio | Parte do `pulseaudio-utils` ou `pipewire-pulse` |
| `xdg-open` | Abrir arquivos com app padrão | Geralmente pré-instalado |

---

## Como Rodar os Testes

```bash
# Ativar o venv (ou usar o venv instalado)
source venv/bin/activate   # ou: source ~/.local/share/alex-transcritor/venv/bin/activate

# Instalar deps de desenvolvimento
pip install -r requirements-dev.txt

# Rodar todos os testes
pytest tests/

# Com cobertura
pytest tests/ --cov --cov-report=term-missing

# Arquivo específico
pytest tests/test_config.py -v

# Análise de segurança
bandit -r alex_transcritor/ -c pyproject.toml

# Verificação de CVEs
pip-audit
```

**Ambiente headless:** `tests/conftest.py` define `QT_QPA_PLATFORM=offscreen` antes de qualquer import PyQt6, permitindo rodar testes sem servidor X/Wayland.

---

## Como Estender o Projeto

### Adicionar novo campo ao config
1. Adicionar função `get_X()` e `save_X()` em `config.py`
2. Escrever testes em `test_config.py` com fixture `isolated_config`
3. Usar em `MainWindow` ou onde aplicável

### Adicionar novo modelo Whisper
1. Adicionar `QComboBox` em `SettingsDialog` com os modelos disponíveis (`tiny`, `base`, `small`, `medium`, `large`)
2. Persistir em `config.json["model"]`
3. Passar como parâmetro ao `WhisperThread` (adicionar `model` ao construtor)
4. Modificar o `subprocess.run` em `worker.py` para usar o modelo

### Adicionar seleção de idioma
Mesmo padrão do modelo: `QComboBox` em `SettingsDialog` → `config.json["language"]` → parâmetro em `WhisperThread`.

### Adicionar indicador de progresso
`WhisperThread` poderia emitir um sinal `progress(int)` se a saída do Whisper for lida linha a linha (`subprocess.Popen` com pipe + leitura incremental). A `MainWindow` conectaria esse sinal a um `QProgressBar`.
