"""API privada para transcrição acelerada no servidor ROCm."""

from __future__ import annotations

import asyncio
import json
import os
import re
import select
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import PlainTextResponse

from . import __version__, audio, diarize, live_server
from .constants import WHISPER_MODELS

MAX_UPLOAD_BYTES = int(os.environ.get("ALEX_TRANSCRITOR_MAX_UPLOAD_BYTES", 2 * 1024**3))
JOB_TTL_SECONDS = int(os.environ.get("ALEX_TRANSCRITOR_JOB_TTL_SECONDS", 24 * 3600))
MIN_FREE_VRAM_GB = float(os.environ.get("ALEX_TRANSCRITOR_MIN_FREE_VRAM_GB", "7"))
GPU_WAIT_SECONDS = int(os.environ.get("ALEX_TRANSCRITOR_GPU_WAIT_SECONDS", 3600))
MAX_PENDING_JOBS = int(os.environ.get("ALEX_TRANSCRITOR_MAX_PENDING_JOBS", 8))
MAX_STORED_JOBS = int(os.environ.get("ALEX_TRANSCRITOR_MAX_STORED_JOBS", 100))
# pyannote não expõe progresso incremental como o stderr do whisper CLI, então
# não dá pra reaproveitar o loop de PROGRESS_RE — um teto simples é suficiente.
DIARIZE_TIMEOUT_SECONDS = int(os.environ.get("ALEX_TRANSCRITOR_DIARIZE_TIMEOUT_SECONDS", 1800))
ALLOWED_SUFFIXES = {".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}
PROGRESS_RE = re.compile(rb"(\d{1,3})%\|")


@dataclass
class Job:
    id: str
    audio_path: str
    workdir: str
    model: str
    language: str
    initial_prompt: str
    enhance: bool
    diarize: bool = False
    status: str = "queued"
    progress: int = 0
    message: str = "Na fila do servidor..."
    error: str = ""
    result: str = ""
    diarization_note: str = ""
    created_at: float = field(default_factory=time.time)
    process: subprocess.Popen | None = field(default=None, repr=False)
    cancelled: bool = False

    def public(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "language": self.language,
            "enhance": self.enhance,
            "diarize": self.diarize,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "diarization_note": self.diarization_note,
            "created_at": self.created_at,
        }


class JobManager:
    # "" significa "sem token configurado", não é uma senha embutida.
    def __init__(self, whisper_bin: str, hf_token: str = "") -> None:  # nosec B107
        self.whisper_bin = whisper_bin
        self.hf_token = hf_token
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcription")
        # Executor próprio para a diarização: permite aplicar timeout via
        # Future.result(timeout=...), já que o pyannote não tem um ponto de
        # verificação periódico como o stderr do whisper.
        self._diarize_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diarization")

    def add(self, job: Job) -> None:
        with self.lock:
            self._purge()
            active = sum(item.status in ("queued", "running") for item in self.jobs.values())
            if active >= MAX_PENDING_JOBS:
                raise OverflowError("Fila de transcrição cheia.")
            self.jobs[job.id] = job
        self.executor.submit(self._process, job)

    def has_capacity(self) -> bool:
        with self.lock:
            active = sum(item.status in ("queued", "running") for item in self.jobs.values())
            return active < MAX_PENDING_JOBS

    def get(self, job_id: str) -> Job:
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def cancel(self, job: Job) -> None:
        job.cancelled = True
        process = job.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except OSError:
                pass
        if job.status in ("queued", "running"):
            job.status = "cancelled"
            job.message = "Transcrição cancelada."

    def _purge(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        expired = [key for key, job in self.jobs.items() if job.created_at < cutoff]
        for key in expired:
            job = self.jobs.pop(key)
            shutil.rmtree(job.workdir, ignore_errors=True)
        terminal = sorted(
            (job for job in self.jobs.values() if job.status not in ("queued", "running")),
            key=lambda job: job.created_at,
        )
        for job in terminal[:max(0, len(self.jobs) - MAX_STORED_JOBS + 1)]:
            self.jobs.pop(job.id, None)

    def _process(self, job: Job) -> None:
        try:
            if job.cancelled:
                return
            job.status = "running"
            self._wait_for_gpu(job)
            if job.cancelled:
                return
            source = self._prepare_source(job)
            produced = self._run_whisper(job, source)
            if job.cancelled:
                return
            if job.diarize:
                try:
                    job.message = "Identificando participantes..."
                    job.result = self._run_diarization_and_merge(job, source, produced)
                except Exception as exc:
                    # A diarização é um extra opcional: falhar nela não pode
                    # transformar uma transcrição boa num job com falha.
                    job.result = self._plain_text_from_whisper_json(produced)
                    job.diarization_note = f"Diarização indisponível: {exc}"
            else:
                job.result = produced.read_text(encoding="utf-8")
            job.progress = 100
            job.status = "succeeded"
            job.message = "Transcrição concluída no servidor."
        except Exception as exc:
            if not job.cancelled:
                job.status = "failed"
                job.error = str(exc)
                job.message = "Falha na transcrição no servidor."
        finally:
            job.process = None
            shutil.rmtree(job.workdir, ignore_errors=True)

    def _wait_for_gpu(self, job: Job) -> None:
        deadline = time.monotonic() + GPU_WAIT_SECONDS
        while _free_vram_gb() < MIN_FREE_VRAM_GB:
            if job.cancelled:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("GPU permaneceu ocupada além do limite de espera.")
            job.message = "Aguardando a GPU do servidor ficar disponível..."
            time.sleep(5)

    def _prepare_source(self, job: Job) -> str:
        if not job.enhance:
            return job.audio_path
        job.message = "Analisando o nível do áudio..."
        gain = audio.needed_gain_db(job.audio_path)
        if gain <= 0:
            return job.audio_path
        job.message = f"Normalizando volume (+{gain:g} dB)..."
        target = str(Path(job.workdir) / "entrada.flac")
        result = subprocess.run(
            audio.gain_command(job.audio_path, target, gain),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        return target if result.returncode == 0 and Path(target).exists() else job.audio_path

    def _run_whisper(self, job: Job, source: str) -> Path:
        outdir = Path(job.workdir) / "output"
        outdir.mkdir()
        # json quando diarizando: precisa dos timestamps por segmento
        # (campo "segments") para casar a fala com os turnos do pyannote.
        output_format = "json" if job.diarize else "txt"
        cmd = [
            self.whisper_bin,
            source,
            "--model", job.model,
            "--output_format", output_format,
            "--output_dir", str(outdir),
            "--device", "cuda",
            "--fp16", "True",
            "--beam_size", "5",
            "--temperature", "0",
            "--condition_on_previous_text", "False",
            "--verbose", "False",
        ]
        if job.language and job.language != "auto":
            cmd += ["--language", job.language]
        if job.initial_prompt:
            cmd += ["--initial_prompt", job.initial_prompt]

        duration = audio.probe_duration(source)
        timeout = max(900, duration * 25)
        deadline = time.monotonic() + timeout
        tail = b""
        job.message = f"Transcrevendo ({job.model} · RX 9070 XT)..."
        job.process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL
        )
        if job.process.stderr is None:
            raise RuntimeError("Não foi possível capturar a saída do Whisper.")
        while True:
            if job.cancelled:
                raise RuntimeError("Transcrição cancelada.")
            if time.monotonic() > deadline:
                self.cancel(job)
                raise RuntimeError(f"Tempo limite excedido ({int(timeout / 60)} min).")
            ready, _, _ = select.select([job.process.stderr], [], [], 0.5)
            if ready:
                chunk = job.process.stderr.read1(4096)
                if chunk:
                    tail = (tail + chunk)[-8000:]
                    matches = PROGRESS_RE.findall(chunk)
                    if matches:
                        job.progress = min(100, int(matches[-1]))
                        job.message = (
                            "Baixando o modelo Whisper..." if b"iB/s" in chunk
                            else f"Transcrevendo ({job.model} · RX 9070 XT)..."
                        )
            if job.process.poll() is not None:
                break
        returncode = job.process.wait()
        produced = sorted(outdir.glob(f"*.{output_format}"))
        if returncode != 0 or not produced:
            detail = tail.decode("utf-8", "replace").strip()[-4000:]
            raise RuntimeError(detail or f"Whisper terminou com código {returncode} sem resultado.")
        return produced[0]

    @staticmethod
    def _plain_text_from_whisper_json(path: Path) -> str:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["text"]

    def _run_diarization_and_merge(self, job: Job, source: str, whisper_json_path: Path) -> str:
        if not self.hf_token:
            raise RuntimeError("ALEX_TRANSCRITOR_HF_TOKEN não configurado no servidor.")
        self._wait_for_gpu(job)
        if job.cancelled:
            raise RuntimeError("Transcrição cancelada.")
        whisper_data = json.loads(whisper_json_path.read_text(encoding="utf-8"))
        future = self._diarize_executor.submit(diarize.run_pipeline, source, self.hf_token)
        turns = future.result(timeout=DIARIZE_TIMEOUT_SECONDS)
        return diarize.merge_with_transcript(whisper_data["segments"], turns)


def _ip_allowed(client_host: str | None, allowed_ip: str) -> bool:
    return not allowed_ip or client_host == allowed_ip


def _token_valid(headers, token: str) -> bool:
    supplied = headers.get("Authorization", "")
    return secrets.compare_digest(supplied, f"Bearer {token}")


def _free_vram_gb() -> float:
    for device in sorted(Path("/sys/class/drm").glob("card*/device")):
        try:
            if (device / "vendor").read_text().strip().lower() != "0x1002":
                continue
            total = int((device / "mem_info_vram_total").read_text())
            used = int((device / "mem_info_vram_used").read_text())
            return (total - used) / 1024**3
        except (OSError, ValueError):
            continue
    return 0.0


def create_app() -> FastAPI:
    token = os.environ.get("ALEX_TRANSCRITOR_TOKEN", "")
    allowed_ip = os.environ.get("ALEX_TRANSCRITOR_ALLOWED_IP", "")
    whisper_bin = os.environ.get("ALEX_TRANSCRITOR_WHISPER_BIN") or shutil.which("whisper") or ""
    # Sem validação obrigatória: diarização é opcional e minoritária — um
    # token do Hugging Face ausente não pode derrubar a transcrição comum,
    # que é o uso principal do servidor. Ver JobManager._run_diarization_and_merge.
    hf_token = os.environ.get("ALEX_TRANSCRITOR_HF_TOKEN", "")
    if not token or len(token) < 32:
        raise RuntimeError("ALEX_TRANSCRITOR_TOKEN deve ter pelo menos 32 caracteres.")
    if not whisper_bin or not Path(whisper_bin).exists():
        raise RuntimeError("Binário Whisper não encontrado.")

    manager = JobManager(whisper_bin, hf_token=hf_token)
    app = FastAPI(title="Alex Transcritor Server", version=__version__, docs_url=None, redoc_url=None)

    def authenticate(request: Request) -> None:
        host = request.client.host if request.client else None
        if not _ip_allowed(host, allowed_ip):
            raise HTTPException(status_code=403, detail="Origem não autorizada.")
        if not _token_valid(request.headers, token):
            raise HTTPException(status_code=401, detail="Token inválido.")

    @app.get("/health", dependencies=[Depends(authenticate)])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "gpu_free_gb": round(_free_vram_gb(), 2)}

    @app.post("/v1/jobs", status_code=202, dependencies=[Depends(authenticate)])
    async def create_job(
        audio_file: UploadFile = File(alias="audio"),
        model: str = Form("turbo"),
        language: str = Form("pt"),
        initial_prompt: str = Form(""),
        enhance: bool = Form(True),
        diarize: bool = Form(False),
    ) -> dict:
        if model not in WHISPER_MODELS:
            raise HTTPException(status_code=422, detail="Modelo inválido.")
        if language not in ("auto", "pt", "en", "es"):
            raise HTTPException(status_code=422, detail="Idioma inválido.")
        if len(initial_prompt) > 700:
            raise HTTPException(status_code=422, detail="Prompt excede 700 caracteres.")
        if not manager.has_capacity():
            raise HTTPException(status_code=429, detail="Fila de transcrição cheia.")
        suffix = Path(audio_file.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail="Formato de áudio não permitido.")

        workdir = tempfile.mkdtemp(prefix="alex-transcritor-server-")
        os.chmod(workdir, 0o700)
        target = Path(workdir) / f"audio{suffix}"
        size = 0
        try:
            with open(target, "xb") as output:
                os.chmod(target, 0o600)
                while chunk := await audio_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Arquivo excede o limite do servidor.")
                    await asyncio.to_thread(output.write, chunk)
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        finally:
            await audio_file.close()
        if size == 0:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(status_code=422, detail="Arquivo de áudio vazio.")

        job = Job(
            id=uuid.uuid4().hex,
            audio_path=str(target),
            workdir=workdir,
            model=model,
            language=language,
            initial_prompt=initial_prompt,
            enhance=enhance,
            diarize=diarize,
        )
        try:
            manager.add(job)
        except OverflowError:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(status_code=429, detail="Fila de transcrição cheia.") from None
        return {"id": job.id, "status": job.status}

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(authenticate)])
    def get_job(job_id: str) -> dict:
        try:
            return manager.get(job_id).public()
        except KeyError:
            raise HTTPException(status_code=404, detail="Trabalho não encontrado.") from None

    @app.get("/v1/jobs/{job_id}/result", response_class=PlainTextResponse, dependencies=[Depends(authenticate)])
    def get_result(job_id: str) -> str:
        try:
            job = manager.get(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Trabalho não encontrado.") from None
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail="Resultado ainda não está disponível.")
        return job.result

    @app.delete("/v1/jobs/{job_id}", status_code=204, dependencies=[Depends(authenticate)])
    def cancel_job(job_id: str) -> None:
        try:
            manager.cancel(manager.get(job_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Trabalho não encontrado.") from None

    @app.websocket("/v1/live")
    async def live_transcription(websocket: WebSocket) -> None:
        """Transcrição ao vivo processada aqui: cliente manda PCM bruto por
        frame binário, servidor devolve segmentos por mensagem JSON. Não usa
        ``Depends(authenticate)`` — HTTPException não tem como virar resposta
        HTTP depois do handshake WS; a checagem é manual, fechando a conexão
        antes de aceitar quando algo não bate.
        """
        host = websocket.client.host if websocket.client else None
        if not _ip_allowed(host, allowed_ip) or not _token_valid(websocket.headers, token):
            await websocket.close(code=4401)
            return
        if _free_vram_gb() < MIN_FREE_VRAM_GB:
            await websocket.close(code=4409)
            return

        await websocket.accept()
        try:
            opening = await websocket.receive_json()
        except Exception:
            await websocket.close(code=4400)
            return
        language = opening.get("language", "pt") if isinstance(opening, dict) else "pt"
        model_name = opening.get("model", "small") if isinstance(opening, dict) else "small"

        try:
            model = await asyncio.to_thread(live_server.load_model, model_name)
        except Exception as exc:
            await websocket.send_json({"error": f"Não foi possível carregar o modelo: {exc}"})
            await websocket.close(code=1011)
            return
        # O cliente só começa a mandar áudio depois disto: carregar o modelo
        # (na primeira vez, baixando os pesos) leva tempo, e áudio enviado
        # nesse intervalo seria só descartado do lado dele.
        await websocket.send_json({"status": "ready"})

        buffer = b""
        elapsed_s = 0.0
        first_window = True
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if not data:
                continue
            buffer, window = live_server.accumulate(buffer, data)
            if window is None:
                continue
            try:
                raw_segments = await asyncio.to_thread(
                    live_server.transcribe_window, model, window, language
                )
            except Exception as exc:
                await websocket.send_json({"error": str(exc)})
                elapsed_s += live_server.ADVANCE_BYTES / live_server.BYTES_PER_SECOND
                first_window = False
                continue
            for seg in live_server.segments_to_live_segments(raw_segments, elapsed_s, first_window):
                await websocket.send_json({
                    "text": seg.text,
                    "start_s": seg.start_s,
                    "end_s": seg.end_s,
                    "is_final": seg.is_final,
                })
            elapsed_s += live_server.ADVANCE_BYTES / live_server.BYTES_PER_SECOND
            first_window = False

    return app
