# Changelog — Alex Transcritor

Registro das alterações aplicadas durante as auditorias de qualidade, testes e segurança.

## [5.0.0] — 2026-08-11

### Transcrição ao vivo — painel durante a gravação

Texto aparecendo enquanto a reunião acontece, em vez de só depois de parar.

- Painel novo abaixo do status, visível durante a gravação e escondido fora dela.
  Cada trecho recebido é acrescentado e **fica** — a transcrição só cresce.
- **Dois motores**, escolhidos pelo mesmo `transcription_backend` do passe final,
  sem opção nova nas Configurações:
  - **remoto** (o usado na prática): áudio PCM enviado por WebSocket para o servidor,
    que transcreve com `openai-whisper` na RX 9070 XT e devolve os segmentos;
  - **local**: `faster-whisper` em CPU, dependência opcional (`requirements-live.txt`).
- O áudio ao vivo sai como **segunda saída do mesmo processo ffmpeg**
  (`record_command(..., live_pcm=True)`), sem tocar no arquivo gravado. Com duas
  fontes, `asplit` duplica o mix — uma saída de filtro não pode ser consumida duas vezes.
- Opt-in, desligado por padrão. Qualquer falha (pacote ausente, GPU indisponível,
  rede caindo) é reportada no painel e **nunca** interrompe a gravação nem o passe final.
- Handshake de `ready`: o cliente só começa a enviar áudio depois que o servidor
  confirma que o modelo carregou — sem isso, o áudio capturado durante a carga
  (que na primeira vez inclui baixar os pesos) era enfileirado e descartado.

**Latência é limitada por desenho**: o piso é o tamanho da janela (2 s) mais o tempo
de inferência. Não é legenda instantânea palavra a palavra como o Google Meet — Whisper
decodifica em janelas, não token a token.

### Diarização de locutores — quem falou

- Só no **passe final remoto**, via `pyannote.audio`. O passe local e o painel ao vivo
  ficaram de fora de propósito.
- Rótulos genéricos (`Pessoa 1`, `Pessoa 2`...), numerados pela ordem de **primeira
  fala**, não pela numeração interna do pyannote (que é arbitrária).
- Junção por **sobreposição temporal máxima** entre os segmentos do Whisper (que passam
  a sair em `--output_format json`, com timestamps) e os turnos do pyannote. Segmento
  em silêncio entre turnos herda o locutor anterior.
- Opt-in por gravação. **Degrada sem quebrar**: token do Hugging Face ausente, GPU sem
  memória, modelo com acesso negado — qualquer falha mantém a transcrição comum e
  devolve um aviso (`diarization_note`), em vez de derrubar o trabalho inteiro.

### Defeitos corrigidos — todos encontrados testando em uso real

Nenhum destes apareceu na suíte de testes; todos vieram de gravações de verdade no
Acer Nitro 5, com log de terminal capturado.

| Sintoma relatado | Causa real |
|---|---|
| App travava e exigia forçar o fechamento | Leitura do pipe e transcrição no mesmo loop: com a transcrição lenta, o buffer do pipe enchia e o **ffmpeg travava no `write()`** — a gravação inteira parava, não só o painel |
| App fechava sozinho com CPU a 100% | `QThread: Destroyed while thread is still running` — checar `isRunning()` antes de conectar o sinal de limpeza tinha corrida; sem referência viva, o GC coletava o wrapper com a thread ainda rodando |
| App sem resposta por minutos após Parar | Sem teto de acúmulo, a transcrição atrasada nunca alcançava o presente: cada janela processada deixava mais áudio acumulado |
| Painel mudo, sem texto nem erro | `recv()` e `send()` no mesmo loop — cada volta esperava o timeout do socket por uma mensagem inexistente, o áudio era descartado por backlog e o servidor nunca completava uma janela |
| "Conexão com o servidor perdida: timed out" | `settimeout()` vale para o socket inteiro, não só para o `recv()`: 0,1 s cortava envios legítimos de PCM |
| Linhas do painel sumiam em vez de acumular | Heurística de "provisório vs. final" quase nunca marcava nada como final em fala contínua, e o provisório era substituído no lugar |
| Transcrição ao vivo lenta e fragmentada | `beam_size` herdava o padrão 5 do faster-whisper — busca em feixe é inviável para janelas curtas em CPU |
| "Library libcublas.so.12 is not found" | Bibliotecas CUDA não vêm com o driver; agora cai para CPU sozinho em vez de ficar morto |
| Diálogo de Configurações espremido | `setMinimumSize` fixo era anterior aos campos novos; alguns gerenciadores abriam no piso em vez do `sizeHint()` |

