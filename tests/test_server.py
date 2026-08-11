import os
import stat
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alex_transcritor import live_server, server


TOKEN = "a" * 32


def _fake_whisper(tmp_path):
    """Grava .json (com "text"/"segments") quando --output_format é json,
    .txt caso contrário — imita a diferença real do CLI do whisper."""
    script = tmp_path / "whisper"
    script.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
source = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[sys.argv.index('--output_dir') + 1])
fmt = sys.argv[sys.argv.index('--output_format') + 1]
print('50%|#####|', file=sys.stderr)
if fmt == 'json':
    data = {
        'text': 'texto remoto',
        'segments': [
            {'start': 0.0, 'end': 1.0, 'text': 'ola'},
            {'start': 1.0, 'end': 2.0, 'text': 'tudo bem'},
        ],
    }
    (outdir / (source.stem + '.json')).write_text(json.dumps(data), encoding='utf-8')
else:
    (outdir / (source.stem + '.txt')).write_text('texto remoto', encoding='utf-8')
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _client(monkeypatch, tmp_path, hf_token=None):
    monkeypatch.setenv("ALEX_TRANSCRITOR_TOKEN", TOKEN)
    monkeypatch.setenv("ALEX_TRANSCRITOR_WHISPER_BIN", str(_fake_whisper(tmp_path)))
    monkeypatch.setattr(server, "_free_vram_gb", lambda: 15.0)
    if hf_token is None:
        monkeypatch.delenv("ALEX_TRANSCRITOR_HF_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ALEX_TRANSCRITOR_HF_TOKEN", hf_token)
    return TestClient(server.create_app())


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _wait_for_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/v1/jobs/{job_id}", headers=_headers()).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} não terminou a tempo: {job}")


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


# ── Diarização ─────────────────────────────────────────────────────────────────

def _post_diarize_job(client):
    return client.post(
        "/v1/jobs",
        headers=_headers(),
        data={"model": "turbo", "language": "pt", "enhance": "false", "diarize": "true"},
        files={"audio": ("amostra.flac", b"fake audio")},
    )


def test_diarize_without_hf_token_degrades_gracefully(monkeypatch, tmp_path):
    """Sem ALEX_TRANSCRITOR_HF_TOKEN configurado, a diarização não pode
    derrubar a transcrição comum — o job precisa suceder com texto plano."""
    with _client(monkeypatch, tmp_path, hf_token=None) as client:
        job_id = _post_diarize_job(client).json()["id"]
        job = _wait_for_job(client, job_id)
        assert job["status"] == "succeeded", job
        assert job["diarization_note"]
        result = client.get(f"/v1/jobs/{job_id}/result", headers=_headers())
        assert result.text == "texto remoto"


def test_diarize_pipeline_failure_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(
        server.diarize, "run_pipeline",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("GPU sem memória")),
    )
    with _client(monkeypatch, tmp_path, hf_token="hf_" + "x" * 30) as client:
        job_id = _post_diarize_job(client).json()["id"]
        job = _wait_for_job(client, job_id)
        assert job["status"] == "succeeded", job
        assert "GPU sem memória" in job["diarization_note"]
        result = client.get(f"/v1/jobs/{job_id}/result", headers=_headers())
        assert result.text == "texto remoto"


def test_diarize_success_labels_speakers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        server.diarize, "run_pipeline",
        lambda *a, **k: [(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")],
    )
    with _client(monkeypatch, tmp_path, hf_token="hf_" + "x" * 30) as client:
        job_id = _post_diarize_job(client).json()["id"]
        job = _wait_for_job(client, job_id)
        assert job["status"] == "succeeded", job
        assert not job["diarization_note"]
        result = client.get(f"/v1/jobs/{job_id}/result", headers=_headers())
        assert "Pessoa 1: ola" in result.text
        assert "Pessoa 2: tudo bem" in result.text


def test_diarize_defaults_to_false(monkeypatch, tmp_path):
    """Sem o campo 'diarize' no form, o job usa o passe txt normal, sem custo extra."""
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/v1/jobs",
            headers=_headers(),
            data={"enhance": "false"},
            files={"audio": ("amostra.flac", b"fake audio")},
        )
        job = _wait_for_job(client, response.json()["id"])
        assert job["status"] == "succeeded", job
        assert job["diarize"] is False
        result = client.get(f"/v1/jobs/{job['id']}/result", headers=_headers())
        assert result.text == "texto remoto"


