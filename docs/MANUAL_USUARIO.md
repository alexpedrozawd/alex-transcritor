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
- **~500 MB no modo servidor**, ou ~4 GB com Whisper local
- Conexão com a internet apenas na instalação

Placa de vídeo NVIDIA é opcional. Sem GPU — ou quando o modelo escolhido não cabe na memória da placa — a transcrição roda na CPU: mais lenta, com a mesma precisão.

Também é possível usar um servidor privado conectado por Tailscale. Nesse modo, o
notebook continua responsável pela gravação, mas o processamento pesado acontece na GPU
do servidor e o texto volta automaticamente para o diretório escolhido.

---

## Instalação

Dentro da pasta do projeto:

```bash
bash install.sh
```

O instalador cuida das dependências do sistema, ambiente Python isolado, ícone no menu
e verificação final. Quando perguntar sobre transcrição local, responda **n** se este
notebook usará exclusivamente o servidor.

O download local do modelo `turbo` (~1,5 GB) só é oferecido quando a engine local é
instalada. No modo servidor, o modelo fica no servidor e não ocupa o notebook.

Ao final:

```
╔══════════════════════════════════════════╗
║    Instalação concluída com sucesso! ✓   ║
╚══════════════════════════════════════════╝
```

---

## Primeiro uso

Abra o app pelo menu de aplicativos (**Alex Transcritor**) ou digitando `alex-transcritor` no terminal.

Para configurar o Nitro 5 para o servidor, execute uma vez dentro do repositório:

```bash
ssh apsrv@100.84.64.122 \
  "sed -n 's/^ALEX_TRANSCRITOR_TOKEN=//p' ~/.config/alex-transcritor/server.env" \
  | python3 configure-remote-client.py --token-stdin
```

O token passa dentro do SSH diretamente para o configurador: não aparece na tela, na
linha de comando nem em arquivo versionado.

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
| **Onde transcrever** | Escolha `Servidor privado via Tailscale` para usar a RX 9070 XT. |
| **Servidor** | No ambiente configurado: `http://100.84.64.122:8300`. |
| **Token** | Cole o token privado fornecido pelo administrador. Ele é armazenado no config `0600`. |
| **Identificar quem falou** | Marca cada trecho do texto final com `Pessoa 1`, `Pessoa 2`... Só funciona no servidor e aumenta o tempo de processamento. Ver [Quem falou](#quem-falou-diarização). |
| **Mostrar transcrição em tempo real** | Abre um painel que mostra o texto durante a gravação. Ver [Transcrição ao vivo](#transcrição-ao-vivo). |
| **Modelo ao vivo** | Só usado quando a transcrição ao vivo roda **neste computador** (modo local). No modo servidor, quem escolhe o modelo é o servidor. |

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

No modo remoto, mantenha o Tailscale conectado até o texto aparecer. Se a conexão cair,
o áudio original continua salvo no notebook; uma nova tentativa pode ser feita depois.

---

## Transcrição ao vivo

Com **Mostrar transcrição em tempo real** marcado, aparece um painel durante a gravação
com o texto sendo transcrito. Serve para acompanhar a reunião, não para substituir o
arquivo final — o texto salvo continua vindo da transcrição completa, que é mais precisa.

**O que esperar, de verdade:** o texto aparece em **blocos, a cada ~2 segundos**, com
mais alguns segundos de atraso. Não é legenda instantânea palavra a palavra como no
Google Meet: o Whisper precisa de alguns segundos de áudio antes de conseguir transcrever
qualquer coisa. Em fala corrida, blocos podem sair fragmentados.

Onde o processamento acontece depende da opção **Onde transcrever**:

| Modo | Onde roda | Observação |
|---|---|---|
| Servidor privado | RX 9070 XT do servidor | Recomendado. O áudio é enviado pela Tailscale enquanto grava |
| Neste computador | CPU local | Precisa do pacote opcional (`requirements-live.txt`). Bem mais lento em hardware modesto |

Enquanto conecta, o painel mostra `Conectando ao servidor...` e depois
`Preparando o modelo no servidor...`. Na **primeira** gravação após uma atualização do
servidor, essa preparação pode demorar mais, porque o modelo é baixado uma vez.

Se algo falhar (pacote ausente, servidor fora do ar, rede caindo), o painel mostra o
motivo e **a gravação continua normalmente** — a transcrição final não é afetada.

---

## Quem falou (diarização)

Com **Identificar quem falou** marcado, o texto final sai separado por locutor:

```
Pessoa 1: bom dia, vamos começar pelo relatório

Pessoa 2: eu atualizei os números ontem à noite
```

Pontos importantes:

- **Só funciona no modo servidor.** No modo local a opção fica desabilitada.
- Os rótulos são **genéricos**. O modelo separa vozes, mas não sabe nomes — `Pessoa 1` é
  simplesmente quem falou primeiro. Renomeie manualmente se quiser.
- **Aumenta o tempo de processamento**, porque é uma segunda passada sobre o áudio.
- Só vale a pena em gravações com mais de uma pessoa. Numa gravação de voz única, todo
  o texto sai como `Pessoa 1`.
- Se a diarização falhar por qualquer motivo, **você recebe a transcrição normal** com um
  aviso, em vez de perder o trabalho.

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

No modo local, o áudio nunca sai do notebook. No modo servidor, ele trafega somente pelo
túnel criptografado do Tailscale até o servidor privado e é apagado do servidor após o
processamento; nenhum áudio é enviado para uma API de nuvem. O arquivo de configuração e
o log de erro são gravados com permissão restrita ao seu usuário.
