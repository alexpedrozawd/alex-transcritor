# Manual do Desenvolvedor — Alex Transcritor

Documentação técnica do código na versão 3.0.0.

---

## Sumário

1. [Arquitetura](#arquitetura)
2. [Módulos e responsabilidades](#módulos-e-responsabilidades)
3. [Fluxo completo de uma gravação](#fluxo-completo-de-uma-gravação)
4. [Qualidade de transcrição: o que foi medido](#qualidade-de-transcrição-o-que-foi-medido)
5. [Configuração](#configuração)
6. [Thread de transcrição](#thread-de-transcrição)
7. [Escolha de dispositivo](#escolha-de-dispositivo)
8. [Interface gráfica](#interface-gráfica)
9. [Segurança](#segurança)
10. [Testes](#testes)
11. [Como estender](#como-estender)

---

## Arquitetura

```
alex-transcritor/
├── main.py                       ← thin entry point (3 linhas)
├── alex_transcritor/
│   ├── __init__.py               ← __version__
│   ├── constants.py              ← caminhos, formatos, metadados de modelos
│   ├── config.py                 ← config validado + descoberta de dispositivos
│   ├── audio.py                  ← comandos ffmpeg e medição de nível
│   ├── hardware.py               ← detecção de GPU e escolha cuda/cpu
│   ├── worker.py                 ← WhisperThread (QThread)
│   └── ui/
│       ├── styles.py             ← folhas de estilo (STYLE, DIALOG_STYLE)
│       ├── settings_dialog.py    ← QDialog com abas Áudio/Transcrição/Vocabulário
│       └── main_window.py        ← QMainWindow principal
├── tests/                        ← pytest (201 testes, 99% de cobertura)
├── assets/icon.png
├── scripts/create_icon.py
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml                ← config de pytest, coverage e bandit
```

**Princípio de design:** cada módulo tem uma responsabilidade. `config.py`, `audio.py` e `hardware.py` não importam Qt e são testáveis sem display. `worker.py` não sabe nada de UI — comunica-se por sinais. `MainWindow` orquestra, mas não implementa lógica de áudio.

---

## Módulos e Responsabilidades

### `constants.py`

```python
INSTALL_DIR: Path              # raiz da instalação
ICON_PATH: str
SOCKET_NAME: str               # instância única
AUDIO_FORMATS: dict            # extensão → argumentos de codec do ffmpeg
WHISPER_MODELS: tuple          # modelos oferecidos na UI
MODEL_VRAM_GB: dict            # VRAM exigida por modelo
whisper_bin() -> str           # venv → irmão do interpretador → PATH
```

`whisper_bin()` resolve em três níveis para que o app funcione tanto instalado (`~/.local/share/alex-transcritor/venv/bin/whisper`) quanto rodando direto do repositório clonado.

### `audio.py`

Constrói comandos do ffmpeg; não executa gravação.

```python
record_command(output_path, monitor, mic, audio_format) -> list[str]
gain_command(source, target, gain_db) -> list[str]
peak_db(path) -> float | None          # via volumedetect
needed_gain_db(path) -> float          # 0 quando não compensa amplificar
probe_duration(path) -> float
unique_path(dir, stem, suffix) -> Path # nunca sobrescreve
```

Informar `monitor` e `mic` juntos gera um `-filter_complex amix=...`, misturando as duas fontes numa faixa só.

### `hardware.py`

```python
gpu_vram_gb() -> float                       # via nvidia-smi, sem importar torch
pick_device(model, preference="auto") -> str # "cuda" ou "cpu"
```

Consultar `nvidia-smi` em vez de `torch.cuda` evita carregar o PyTorch (segundos e centenas de MB) só para decidir onde rodar.

---

## Fluxo completo de uma gravação

```
Usuário clica ⏺ Gravar
  → resolve o diretório de saída para caminho absoluto
  → valida permissão de escrita (os.access W_OK)
  → get_monitor()/get_mic() validam o dispositivo contra o pactl atual
  → unique_path() escolhe um nome que não sobrescreve nada
  → Popen(record_command(...)) com stderr num arquivo temporário
  → QTimer 1,2 s: confirma que o ffmpeg não morreu
  → QTimer 1 s: atualiza o contador de tempo

Usuário clica ⏹ Parar
  → SIGTERM no ffmpeg, wait(10 s), SIGKILL se preciso
  → salva o diretório derivado do arquivo gravado
  → WhisperThread.start()
       ├─ probe_duration() → define o timeout
       ├─ needed_gain_db() → amplifica só se o áudio estiver baixo
       ├─ pick_device() → cuda ou cpu
       ├─ whisper ... --output_dir <temp>
       │    lê stderr com select(), emite progress(%)
       ├─ se falhou em cuda → repete em cpu
       ├─ confere que o .txt existe de fato
       ├─ aplica as correções do usuário
       └─ move para txt_path → succeeded(caminho)
```

Todo o trabalho intermediário acontece num `TemporaryDirectory`. O Whisper nomeia a saída a partir do arquivo de entrada — como a entrada pode ser uma cópia normalizada, o resultado é renomeado no final para o nome que o usuário escolheu.

---

## Qualidade de transcrição: o que foi medido

Amostra em português do Brasil (86 palavras), comparada a uma transcrição de referência, num Intel i5-10300H com GTX 1650 (3,64 GiB utilizáveis):

| Configuração | WER |
|---|---|
| `small`, MP3 24 kb/s, sem vocabulário (versão 2.1.0) | 22,1% |
| `small`, FLAC, com vocabulário | 19,8% |
| `turbo`, FLAC, com vocabulário | **5,8%** |

Sobre áudio baixo (pico −24 dBFS):

| Configuração | WER |
|---|---|
| Sem tratamento | 23,3% |
| `highpass` + `loudnorm` | 15,1% |
| **Ganho de pico puro** | **12,8%** |

E, sobre áudio já em nível adequado (pico −2 dBFS), aplicar filtro **piorou**: 19,8% → 24,4%. Daí `needed_gain_db()` medir antes e devolver zero quando não há folga real.

### Restrições descobertas rodando o código

- **fp16 gera logits NaN** nesta GPU. O Whisper engole a exceção, imprime `Skipping ... due to ValueError` e **sai com código 0** sem gerar arquivo. Por isso `--fp16 False` é fixo e o worker confere a existência do `.txt` em vez de confiar no código de retorno.
- **A implementação de referência mantém os pesos em float32** mesmo com `--fp16 True`. `turbo` (809 M parâmetros) e `medium` (769 M) estouram os 3,64 GiB da GTX 1650; `small` cabe. É o que `MODEL_VRAM_GB` codifica.
- **`faster-whisper` seria o próximo salto** (int8/float16 fazem `turbo` caber em 4 GB, 4× mais rápido), mas o `ctranslate2` 4.8.1 não publica wheel para Python 3.14 — inviável enquanto a distribuição só oferecer esse interpretador.

---

## Configuração

`~/.config/alex-transcritor/config.json`, diretório `0700`, arquivo `0600`.

```python
DEFAULTS = {
    "monitor": "", "mic": "", "source_mode": "system",
    "last_dir": "", "model": "turbo", "language": "pt",
    "audio_format": "flac", "enhance_audio": True,
    "vocabulary": "", "replacements": "", "device": "auto",
}
```

`load_config()` nunca confia no disco: chaves desconhecidas são descartadas, valores com tipo divergente voltam ao padrão e campos enumerados (`model`, `device`, `audio_format`, `source_mode`) são validados contra o domínio permitido. Um `config.json` corrompido ou adulterado degrada para os padrões em vez de propagar valor arbitrário para a linha de comando.

`save_config()` grava em arquivo temporário no mesmo diretório e faz `os.replace()`. Uma falha no meio da escrita preserva o config anterior — antes, o `O_TRUNC` zerava o arquivo antes de escrever.

`get_monitor()`/`get_mic()` validam o dispositivo salvo contra a lista atual do `pactl`. Um dispositivo que sumiu é substituído pelo primeiro disponível: sem isso o ffmpeg cai silenciosamente na fonte padrão e grava a coisa errada.

---

## Thread de transcrição

```python
class WhisperThread(QThread):
    succeeded = pyqtSignal(str)      # caminho do .txt
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)  # percentual, rótulo
```

Os sinais **não** se chamam `finished`/`error`: `finished` sombrearia o sinal homônimo que o `QThread` emite por conta própria.

**Progresso.** O Whisper escreve a barra do tqdm em stderr, sobrescrevendo a linha com `\r`. O worker lê o stream com `select()` (timeout de 0,5 s), extrai o último `NN%|` e distingue download de modelo (`iB/s`) de transcrição (`frames/s`). O `select()` também garante que o cancelamento e o timeout sejam avaliados mesmo quando o processo fica mudo.

**Cancelamento.** `cancel()` define `_cancelled` e mata o processo filho (`terminate`, `wait(5 s)`, `kill`). `QThread.terminate()` sozinho matava apenas a thread Python e deixava o Whisper rodando órfão, segurando GPU e vários GB de RAM.

**Timeout.** `max(900 s, duração × 25)`. O teto fixo de uma hora interrompia gravações longas: em CPU o `turbo` roda perto de 1,2× tempo real.

**Fallback.** Falha com `device == "cuda"` dispara uma segunda tentativa em CPU. Cobre tanto OOM de VRAM quanto NaN em fp16.

---

## Escolha de dispositivo

| `device` no config | Comportamento |
|---|---|
| `auto` (padrão) | `cuda` se a VRAM comportar `MODEL_VRAM_GB[modelo] × 1,15`; senão `cpu` |
| `cuda` | força GPU (com fallback automático para CPU em caso de falha) |
| `cpu` | força CPU |

---

## Interface gráfica

`MainWindow` é montada por métodos `_make_*`, cada um devolvendo um widget ou layout. A janela tem tamanho mínimo em vez de fixo — com fontes de acessibilidade o layout fixo cortava texto.

O botão ⏹ acumula dois papéis: **Parar** durante a gravação e **✕ Cancelar** durante a transcrição (`_stop_clicked` despacha conforme o estado).

`SettingsDialog` tem três abas e grava tudo de uma vez em `_save()`. Cada `QComboBox` guarda o valor de config em `userData`, separando rótulo exibido de valor persistido.

---

## Segurança

| Vetor | Tratamento |
|---|---|
| Injeção de comando | Todo `subprocess` recebe lista de argumentos, nunca `shell=True`. Nome de dispositivo hostil vira argumento isolado |
| Travessia de caminho | `_sanitize_filename()` remove separadores, caracteres de controle e limita a 200 caracteres; o diretório é resolvido para absoluto |
| Config adulterado | Validação de tipo e de domínio em `load_config()` |
| Corrupção do config | Escrita atômica com `os.replace()` |
| Permissões | `config.json` e o log de erro em `0600`; diretório de config em `0700` |
| Socket de instância única | `QLocalServer.SocketOption.UserAccessOption` — sem isso qualquer conta local conecta |
| Prompt de vocabulário | Limitado a 700 caracteres (o Whisper aceita ~224 tokens) |
| Correções do usuário | `re.escape()` no padrão e substituição por callable — nada é interpretado como regex |

Verificação: `bandit` sem apontamentos; `pip-audit` sem vulnerabilidades conhecidas.

---

## Testes

```bash
pytest tests/ --cov --cov-report=term-missing
```

| Arquivo | Foco |
|---|---|
| `test_config.py` | validação, atomicidade, permissões, vocabulário |
| `test_audio.py` | montagem de comandos, medição de nível, nomes únicos |
| `test_constants.py` | resolução de `whisper_bin()` (venv → irmão do interpretador → PATH) |
| `test_hardware.py` | detecção de GPU e escolha de dispositivo |
| `test_worker.py` | pipeline completo com um Whisper falso |
| `test_main_window.py` | estados da UI, validações, encerramento |
| `test_settings_dialog.py` | carga e persistência das três abas |
| `test_app.py` | dependências, instância única, `main()` |

`test_worker.py` não mocka `subprocess`: roda um script Python que imita o binário real — barra de progresso em stderr, saída nomeada pelo arquivo de entrada e o código de retorno 0 mesmo sem transcrever. Foi assim que o modo de falha silenciosa ficou coberto.

`conftest.py` define `QT_QPA_PLATFORM=offscreen` antes de qualquer import do PyQt6, o que permite testar até o `main()`.

---

## Como estender

**Novo formato de áudio:** adicione a entrada em `AUDIO_FORMATS` (`constants.py`) e o rótulo em `FORMAT_LABELS` (`settings_dialog.py`).

**Novo modelo:** acrescente a `WHISPER_MODELS`, a `MODEL_VRAM_GB` e a `MODEL_LABELS`.

**Outro formato de saída (SRT/VTT):** `_run_whisper()` passa `--output_format txt`; aceitar uma lista exige ajustar também o `glob("*.txt")` e o `_publish()`.

**Trocar a engine (faster-whisper):** o ponto de extensão é `WhisperThread._run_whisper()`. A interface de sinais e o restante do fluxo permanecem válidos.
