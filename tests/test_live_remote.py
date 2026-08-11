"""Testes do RemoteLiveTranscriber — motor ao vivo via streaming WebSocket."""

import io
import json
import time

import pytest
import websocket as real_websocket

from alex_transcritor import live_remote
from alex_transcritor.live_remote import RemoteLiveTranscriber


READY = json.dumps({"status": "ready"})


class _FakeWS:
    """Responde o handshake de ``ready`` por padrão, como o servidor real."""

    def __init__(self, incoming=None, ready=READY):
        self.sent_text = []
        self.sent_bytes = []
        self.closed = False
        self.timeouts = []
        self._incoming = ([ready] if ready is not None else []) + list(incoming or [])

    def settimeout(self, t):
        self.timeouts.append(t)

    def send_text(self, s):
        self.sent_text.append(s)

    def send_bytes(self, b):
        if self.closed:
            raise real_websocket.WebSocketConnectionClosedException()
        self.sent_bytes.append(b)

    def recv(self):
        if self._incoming:
            return self._incoming.pop(0)
        if self.closed:
            raise real_websocket.WebSocketConnectionClosedException()
        time.sleep(0.01)  # imita o bloqueio real, sem queimar CPU no teste
        raise real_websocket.WebSocketTimeoutException()

    def close(self):
        self.closed = True


# ── _to_ws_url — pura ────────────────────────────────────────────────────────

def test_to_ws_url_converts_http_and_https():
    assert live_remote._to_ws_url("http://host:8300") == "ws://host:8300"
    assert live_remote._to_ws_url("https://host:8300") == "wss://host:8300"


# ── conexão e envio ───────────────────────────────────────────────────────────

def test_sends_opening_message_and_pcm_chunks(qtbot, monkeypatch):
    fake_ws = _FakeWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    payload = b"\x00" * 100
    transcriber = RemoteLiveTranscriber(
        io.BytesIO(payload), "http://host:8300", "tok", language="pt", model="small",
    )
    transcriber.start()
    assert transcriber.wait(3000)
    assert fake_ws.sent_text == [json.dumps({"language": "pt", "model": "small"})]
    assert b"".join(fake_ws.sent_bytes) == payload
    assert fake_ws.closed


def test_missing_websocket_client_emits_failed(qtbot, monkeypatch):
    monkeypatch.setattr(live_remote, "websocket", None)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b""), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.failed, timeout=2000) as blocker:
        transcriber.start()
    assert "websocket-client" in blocker.args[0]
    transcriber.wait(2000)


def test_connection_failure_emits_failed_without_crashing(qtbot, monkeypatch):
    def _raise(*a, **k):
        raise OSError("conexão recusada")

    monkeypatch.setattr(live_remote.websocket, "create_connection", _raise)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b""), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.failed, timeout=2000) as blocker:
        transcriber.start()
    assert "conectar" in blocker.args[0]
    transcriber.wait(2000)


def test_socket_timeout_is_generous_enough_for_real_sends(qtbot, monkeypatch):
    """Regressão de uso real: settimeout() vale para o socket inteiro, não só
    para o recv() de checagem — 0.1s derrubava a conexão sempre que um envio
    de PCM demorasse mais que isso, fácil de acontecer em qualquer rede real."""
    fake_ws = _FakeWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    transcriber.start()
    assert transcriber.wait(3000)
    assert all(t >= 1.0 for t in fake_ws.timeouts), fake_ws.timeouts


def test_audio_is_sent_without_waiting_for_server_messages(qtbot, monkeypatch):
    """Regressão do bug que deixou o painel mudo em uso real: recv() e send()
    no mesmo loop faziam cada volta esperar o timeout do socket por uma
    mensagem inexistente, enquanto o áudio acumulava e era descartado — quase
    nada chegava ao servidor, que nunca completava uma janela. O envio não
    pode depender da chegada de mensagens."""
    fake_ws = _FakeWS()  # nunca manda segmento nenhum, só o ready
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    payload = b"\x00" * (live_remote.READ_CHUNK_BYTES * 30)
    transcriber = RemoteLiveTranscriber(io.BytesIO(payload), "http://host:8300", "tok")
    transcriber.start()
    assert transcriber.wait(5000), "não terminou a tempo"
    # Sem descarte por backlog: tudo que foi lido do pipe chegou ao socket.
    assert b"".join(fake_ws.sent_bytes) == payload