Uma tentativa de otimização foi **revertida**: `float16` na GPU piorou a latência em
vez de melhorar na GTX 1650 (Turing, sem Tensor Cores). Voltou para `int8`.

### Decisões de dependência — todas verificadas, não presumidas

- **`pyannote.audio==4.0.7`**, não a linha 3.x: testado, 3.3.2 e 3.4.0 não importam com
  o `torchaudio` atual (usam `torchaudio.AudioMetaData`, removido). A 4.x traz telemetria
  OpenTelemetry **ligada por padrão** (envia dados para `otel.pyannote.ai` a cada uso) —
  por isso `PYANNOTE_METRICS_ENABLED=false` é obrigatório no `server.env`, não opcional.
- **`torchcodec` não carrega neste ROCm** (espera bibliotecas CUDA). Contornado em
  `diarize.py`, que pré-carrega o áudio com `soundfile` em vez de deixar o pyannote
  decodificar o arquivo sozinho.
- **`faster-whisper==1.2.1`**, não 1.0.3: versões antigas fixam `av<13`, sem wheel para
  Python 3.14 — compilar exigiria bibliotecas de desenvolvimento do ffmpeg.
- **O motor ao vivo do servidor é `openai-whisper`, não `faster-whisper`**: o CTranslate2
  por trás do faster-whisper só ganhou suporte ROCm recentemente e o repositório oficial
  da AMD não tem release publicado. O `openai-whisper` já roda validado nessa GPU.
- Instalação do pyannote confirmada segura quanto ao PyTorch ROCm já instalado: nem
  `torch` nem `torchaudio` aparecem na lista de pacotes que o pip baixa.

### Servidor

- Endpoint **`/v1/live`** (WebSocket): frames binários com PCM bruto de entrada,
  mensagens JSON com segmentos de saída. Autenticação checada **antes** do
  `accept()` (`HTTPException` não vira resposta HTTP depois do handshake).
- Recusa a sessão ao vivo quando não há VRAM livre, em vez de competir em silêncio
  com um passe em lote.
- Variáveis novas: `ALEX_TRANSCRITOR_HF_TOKEN`, `PYANNOTE_METRICS_ENABLED`,
  `ALEX_TRANSCRITOR_DIARIZE_TIMEOUT_SECONDS`, `MPLCONFIGDIR`.
- `ReadWritePaths` da unidade systemd ampliado para `~/.cache/huggingface` (download do
  modelo de diarização) e `~/.cache/matplotlib` (dependência transitiva do pyannote).

### Arquitetura

- **`live_windowing.py`** (novo): janelamento e deduplicação por sobreposição, puros —
  sem Qt e sem motor. Reaproveitado pelo cliente e pelo servidor, que não podem depender
  um do outro (o servidor é headless e não pode ganhar PyQt6 só por compartilhar a
  matemática).
- **`live.py`** (motor local), **`live_remote.py`** (cliente WebSocket) e
  **`live_server.py`** (motor no servidor) têm a mesma interface de sinais, então trocar
  de motor não muda nada em `main_window.py` nem no painel.
- Leitura do pipe sempre em thread própria, separada da transcrição/rede: o ffmpeg nunca
  pode ficar esperando um consumidor lento.

### Testes

- **298 testes**, incluindo o endpoint WebSocket (`TestClient`), o algoritmo de junção da
  diarização com dados sintéticos, e regressões dedicadas para cada defeito da tabela acima.
