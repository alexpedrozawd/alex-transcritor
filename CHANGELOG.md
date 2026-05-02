# Changelog — Alex Transcritor

Registro de todas as alterações aplicadas durante a análise de qualidade, testes e segurança
(versão original → versão 2.0.0).

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