# ── Transcrição ao vivo (WebSocket) ─────────────────────────────────────────────

def _live_pcm_window():
    """Uma janela cheia com energia suficiente para não ser tratada como
    silêncio — janela muda é pulada antes de chegar ao modelo."""
    from alex_transcritor.live_windowing import WINDOW_BYTES
    return b"\x00\x10" * (WINDOW_BYTES // 2)  # amplitude 4096 em s16le


def _live_pcm_silence():
    from alex_transcritor.live_windowing import WINDOW_BYTES
    return b"\x00" * WINDOW_BYTES


def test_live_rejects_invalid_token_before_accepting(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/v1/live", headers={"Authorization": "Bearer errado"}
            ) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4401


def test_live_rejects_when_no_vram_free(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        monkeypatch.setattr(server, "_free_vram_gb", lambda: 0.5)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/v1/live", headers=_headers()) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4409


def test_live_transcribes_a_window_and_returns_segment(monkeypatch, tmp_path):
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")
    monkeypatch.setattr(
        live_server, "transcribe_window",
        lambda model, window, language, initial_prompt="": [
            {"start": 0.0, "end": 1.0, "text": "ola mundo"}
        ],
    )
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})
            # O "ready" vem antes de qualquer áudio: o cliente espera por ele
            # para não gravar em cima da carga do modelo.
            assert ws.receive_json() == {"status": "ready"}
            ws.send_bytes(_live_pcm_window())
            message = ws.receive_json()
    assert message == {
        "text": "ola mundo", "start_s": 0.0, "end_s": 1.0, "is_final": True, "speaker": "",
    }


def test_live_skips_silent_windows_without_touching_the_model(monkeypatch, tmp_path):
    """Alimentar silêncio ao Whisper é a origem clássica de alucinação — janela
    muda nem chega ao modelo. Também economiza GPU."""
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")
    chamadas = []

    def _registra(model, window, language, initial_prompt=""):
        chamadas.append(window)
        return [{"start": 0.0, "end": live_server.WINDOW_S / 2, "text": "só a janela com som"}]

    monkeypatch.setattr(live_server, "transcribe_window", _registra)
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})
            assert ws.receive_json() == {"status": "ready"}
            ws.send_bytes(_live_pcm_silence())
            # Só depois de áudio com energia é que vem resposta — prova que a
            # janela silenciosa foi descartada sem inferência.
            ws.send_bytes(_live_pcm_window())
            message = ws.receive_json()
    assert message["text"] == "só a janela com som"
    assert len(chamadas) == 1  # a janela silenciosa não chegou ao modelo


def test_speech_after_initial_silence_keeps_its_beginning(monkeypatch, tmp_path):
    """Regressão: pular uma janela silenciosa não pode marcá-la como janela
    anterior "já emitida" — senão a primeira fala depois do silêncio perde o
    começo, exatamente o caso de uma gravação que começa em silêncio."""
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")
    # Segmento inteiramente dentro da sobreposição: só sobrevive se a janela
    # ainda for tratada como a primeira.
    from alex_transcritor.live_windowing import OVERLAP_S
    inicio = OVERLAP_S / 2
    monkeypatch.setattr(
        live_server, "transcribe_window",
        lambda model, window, language, initial_prompt="": [
            {"start": 0.0, "end": inicio, "text": "bom dia"}
        ],
    )
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})
            assert ws.receive_json() == {"status": "ready"}
            ws.send_bytes(_live_pcm_silence())   # reunião começa em silêncio
            ws.send_bytes(_live_pcm_window())    # e então alguém fala
            message = ws.receive_json()
    assert message["text"] == "bom dia"


def test_live_forwards_the_vocabulary_prompt(monkeypatch, tmp_path):
    """O vocabulário do usuário reduz muito o erro em nomes próprios — o passe
    ao vivo tem que receber o mesmo prompt do passe final."""
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")
    recebido = {}

    def _captura(model, window, language, initial_prompt=""):
        recebido["prompt"] = initial_prompt
        return [{"start": 0.0, "end": 1.0, "text": "ok"}]

    monkeypatch.setattr(live_server, "transcribe_window", _captura)
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny", "initial_prompt": "PipeWire, Kubernetes"})
            assert ws.receive_json() == {"status": "ready"}
            ws.send_bytes(_live_pcm_window())
            ws.receive_json()
    assert recebido["prompt"] == "PipeWire, Kubernetes"