- Verificação de ponta a ponta com **servidor uvicorn real e cliente real**, pipe
  alimentado em tempo real e carga de modelo lenta simulada: 6 janelas enviadas,
  6 segmentos recebidos, zero descarte.

---

## [4.0.0] — 2026-08-10

### Transcrição remota privada

- Cliente desktop pode alternar entre Whisper local e servidor via Tailscale.
- API FastAPI assíncrona com upload limitado, token obrigatório, restrição por IP,
  progresso, cancelamento e resultado em texto.
- Serviço vinculado somente a `100.84.64.122:8300`, aceitando o Nitro 5 em
  `100.88.218.16`; nunca escuta em `0.0.0.0`.
- Fila de uma transcrição por vez e espera por pelo menos 7 GiB livres de VRAM.
- Ambiente Conda próprio com PyTorch ROCm para a RX 9070 XT (`gfx1201`), sem alterar
  ambientes do `ap-ai-studio`.
- Arquivos recebidos ficam em diretório temporário `0700`, com conteúdo `0600`, e são
  removidos após o processamento. Token e configuração permanecem fora do Git.
- Serviço `systemd --user` com limites de memória e hardening; modelo é descarregado
  ao fim de cada trabalho para liberar a GPU compartilhada.

### Testes

- Testes da API cobrem autenticação, restrição de origem, validação de upload e fluxo
  completo com Whisper falso.
- Testes do cliente remoto cobrem polling, publicação, correções e cancelamento.

---

## [3.0.0] — 2026-08-08

Auditoria focada em **precisão de transcrição**, robustez e segurança. Todos os números
abaixo foram medidos executando o código, não estimados.

### Precisão — o problema central

Amostra em português do Brasil (86 palavras) comparada a uma transcrição de referência,
num Intel i5-10300H com GTX 1650:

| Configuração | WER |
|---|---|
| Versão 2.1.0 (`small`, MP3 24 kb/s, sem vocabulário) | 22,1% |
| `small`, FLAC, com vocabulário | 19,8% |
| **3.0.0 (`turbo`, FLAC, com vocabulário)** | **5,8%** |

Erros típicos que sumiram: "Pedrona" → **Pedroza**, "Pipe Lady" → **PipeWire**,
"Wodke"/"Word que" → **worker**, "e missões de adquivo" → **permissões de arquivo**.

| Mudança | Detalhe |
|---|---|
| **Modelo `turbo` como padrão** | Antes fixo em `small`. Selecionável na interface, com a exigência de VRAM de cada opção |
| **Vocabulário do usuário** | Nomes próprios e jargões viram `--initial_prompt`, enviesando a decodificação. Limitado a 700 caracteres (o Whisper aceita ~224 tokens) |
| **Correções automáticas** | Substituições `errado => certo` aplicadas ao texto final |
| **Gravação sem perda** | FLAC 16 kHz mono. O MP3 anterior saía a **24 kb/s** — qualidade de telefone. WAV e MP3 seguem disponíveis |
| **Ganho adaptativo** | O app mede o pico e só amplifica quando há folga real. Em áudio baixo (−24 dBFS) o WER caiu de 23,3% para 12,8%; em áudio já adequado, filtrar **piorava** (19,8% → 24,4%), daí a medição prévia |
| **`condition_on_previous_text=False`** | Evita que o modelo repita a janela anterior ao encontrar silêncio — causa clássica de alucinação |
| **Ganho de pico em vez de `loudnorm`** | Testado: `highpass`+`loudnorm` dava 15,1%; ganho puro, 12,8% |

### Correções de bugs

