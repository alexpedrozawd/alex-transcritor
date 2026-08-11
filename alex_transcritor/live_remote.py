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

from .live_windowing import LiveSegment

READ_CHUNK_BYTES = 4096

#: Mesma lógica de proteção contra acúmulo do motor local (live.py) — numa
#: rede lenta/instável, nunca vale a pena mandar áudio muito atrasado.
MAX_QUEUED_CHUNKS = 50

#: Tempo de espera por dado antes de checar se chegou algo do servidor ou se
#: é hora de mandar mais áudio — mantém send/recv intercalados na mesma
#: thread, sem precisar sincronizar acesso concorrente ao socket.
#:
#: ``websocket.WebSocket.settimeout()`` vale para o socket inteiro, não só
#: para o ``recv()`` de checagem — testado em uso real: 0.1s derrubava a
#: conexão sempre que um envio de PCM (``send_bytes``) demorasse mais que
#: isso, o que é fácil de acontecer em qualquer rede real. Não prejudica a
#: responsividade de receber segmentos: a fila de blocos pendentes já dirige
#: o ritmo do loop, esse timeout só importa quando não há nada para mandar.
POLL_TIMEOUT_S = 2.0


class RemoteLiveTranscriber(QThread):
    """Lê PCM do stdout do ffmpeg e transmite para o servidor por WebSocket."""

    segment = pyqtSignal(object)  # LiveSegment
    failed = pyqtSignal(str)      # não fatal — a gravação principal segue

    def __init__(
        self,
        stdout: BinaryIO,
        remote_url: str,
        token: str,
        language: str = "pt",
        model: str = "small",
    ) -> None:
        super().__init__()
        self._stdout = stdout
        self.remote_url = remote_url
        self.token = token
        self.language = language
        self.model = model
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

        try:
            self._ws = websocket.create_connection(
                _to_ws_url(self.remote_url) + "/v1/live",
                header=[f"Authorization: Bearer {self.token}"],
                timeout=15,
            )
            self._ws.settimeout(POLL_TIMEOUT_S)
            self._ws.send_text(json.dumps({"language": self.language, "model": self.model}))
        except Exception as exc:
            self.failed.emit(f"Não foi possível conectar ao servidor: {exc}")
            self.stop()
            reader.join(timeout=5)
            return

        already_failed = False
        while not self._stopped:
            self._drain_incoming_segments()
            try:
                chunk = self._chunks.get(timeout=POLL_TIMEOUT_S)
            except queue.Empty:
                continue
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
        self._close_ws()
        reader.join(timeout=5)

    def _drain_incoming_segments(self) -> None:
        """Lê o que já chegou do servidor sem bloquear — a conexão tem
        timeout curto (``POLL_TIMEOUT_S``), então isso nunca segura o envio
        de áudio por muito tempo."""
        try:
            message = self._ws.recv()
        except websocket.WebSocketTimeoutException:
            return
        except Exception:
            return
        if not message:
            return
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return
        if "error" in payload:
            self.failed.emit(payload["error"])
            return
        self.segment.emit(LiveSegment(
            text=payload["text"],
            start_s=payload["start_s"],
            end_s=payload["end_s"],
            is_final=payload["is_final"],
        ))

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