def test_no_audio_is_sent_before_the_server_is_ready(qtbot, monkeypatch):
    """Áudio mandado enquanto o servidor ainda carrega o modelo seria só
    descartado — a sessão começaria surda."""
    order = []

    class _OrderTrackingWS(_FakeWS):
        def recv(self):
            order.append(("recv", len(self.sent_bytes)))
            return super().recv()

        def send_bytes(self, b):
            order.append(("send", len(b)))
            super().send_bytes(b)

    fake_ws = _OrderTrackingWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    transcriber.start()
    assert transcriber.wait(3000)
    # O primeiro recv (handshake do ready) acontece antes de qualquer envio.
    assert order[0] == ("recv", 0)


def test_error_instead_of_ready_emits_failed(qtbot, monkeypatch):
    fake_ws = _FakeWS(ready=json.dumps({"error": "GPU ocupada"}))
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.failed, timeout=3000) as blocker:
        transcriber.start()
    assert blocker.args[0] == "GPU ocupada"
    transcriber.wait(2000)
    assert fake_ws.sent_bytes == []  # nada de áudio depois de um erro


def test_status_signal_reports_progress_before_streaming(qtbot, monkeypatch):
    fake_ws = _FakeWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.status, timeout=3000) as blocker:
        transcriber.start()
    assert "Conectando" in blocker.args[0]
    transcriber.wait(3000)


def test_stop_before_start_returns_quickly(qtbot, monkeypatch):
    fake_ws = _FakeWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    transcriber.stop()
    transcriber.start()
    assert transcriber.wait(2000)


# ── recebimento de segmentos ────────────────────────────────────────────────────

def test_receives_segment_and_emits_signal(qtbot, monkeypatch):
    payload = json.dumps({"text": "ola", "start_s": 0.0, "end_s": 1.0, "is_final": True})
    fake_ws = _FakeWS(incoming=[payload])
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.segment, timeout=3000) as blocker:
        transcriber.start()
    seg = blocker.args[0]
    assert seg.text == "ola"
    assert seg.start_s == 0.0
    assert seg.end_s == 1.0
    assert seg.is_final is True
    transcriber.wait(2000)


def test_receives_error_message_emits_failed(qtbot, monkeypatch):
    payload = json.dumps({"error": "algo quebrou no servidor"})
    fake_ws = _FakeWS(incoming=[payload])
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    transcriber = RemoteLiveTranscriber(io.BytesIO(b"\x00" * 100), "http://host:8300", "tok")
    with qtbot.waitSignal(transcriber.failed, timeout=3000) as blocker:
        transcriber.start()
    assert blocker.args[0] == "algo quebrou no servidor"
    transcriber.wait(2000)


# ── acúmulo — mesma proteção do motor local ────────────────────────────────────

def test_drops_backlog_when_network_falls_behind(qtbot, monkeypatch):
    """Regressão do mesmo tipo já corrigido no motor local: se a rede cair
    atrás do tempo real, o excesso é descartado em vez de acumulado."""

    class _SlowFakeWS(_FakeWS):
        def send_bytes(self, b):
            time.sleep(0.05)
            super().send_bytes(b)

    fake_ws = _SlowFakeWS()
    monkeypatch.setattr(live_remote.websocket, "create_connection", lambda *a, **k: fake_ws)
    huge_payload = b"\x00" * (live_remote.READ_CHUNK_BYTES * 200)
    transcriber = RemoteLiveTranscriber(io.BytesIO(huge_payload), "http://host:8300", "tok")
    transcriber.start()
    assert transcriber.wait(5000), "não terminou a tempo — parece estar mandando o acúmulo inteiro"
    total_sent = sum(len(b) for b in fake_ws.sent_bytes)
    assert total_sent < len(huge_payload)