| ID | Severidade | Problema | Correção |
|----|---|----------|----------|
| B1 | **Alta** | O Whisper captura exceções por arquivo, imprime `Skipping ... due to ...` e **sai com código 0**. O app exibia "✅ Transcrição concluída!" e o botão Texto não abria nada | O worker confere que o `.txt` existe, em vez de confiar no código de retorno |
| B2 | **Alta** | fp16 gera logits NaN nesta GPU e `turbo`/`medium` estouram 4 GB de VRAM — falha total sem saída | Escolha automática de dispositivo por VRAM e **retentativa em CPU** quando a GPU falha |
| B3 | **Alta** | Gravar duas vezes com o mesmo nome apagava áudio e transcrição anteriores | `unique_path()` gera `aula-2`, `aula-3`… |
| B4 | **Alta** | Fechar o app durante a transcrição deixava o Whisper **órfão**, segurando GPU e vários GB de RAM | `WhisperThread.cancel()` mata o processo filho antes de encerrar a thread |
| B5 | **Alta** | ffmpeg com dispositivo inválido morre em silêncio; a interface seguia exibindo "🔴 Gravando..." | Verificação após 1,2 s, com o erro real do ffmpeg na mensagem |
| B6 | **Alta** | Instalador abortava em Python 3.13+ com GPU NVIDIA: reinstalava o torch dos índices cu118/cu121, que não têm wheels para essas versões — com `set -e`, o launcher nunca era criado | Passo removido; o torch do PyPI já traz CUDA. Agora só verifica e informa |
| B7 | Média | Timeout fixo de 1 h matava transcrições longas (em CPU o `turbo` leva ~1,2× a duração) | `max(15 min, duração × 25)` |
| B8 | Média | Trocar o diretório de saída durante a gravação mandava o texto para outro lugar | O destino é derivado do arquivo gravado |
| B9 | Média | Dispositivo salvo que não existe mais fazia o ffmpeg gravar a fonte padrão, em silêncio | `get_monitor()`/`get_mic()` validam contra a lista atual do `pactl` |
| B10 | Média | `save_config` truncava o arquivo antes de escrever: falha no meio perdia todas as configurações | Escrita atômica com arquivo temporário + `os.replace()` |
| B11 | Média | Diretório relativo caía no CWD do launcher; `.` + nome iniciado por `-` gerava argumento que o ffmpeg lia como opção | Diretório resolvido para caminho absoluto |
| B12 | Baixa | Sinais `finished`/`error` sombreavam `QThread.finished` | Renomeados para `succeeded`/`failed` |
| B13 | Baixa | Nome de arquivo sem limite de tamanho | Limitado a 200 caracteres; vazio vira data e hora |
| B14 | Baixa | Rótulo de versão `#2a2a2a` sobre `#111111` — contraste ~1,2:1, ilegível | Paleta de textos secundários clareada |
| B15 | Baixa | Janela de tamanho fixo cortava texto com fontes de acessibilidade | Tamanho mínimo, redimensionável |
| B16 | Baixa | `grep -qF 'local/bin'` casava com qualquer comentário e pulava o ajuste de PATH | Marcador próprio no `.bashrc`/`.profile` |
| B17 | Baixa | `create_icon.py` e `icon.png` duplicados na raiz | Removidos (ficam em `scripts/` e `assets/`) |
| B18 | Baixa | Sem verificação de escrita no diretório de saída | `os.access(W_OK)` antes de gravar |
| B19 | Baixa | `ffprobe` não constava na checagem de dependências | Adicionado |

### Segurança

| Vetor | Situação anterior | Correção |
|---|---|---|
| Socket de instância única | Sem restrição — qualquer conta local podia conectar e manipular a janela | `QLocalServer.SocketOption.UserAccessOption` |
| `config.json` adulterado | Valores repassados sem validação para a linha de comando | Validação de tipo e de domínio; chaves desconhecidas descartadas |
| Log de erro | Permissão padrão (0644), podendo conter caminhos e trechos do áudio | Criado com `0600` |
| Correções do usuário | Texto usado direto em `re.sub` | `re.escape()` no padrão e substituição por callable |
| Arquivo temporário do ffmpeg | Ficava em `/tmp` após falha ou fechamento | Removido em todos os caminhos de saída |
| Injeção de comando | — | Reconfirmado: todos os `subprocess` usam lista de argumentos, `shell=False` |

