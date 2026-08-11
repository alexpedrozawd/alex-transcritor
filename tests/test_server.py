import os
import stat
import time

from fastapi.testclient import TestClient

from alex_transcritor import server


TOKEN = "a" * 32


def _fake_whisper(tmp_path):
    script = tmp_path / "whisper"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
source = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[sys.argv.index('--output_dir') + 1])
print('50%|#####|', file=sys.stderr)
(outdir / (source.stem + '.txt')).write_text('texto remoto', encoding='utf-8')
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEX_TRANSCRITOR_TOKEN", TOKEN)
    monkeypatch.setenv("ALEX_TRANSCRITOR_WHISPER_BIN", str(_fake_whisper(tmp_path)))
    monkeypatch.setattr(server, "_free_vram_gb", lambda: 15.0)
    return TestClient(server.create_app())


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_requires_strong_token(monkeypatch):
    monkeypatch.setenv("ALEX_TRANSCRITOR_TOKEN", "curto")
    monkeypatch.setenv("ALEX_TRANSCRITOR_WHISPER_BIN", "/bin/true")
    try:
        server.create_app()
    except RuntimeError as exc:
        assert "32 caracteres" in str(exc)
    else:
        raise AssertionError("token fraco foi aceito")


def test_authentication(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers=_headers("b" * 32)).status_code == 401
        response = client.get("/health", headers=_headers())
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_rejects_invalid_upload(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/v1/jobs",
            headers=_headers(),
            files={"audio": ("payload.exe", b"x")},
        )
        assert response.status_code == 415


def test_rejects_when_queue_is_full(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "MAX_PENDING_JOBS", 0)
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/v1/jobs",
            headers=_headers(),
            data={"enhance": "false"},
            files={"audio": ("amostra.flac", b"fake audio")},
        )
        assert response.status_code == 429


def test_job_end_to_end(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/v1/jobs",
            headers=_headers(),
            data={"model": "turbo", "language": "pt", "enhance": "false"},
            files={"audio": ("amostra.flac", b"fake audio")},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/v1/jobs/{job_id}", headers=_headers()).json()
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        assert job["status"] == "succeeded", job
        result = client.get(f"/v1/jobs/{job_id}/result", headers=_headers())
        assert result.status_code == 200
        assert result.text == "texto remoto"


def test_allowed_source_ip(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEX_TRANSCRITOR_ALLOWED_IP", "100.88.218.16")
    with _client(monkeypatch, tmp_path) as client:
        assert client.get("/health", headers=_headers()).status_code == 403
