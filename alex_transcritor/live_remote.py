"""Transcrição ao vivo processada no servidor remoto, via WebSocket.

Mesma interface pública de ``LiveTranscriber`` (``live.py``) — sinais
``segment``/``failed`` e método ``stop()`` — para que ``main_window.py`` e
``LivePanel`` troquem de motor sem mudar nada em como consomem os sinais.
Em vez de rodar faster-whisper localmente, transmite o PCM bruto por
WebSocket para o servidor (que roda openai-whisper na GPU ROCm) e recebe os
segmentos de volta pela mesma conexão.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import BinaryIO

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import websocket
except ImportError:  # pragma: no cover — exercitado via testes com monkeypatch
    websocket = None

from .live_windowing import WINDOW_BYTES, LiveSegment

READ_CHUNK_BYTES = 4096

#: Mesma lógica de proteção contra acúmulo do motor local (live.py) — numa
#: rede lenta/instável, nunca vale a pena mandar áudio muito atrasado.
#: Derivado da janela, nunca fixo: um teto fixo de 50 deixava só 3 blocos de
#: folga sobre os 47 que uma janela de 6 s ocupa, e descartava áudio bom ao
#: menor engasgo da rede.
MAX_QUEUED_CHUNKS = 3 * (WINDOW_BYTES // READ_CHUNK_BYTES)

CONNECT_TIMEOUT_S = 15.0

#: Timeout do socket durante o streaming. Generoso de propósito: ``recv`` e
#: ``send`` compartilham o mesmo timeout, e o servidor pode ficar sem ler o
#: socket por vários segundos enquanto transcreve uma janela na GPU. Curto
#: demais aqui derruba a conexão no meio de um envio legítimo.
SOCKET_TIMEOUT_S = 30.0

#: Espera pela confirmação de que o modelo terminou de carregar no servidor.
#: A primeira sessão com um modelo ainda não usado inclui o download dos
#: pesos, que pode levar minutos numa conexão lenta.
READY_TIMEOUT_S = 300.0


class RemoteLiveTranscriber(QThread):
    """Lê PCM do stdout do ffmpeg e transmite para o servidor por WebSocket."""

    segment = pyqtSignal(object)  # LiveSegment
    failed = pyqtSignal(str)      # não fatal — a gravação principal segue
    status = pyqtSignal(str)      # aviso passageiro (conectando, preparando modelo...)

    def __init__(
        self,
        stdout: BinaryIO,
        remote_url: str,
        token: str,
        language: str = "pt",
        model: str = "turbo",
        initial_prompt: str = "",
        diarize: bool = False,
    ) -> None:
        super().__init__()
        self._stdout = stdout
        self.remote_url = remote_url
        self.token = token
        self.language = language
        self.model = model
        self.initial_prompt = initial_prompt
        self.diarize = diarize
        self._stopped = False
        self._ws = None
        self._chunks: queue.Queue[bytes | None] = queue.Queue()

    def stop(self) -> None:
        self._stopped = True
        self._chunks.put(None)

    def run(self) -> None:
        if websocket is None:
            self.failed.emit("websocket-client não instalado.")
            return

        # Thread só de leitura, independente do envio pela rede — mesma
        # razão do live.py local: se a leitura esperasse a rede (lenta,
        # instável), o buffer do pipe do SO enche e o ffmpeg trava no
        # write(), travando a gravação inteira, não só a transcrição ao vivo.
        reader = threading.Thread(target=self._read_loop, daemon=True)
        reader.start()

        if self._stopped:
            reader.join(timeout=5)
            return

        self.status.emit("Conectando ao servidor...")
        try:
            self._ws = websocket.create_connection(
                _to_ws_url(self.remote_url) + "/v1/live",
                header=[f"Authorization: Bearer {self.token}"],
                timeout=CONNECT_TIMEOUT_S,
            )
            self._ws.send_text(json.dumps({
                "language": self.language,
                "model": self.model,
                "initial_prompt": self.initial_prompt,
                "diarize": self.diarize,
            }))
            self.status.emit("Preparando o modelo no servidor...")
            self._ws.settimeout(READY_TIMEOUT_S)
            ready = self._await_ready()
            self._ws.settimeout(SOCKET_TIMEOUT_S)
        except Exception as exc:
            self.failed.emit(f"Não foi possível conectar ao servidor: {exc}")
            self.stop()
            self._close_ws()
            reader.join(timeout=5)
            return
        if not ready:
            self.stop()
            self._close_ws()
            reader.join(timeout=5)
            return

        # Recepção em thread própria: ``recv`` e ``send`` no mesmo loop faziam
        # cada volta esperar até o timeout do socket por uma mensagem que
        # ainda não existia, enquanto o áudio se acumulava e era descartado
        # pelo limite de backlog — na prática quase nada era enviado e o
        # servidor nunca completava uma janela. websocket-client usa locks
        # separados para envio (``lock``) e leitura (``readlock``) com
        # ``enable_multithread`` (padrão), então isso é uso previsto.
        receiver = threading.Thread(target=self._receive_loop, daemon=True)
        receiver.start()

        already_failed = False
        while not self._stopped:
            chunk = self._chunks.get()
            if chunk is None:  # EOF do ffmpeg, ou stop() pedindo para sair
                break
            if self._chunks.qsize() > MAX_QUEUED_CHUNKS:
                continue  # rede caiu atrás do tempo real — descarta, não acumula
            try:
                self._ws.send_bytes(chunk)
            except Exception as exc:
                if not already_failed:
                    self.failed.emit(f"Conexão com o servidor perdida: {exc}")
                    already_failed = True
                break

        self._stopped = True
        self._close_ws()  # desbloqueia o recv pendente na thread de recepção
        reader.join(timeout=5)
        receiver.join(timeout=5)

    def _await_ready(self) -> bool:
        """Espera o servidor confirmar que o modelo está carregado.

        Sem isso, todo o áudio capturado durante a carga (que na primeira vez
        inclui o download dos pesos) seria enfileirado e descartado pelo
        limite de backlog, e a sessão começaria surda.
        """
        payload = json.loads(self._ws.recv())
        if "error" in payload:
            self.failed.emit(payload["error"])
            return False
        if payload.get("status") != "ready":
            self.failed.emit("Resposta inesperada do servidor ao iniciar a sessão.")
            return False
        return True

    def _receive_loop(self) -> None:
        """Só recebe segmentos — nunca segura o envio de áudio."""
        while not self._stopped:
            try:
                message = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                return  # socket fechado no encerramento, ou conexão caiu
            if message:
                self._handle_message(message)

    def _handle_message(self, message) -> None:
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return
        if "error" in payload:
            self.failed.emit(payload["error"])
            return
        if "status" in payload:
            return  # o "ready" já foi consumido no handshake
        try:
            segment = LiveSegment(
                text=payload["text"],
                start_s=payload["start_s"],
                end_s=payload["end_s"],
                is_final=payload["is_final"],
                speaker=payload.get("speaker", ""),
            )
        except KeyError:
            return
        self.segment.emit(segment)

    def _read_loop(self) -> None:
        """Só drena o pipe, o mais rápido possível — nunca espera a rede."""
        if self._stdout is None:
            self._chunks.put(None)
            return
        while True:
            try:
                data = self._stdout.read(READ_CHUNK_BYTES)
            except (OSError, ValueError):
                data = None
            if not data:
                self._chunks.put(None)
                return
            self._chunks.put(data)

    def _close_ws(self) -> None:
        # Best-effort: a conexão já pode estar morta.
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # nosec B110
                pass


def _to_ws_url(http_url: str) -> str:
    """``http(s)://host:porta`` -> ``ws(s)://host:porta``."""
    if http_url.startswith("https://"):
        return "wss://" + http_url[len("https://"):]
    if http_url.startswith("http://"):
        return "ws://" + http_url[len("http://"):]
    return http_url