Bateria adversarial executada: 11 nomes de arquivo hostis (travessia, byte nulo, metacaracteres,
substituição de comando), 13 variações de `config.json` corrompido ou malicioso, 5 nomes de
dispositivo hostis e 50 gravações concorrentes com o mesmo nome — nenhuma falha.
`bandit` sem apontamentos; `pip-audit` sem vulnerabilidades conhecidas.

### Novas funcionalidades

| Funcionalidade | Descrição |
|---|---|
| **Captura de microfone e modo reunião** | Grava áudio do sistema, microfone, ou os dois mixados |
| **Barra de progresso** | Percentual real lido da saída do Whisper, distinguindo download de modelo de transcrição |
| **Cancelar transcrição** | O botão Parar vira Cancelar durante a transcrição |
| **Contador de gravação** | Tempo decorrido em `mm:ss` |
| **Configurações em abas** | Áudio, Transcrição e Vocabulário |
| **Diagnóstico de hardware** | A tela de configurações informa a VRAM detectada e o que isso implica |
| **Verificação pós-instalação** | O instalador confirma que o app carrega antes de criar o atalho no menu |

### Arquitetura

| Módulo | Papel |
|---|---|
| `audio.py` *(novo)* | Comandos do ffmpeg, medição de nível, nomes únicos |
| `hardware.py` *(novo)* | Detecção de GPU via `nvidia-smi`, sem carregar o PyTorch |
| `worker.py` | Reescrito: progresso, cancelamento, fallback de dispositivo, pós-processamento |
| `config.py` | Reescrito: esquema com padrões, validação, escrita atômica |

### Testes

| Antes | Depois |
|---|---|
| 67 testes, 100% excluindo `app.py` | **201 testes, 99% incluindo `app.py`** |

`test_worker.py` deixou de mockar `subprocess`: roda um Whisper falso que reproduz os
comportamentos reais do binário — foi assim que a falha silenciosa (B1) ficou coberta.

### Avaliado e não adotado

**`faster-whisper`** (CTranslate2) faria `turbo` caber em 4 GB de VRAM com int8/float16 e
rodaria 4× mais rápido. Não foi adotado porque o `ctranslate2` 4.8.1 não publica wheel para
**Python 3.14**, que é o único interpretador disponível no sistema alvo. É o próximo salto
natural quando houver wheel — o ponto de extensão é `WhisperThread._run_whisper()`.

---

## [2.1.0] — 2026-05-02

### Remoção do Ícone de Bandeja (System Tray)

| Mudança | Detalhes |
|---|---|
| **Tray removido** | A janela não minimiza mais para a bandeja ao ser fechada; fechar encerra o app (`setQuitOnLastWindowClosed(True)`) |
| **Botão ⚙ Configurações na janela** | Antes acessível via menu do tray; agora disponível permanentemente no canto superior direito da janela principal |
| **Exibição discreta da versão** | Versão atual (`v{__version__}`) exibida no rodapé da janela, à direita, em cor sutil (`#2a2a2a`) |
| **Correção de mensagem** | Aviso de "dispositivo não configurado" em `_start_recording` referenciava "Menu tray → Configurações"; atualizado para "⚙ Configurações (canto superior direito)" |
| **Altura da janela** | Ajustada de 360×365px para 360×385px para acomodar o label de versão |

### Testes

| Arquivo | Mudança |
|---|---|
| `tests/test_main_window.py` | Adicionado `test_version_label_shows_version` |
| `tests/test_main_window.py` | Fixture `window` atualizada: usa `before_close_func=_safe_close` para limpar `recording_process` antes de `qtbot` fechar o widget; sem isso, o `closeEvent` disparava `QMessageBox.question` em modo offscreen e travava após testes que deixavam gravação ativa |
| **Total** | **67** (100% excl. `app.py`) |

---

## [2.0.0] — 2026-05-02

### Arquitetura — Reestruturação em Pacote Python

**Antes:** um único arquivo `main.py` (~485 linhas) com todas as responsabilidades misturadas.

**Depois:** pacote `alex_transcritor/` com separação clara de responsabilidades:

