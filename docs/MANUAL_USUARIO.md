# Manual do Usuário — Alex Transcritor

Guia para instalar, configurar e usar o Alex Transcritor.

---

## O que é

Um aplicativo desktop para Linux que **grava o áudio do seu computador e transcreve automaticamente para texto**, usando o OpenAI Whisper. Tudo roda na sua máquina: nenhum áudio sai do computador, não há chave de API nem mensalidade.

Serve para aulas, reuniões, entrevistas, podcasts — qualquer áudio que você queira em texto.

---

## Pré-requisitos

- **Linux** (Ubuntu, Debian, Mint, Fedora, Arch…)
- **Python 3.10 ou superior** — confira com `python3 --version`
- **ffmpeg** e **ffprobe** (o instalador tenta instalar)
- **PulseAudio ou PipeWire** (com o comando `pactl`)
- **~4 GB de espaço livre** (ambiente Python + modelo de IA)
- Conexão com a internet apenas na instalação

Placa de vídeo NVIDIA é opcional. Sem GPU — ou quando o modelo escolhido não cabe na memória da placa — a transcrição roda na CPU: mais lenta, com a mesma precisão.

---

## Instalação

Dentro da pasta do projeto:

```bash
bash install.sh
```

O instalador cuida de tudo: dependências do sistema, ambiente Python isolado, download do modelo, ícone no menu de aplicativos e uma verificação final para garantir que o app realmente sobe.

Quando ele perguntar se deve baixar o modelo `turbo` (~1,5 GB), responda **s**. Se você deixar para depois, o download acontece sozinho na primeira transcrição — mas aí a primeira gravação demora bem mais.

Ao final:

```
╔══════════════════════════════════════════╗
║    Instalação concluída com sucesso! ✓   ║
╚══════════════════════════════════════════╝
```

---

## Primeiro uso

Abra o app pelo menu de aplicativos (**Alex Transcritor**) ou digitando `alex-transcritor` no terminal.

**Antes da primeira gravação, clique no botão ⚙ no canto superior direito.** Vale conferir três coisas:

### Aba Áudio

| Campo | O que fazer |
|---|---|
| **O que gravar** | `Áudio do sistema` para gravar o que sai pelas caixas/fone. `Microfone` para gravar sua voz. `Sistema + microfone` para reuniões, em que você quer os dois lados. |
| **Dispositivo de saída** | Escolha o `.monitor` correspondente ao aparelho que você usa. Se estiver errado, a gravação sai muda. |
| **Microfone** | Só é usado nos modos `Microfone` e `Sistema + microfone`. |
| **Formato do arquivo** | Deixe em **FLAC**. É sem perda de qualidade e ocupa metade de um WAV. MP3 existe por compatibilidade, mas piora a transcrição. |
| **Corrigir volume baixo** | Deixe marcado. O app mede o nível do áudio e só amplifica quando está mesmo baixo — e sempre numa cópia, sem alterar a gravação salva. |

### Aba Transcrição

| Campo | O que fazer |
|---|---|
| **Modelo** | `turbo` é o padrão e o mais preciso na prática. `small` é bem mais rápido e menos preciso — troque se a espera incomodar mais que os erros. |
| **Idioma** | `Português`, ou `Detectar automaticamente` se você grava em vários idiomas. |
| **Processamento** | Deixe em `Automático`: o app usa a GPU quando o modelo cabe nela e cai para a CPU quando não cabe. |

### Aba Vocabulário — a que mais reduz erro

**Termos que costumam aparecer:** liste nomes próprios e jargões separados por vírgula.

```
Alexandre Pedroza, PipeWire, Kubernetes, Dra. Marcela, ANVISA, faturamento recorrente
```

Esses termos são enviados ao modelo como contexto antes da transcrição, o que aumenta muito a chance de ele escrever "PipeWire" em vez de "pipe lady". Cadastre os nomes das pessoas com quem você mais conversa e os termos da sua área.

**Correções automáticas:** para o erro que insiste em aparecer, escreva uma linha por correção:

```
pipe lady => PipeWire
pedrona => Pedroza
```

São aplicadas ao texto final, sem diferenciar maiúsculas de minúsculas.

---

## Gravando

1. Digite um **nome de arquivo** (se deixar em branco, o app usa data e hora)
2. Confira o **diretório de saída** — o app lembra o último usado
3. Clique em **⏺ Gravar**. O contador mostra o tempo decorrido
4. Clique em **⏹ Parar** quando terminar
5. Acompanhe a barra de progresso da transcrição. Durante essa etapa o mesmo botão vira **✕ Cancelar**
6. Quando terminar, aparecem os botões **🎵 Áudio** e **📄 Texto**

O app **nunca sobrescreve** um arquivo existente: gravar "aula" duas vezes gera `aula.flac` e `aula-2.flac`.

### Quanto tempo demora

Depende do modelo e de onde ele roda. Medido num Intel i5-10300H com GTX 1650:

| Modelo | Onde roda | Tempo para 1 h de áudio |
|---|---|---|
| `small` | GPU de 4 GB | ~20 min |
| `turbo` | CPU (8 threads) | ~1 h 15 min |

Você pode continuar usando o computador enquanto a transcrição roda.

---

## Quando algo dá errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| **"Falha na gravação"** logo ao clicar em Gravar | Dispositivo de áudio inválido | Abra ⚙ → Áudio e escolha outro dispositivo. A mensagem traz o erro do ffmpeg |
| **"A gravação ficou vazia"** | Foi capturada a fonte errada, ou nada tocou | Confira o dispositivo em ⚙ → Áudio |
| **Botão 📋 Ver Log de Erro** aparece | A transcrição falhou | Abra o log: ele traz a mensagem exata do Whisper |
| **Transcrição muito lenta** | Modelo grande rodando em CPU | ⚙ → Transcrição → mude para `small` |
| **Palavras erradas** | Vocabulário não cadastrado | ⚙ → Vocabulário: cadastre os termos e as correções automáticas |
| **App não abre** | Instalação incompleta | Rode `alex-transcritor` no terminal para ver a mensagem de erro |

O áudio continua salvo mesmo quando a transcrição falha — o botão **🎵 Áudio** permanece disponível.

---

## Onde ficam os arquivos

| O quê | Onde |
|---|---|
| Aplicativo e ambiente Python | `~/.local/share/alex-transcritor/` |
| Configurações | `~/.config/alex-transcritor/config.json` (só o seu usuário lê) |
| Modelos de IA | `~/.cache/whisper/` |
| Gravações e transcrições | onde você escolher (padrão `~/transcricoes`) |

---

## Desinstalação

```bash
bash uninstall.sh
```

Remove o aplicativo, o launcher, o ícone do menu e as configurações. Os modelos em `~/.cache/whisper` e as suas gravações **não** são apagados.

---

## Privacidade

O áudio nunca sai da sua máquina. O modelo é baixado uma vez e toda a transcrição acontece localmente. O arquivo de configuração e o log de erro são gravados com permissão restrita ao seu usuário.