def _mock_live_transcription(monkeypatch, text="alguém falando"):
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")
    monkeypatch.setattr(
        live_server, "transcribe_window",
        lambda model, window, language, initial_prompt="": [
            {"start": 0.0, "end": live_server.WINDOW_S / 2, "text": text}
        ],
    )


def test_live_labels_speakers_when_requested(monkeypatch, tmp_path):
    _mock_live_transcription(monkeypatch)
    monkeypatch.setattr(
        live_server, "diarize_pcm",
        lambda pcm, token: [(0.0, live_server.WINDOW_S, "SPEAKER_00")],
    )
    with _client(monkeypatch, tmp_path, hf_token="hf_" + "x" * 30) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny", "diarize": True})
            assert ws.receive_json() == {"status": "ready"}
            # A diarização roda a cada N janelas — manda o suficiente para
            # fechar esse ciclo.
            for _ in range(live_server.DIARIZE_EVERY_N_WINDOWS):
                ws.send_bytes(_live_pcm_window())
                message = ws.receive_json()
    assert message["speaker"] == "Pessoa 1"


def test_live_without_diarize_flag_never_calls_the_pipeline(monkeypatch, tmp_path):
    _mock_live_transcription(monkeypatch)
    chamadas = []
    monkeypatch.setattr(
        live_server, "diarize_pcm",
        lambda pcm, token: chamadas.append(pcm) or [],
    )
    with _client(monkeypatch, tmp_path, hf_token="hf_" + "x" * 30) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})  # sem diarize
            assert ws.receive_json() == {"status": "ready"}
            for _ in range(live_server.DIARIZE_EVERY_N_WINDOWS):
                ws.send_bytes(_live_pcm_window())
                message = ws.receive_json()
    assert chamadas == []
    assert message["speaker"] == ""


def test_live_diarization_failure_keeps_the_transcription_running(monkeypatch, tmp_path):
    """Rótulo de locutor é um extra: falhar nele não pode calar o painel."""
    _mock_live_transcription(monkeypatch, text="continua transcrevendo")

    def _explode(pcm, token):
        raise RuntimeError("modelo com acesso negado")

    monkeypatch.setattr(live_server, "diarize_pcm", _explode)
    with _client(monkeypatch, tmp_path, hf_token="hf_" + "x" * 30) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny", "diarize": True})
            assert ws.receive_json() == {"status": "ready"}
            textos, erros = [], []
            for _ in range(live_server.DIARIZE_EVERY_N_WINDOWS + 1):
                ws.send_bytes(_live_pcm_window())
                msg = ws.receive_json()
                (erros if "error" in msg else textos).append(msg)
    assert any("acesso negado" in e["error"] for e in erros)
    assert any(t["text"] == "continua transcrevendo" for t in textos)


def test_live_diarize_ignored_without_hf_token(monkeypatch, tmp_path):
    _mock_live_transcription(monkeypatch)
    chamadas = []
    monkeypatch.setattr(
        live_server, "diarize_pcm", lambda pcm, token: chamadas.append(pcm) or [],
    )
    with _client(monkeypatch, tmp_path, hf_token=None) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny", "diarize": True})
            assert ws.receive_json() == {"status": "ready"}
            for _ in range(live_server.DIARIZE_EVERY_N_WINDOWS):
                ws.send_bytes(_live_pcm_window())
                message = ws.receive_json()
    assert chamadas == []          # sem token, nem tenta
    assert message["speaker"] == ""  # e a transcrição segue normal


def test_live_model_load_failure_sends_error_and_closes(monkeypatch, tmp_path):
    def _raise(name):
        raise RuntimeError("GPU sem memória")

    monkeypatch.setattr(live_server, "load_model", _raise)
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})
            message = ws.receive_json()
            assert "GPU sem memória" in message["error"]


def test_live_transcribe_failure_sends_error_but_keeps_session_open(monkeypatch, tmp_path):
    monkeypatch.setattr(live_server, "load_model", lambda name: "fake-model")

    def _raise(model, window, language, initial_prompt=""):
        raise RuntimeError("janela corrompida")

    monkeypatch.setattr(live_server, "transcribe_window", _raise)
    with _client(monkeypatch, tmp_path) as client:
        with client.websocket_connect("/v1/live", headers=_headers()) as ws:
            ws.send_json({"language": "pt", "model": "tiny"})
            assert ws.receive_json() == {"status": "ready"}
            ws.send_bytes(_live_pcm_window())
            message = ws.receive_json()
    assert "janela corrompida" in message["error"]