```
alex_transcritor/
├── __init__.py          → versão do pacote
├── constants.py         → INSTALL_DIR, WHISPER_BIN, ICON_PATH, SOCKET_NAME
├── config.py            → toda lógica de persistência (JSON, pactl, dirs)
├── worker.py            → WhisperThread (thread de transcrição)
└── ui/
    ├── styles.py        → constante STYLE (CSS da interface)
    ├── settings_dialog.py → SettingsDialog
    └── main_window.py   → MainWindow (UI principal)
```

`main.py` na raiz tornou-se um thin entry point de 3 linhas.

---

### Correções de Erros e Robustez

| ID | Local | Problema original | Correção aplicada |
|----|-------|-------------------|-------------------|
| E1 | `_start_recording` | `os.makedirs` sem captura de `PermissionError` | Try/except com `QMessageBox.critical` |
| E2 | `_start_recording` | `get_monitor()` retornando `""` → ffmpeg falha silenciosamente; UI exibe "Gravando..." mesmo sem gravar | Validação explícita antes de chamar `Popen`; exibe `QMessageBox.warning` se monitor vazio |
| E3 | `_on_error` | `open(log_path)` sem try/except | Captura `OSError` silenciosamente |
| E4 | `is_already_running` | `QLocalSocket` sem `socket.close()` | Adicionado `socket.close()` após uso |
| E5 | `WhisperThread.run` | Exceção genérica; `FileNotFoundError` não distinguida | Captura específica de `FileNotFoundError` (mensagem "Whisper não encontrado") e `TimeoutExpired` |
| E6 | `_open_file` | Sem try/except em `subprocess.Popen` | Captura `OSError` |

---

### Melhorias de Qualidade de Código

| ID | Problema original | Correção |
|----|-------------------|----------|
| S1 | `MainWindow` com 6 responsabilidades | Responsabilidades extraídas para módulos; UI decomposta em `_make_*` |
| S2 | `WhisperThread` acoplada a variável global `WHISPER_BIN` | Agora recebe `whisper_bin` como parâmetro no construtor |
| A2 | `SettingsDialog` chamava `load_config()` 2x | Carregado uma vez por chamada; código reorganizado |
| L2 | `_build_ui()` com 73 linhas | Decomposta em `_make_title()`, `_make_separator()`, `_make_filename_section()`, `_make_directory_section()`, `_make_controls_section()`, `_make_status_label()`, `_make_file_buttons()` |
| L3 | Diretório de saída padrão hardcoded em `_build_ui` | Lido via `get_last_output_dir()` (persiste entre sessões) |
| L4 | `on_new_connection` aninhada em `__main__` | Extraída para função `_on_new_connection(server, window)` em `app.py` |
| L5 | Falta de type hints nos métodos | Type hints adicionados em todos os métodos públicos e privados |
| P1–P3 | Violações PEP 8 (linhas em branco, ordem de constantes) | Corrigidas pela reestruturação |

---

### Novas Funcionalidades (Sugestões Implementadas)

| Funcionalidade | Descrição |
|---|---|
| **Verificação de dependências na inicialização** | `app.py` verifica `ffmpeg`, `pactl` e `whisper` via `shutil.which` antes de abrir a janela; exibe aviso amigável se algum estiver ausente |
| **Persistência do último diretório usado** | `save_last_output_dir()` salva em `config.json`; `get_last_output_dir()` restaura na próxima sessão |
| **Sanitização de nome de arquivo** | `_sanitize_filename()` remove `/`, `\`, `<>:"|?*` e caracteres de controle do nome digitado pelo usuário |
| **Fechar janela minimiza para tray** | `closeEvent` agora esconde a janela em vez de sair do app; encerramento real apenas pelo tray "Sair" |
| **Timeout na transcrição** | `WhisperThread` define `timeout=3600` (1 hora) para evitar travamento indefinido |
| **Timeout no pactl** | `list_monitor_sources()` define `timeout=5` segundos |

---

### Segurança

