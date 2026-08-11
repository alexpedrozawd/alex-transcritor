from pathlib import Path

from alex_transcritor.remote import RemoteWhisperThread


class Response:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload or {}
        self.text = text
        self.status_code = status
        self.ok = status < 400

    def json(self):
        return self._payload


class Session:
    def __init__(self):
        self.polls = 0
        self.deleted = False

    def post(self, *_args, **_kwargs):
        return Response({"id": "job-1"}, status=202)

    def get(self, url, **_kwargs):
        if url.endswith("/result"):
            return Response(text="pipe lady concluído")
        self.polls += 1
        status = "succeeded" if self.polls > 1 else "running"
        return Response({"status": status, "progress": 50, "message": "Processando"})

    def delete(self, *_args, **_kwargs):
        self.deleted = True
        return Response(status=204)

    def close(self):
        pass


def test_remote_pipeline_writes_result(qtbot, tmp_path, monkeypatch):
    audio = tmp_path / "audio.flac"
    audio.write_bytes(b"audio")
    target = tmp_path / "audio.txt"
    thread = RemoteWhisperThread(
        str(audio), str(target), "http://100.84.64.122:8300", "x" * 32,
        "turbo", "pt", replacements=[("pipe lady", "PipeWire")],
    )
    session = Session()
    thread._session = session
    monkeypatch.setattr("alex_transcritor.remote.time.sleep", lambda _seconds: None)
    with qtbot.waitSignal(thread.succeeded, timeout=1000) as signal:
        thread.run()
    assert signal.args == [str(target)]
    assert target.read_text(encoding="utf-8") == "PipeWire concluído"


def test_remote_requires_token(qtbot, tmp_path):
    audio = tmp_path / "audio.flac"
    audio.write_bytes(b"audio")
    thread = RemoteWhisperThread(
        str(audio), str(tmp_path / "audio.txt"), "http://100.84.64.122:8300", "", "turbo", "pt"
    )
    with qtbot.waitSignal(thread.failed, timeout=1000) as signal:
        thread.run()
    assert "Token" in signal.args[0]


def test_rejects_plain_http_outside_tailscale(qtbot, tmp_path):
    audio = tmp_path / "audio.flac"
    audio.write_bytes(b"audio")
    thread = RemoteWhisperThread(
        str(audio), str(tmp_path / "audio.txt"), "http://192.168.1.5:8300",
        "x" * 32, "turbo", "pt",
    )
    with qtbot.waitSignal(thread.failed, timeout=1000) as signal:
        thread.run()
    assert "Tailscale" in signal.args[0]


def test_cancel_notifies_server(tmp_path, monkeypatch):
    thread = RemoteWhisperThread("a", "b", "http://100.84.64.122:8300", "x" * 32, "turbo", "pt")
    called = []
    monkeypatch.setattr("alex_transcritor.remote.requests.delete", lambda *args, **kwargs: called.append(args))
    thread._job_id = "job-1"
    thread.cancel()
    assert called