| Vetor | Análise | Ação |
|---|---|---|
| Injeção de comando via `subprocess` | Todos os chamados usam lista de argumentos (`shell=False`); nenhum dado do usuário é interpolado no shell | OK — sem alteração necessária |
| Path traversal no nome de arquivo | Nome do usuário passado diretamente para `os.path.join` | **Corrigido** via `_sanitize_filename()` |
| Leitura de JSON | `json.load` sem validação de tipo | **Corrigido**: verifica `isinstance(data, dict)` antes de retornar |
| `install.sh`: variáveis sem aspas | `$PKG_UPDATE` e `$PKG_INSTALL` sem aspas em alguns contextos | **Corrigido**: verificação `[[ -n "$PKG_INSTALL" ]]` antes de executar |
| `install.sh`: `grep -oP` (Perl regex) | Não disponível em BSD/macOS | **Corrigido**: substituído por `grep -oE` (POSIX estendido) |
| Dependências sem pinagem | `pip install openai-whisper` sem versão | **Corrigido**: `requirements.txt` com versões mínimas |
| Bandit scan | 0 issues Medium/High; 0 issues Low após config | **OK** — falsos positivos B404/B603/B607 documentados em `pyproject.toml` |

---

### Testes

| Arquivo | Testes | Cobertura |
|---|---|---|
| `tests/test_config.py` | 19 | 100% |
| `tests/test_worker.py` | 7 | 100% |
| `tests/test_main_window.py` | 30 | 100% |
| `tests/test_settings_dialog.py` | 6 | 100% |
| **Total** | **65** | **100%** (excl. `app.py`) |

Ferramentas: `pytest 9.0.3`, `pytest-qt 4.5.0`, `pytest-mock 3.15.1`, `pytest-cov 7.1.0`

---

---

## [2.0.1] — 2026-05-02

### Correções — Instalador

| Arquivo | Problema | Correção |
|---|---|---|
| `install.sh` | O instalador sempre perguntava se o usuário queria baixar o modelo Whisper, mesmo quando `~/.cache/whisper/small.pt` já existia | Adicionada verificação prévia: se o arquivo do modelo existir, exibe `[✓] Modelo já está baixado` e pula a pergunta |
| `install.sh` | Launcher e `.desktop` eram criados antes do download do modelo e da detecção de áudio — o app ficava acessível pelo menu antes de estar completamente instalado, podendo exibir aviso falso de dependência ausente | Launcher e `.desktop` movidos para o **final** do script (passos 13 e 14), garantindo que o app só apareça no menu após tudo estar pronto |
| `install.sh` | `__pycache__` do diretório fonte era copiado junto com o pacote — arquivos `.pyc` compilados com caminhos do source podiam causar resolução incorreta de `Path(__file__)` | Adicionado `find ... -exec rm -rf {} +` após a cópia para remover o `__pycache__` e forçar recompilação com caminhos corretos do destino |

---

### Arquivos Novos

| Arquivo | Propósito |
|---|---|
| `alex_transcritor/` | Pacote Python principal |
| `assets/icon.png` | Ícone movido de `/` para `assets/` |
| `scripts/create_icon.py` | Script movido de `/` para `scripts/`; corrigido caminho de saída |
| `tests/` | Suite completa de testes |
| `requirements.txt` | Dependências de produção com versões mínimas |
| `requirements-dev.txt` | Dependências de desenvolvimento e teste |
| `pyproject.toml` | Configuração de pytest, coverage e bandit |
| `docs/MANUAL_DESENVOLVEDOR.md` | Manual técnico completo |
| `docs/MANUAL_USUARIO.md` | Manual do usuário final |

---

### Arquivos Modificados

| Arquivo | Principais mudanças |
|---|---|
| `main.py` | Thin entry point (3 linhas); toda lógica movida para pacote |
| `install.sh` | Copia pacote `alex_transcritor/` e `assets/`; corrige `grep -oE`; valida PKG_INSTALL antes de executar; ícone agora em `assets/` |
| `uninstall.sh` | Sem alterações funcionais |
