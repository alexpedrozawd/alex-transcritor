"""Cliente da API privada de transcrição remota."""

import json
import ipaddress
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QThread, pyqtSignal


class RemoteWhisperThread(QThread):
    """Envia o áudio ao servidor e acompanha o trabalho sem bloquear a UI."""

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(
        self,
        audio_path: str,
        txt_path: str,
        remote_url: str,
        token: str,
        model: str,
        language: str,
        initial_prompt: str = "",
        enhance: bool = True,
        diarize: bool = False,
        replacements: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.audio_path = audio_path
        self.txt_path = txt_path
        self.remote_url = remote_url.rstrip("/")
        self.token = token
        self.model = model
        self.language = language
        self.initial_prompt = initial_prompt
        self.enhance = enhance
        self.diarize = diarize
        self.replacements = replacements or []
        self._cancelled = False
        self._job_id = ""
        self._session = requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def cancel(self) -> None:
        self._cancelled = True
        if self._job_id:
            try:
                requests.delete(
                    f"{self.remote_url}/v1/jobs/{self._job_id}",
                    headers=self._headers,
                    timeout=10,
                )
            except requests.RequestException:
                pass

    def run(self) -> None:
        try:
            self._run_remote()
        except requests.RequestException as exc:
            if not self._cancelled:
                self.failed.emit(f"Servidor de transcrição indisponível:\n{exc}")
        except (OSError, ValueError, KeyError) as exc:
            if not self._cancelled:
                self.failed.emit(f"Falha na transcrição remota:\n{exc}")
        finally:
            self._session.close()

    def _run_remote(self) -> None:
        if not self.token:
            raise ValueError("Token do servidor remoto não configurado.")
        parsed = urlparse(self.remote_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("URL do servidor remoto inválida.")
        if parsed.scheme == "http":
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError as exc:
                raise ValueError("HTTP sem TLS só é permitido para um IP Tailscale.") from exc
            if address not in ipaddress.ip_network("100.64.0.0/10"):
                raise ValueError("HTTP sem TLS só é permitido dentro da Tailscale.")
        self.progress.emit(0, "Enviando áudio ao servidor...")
        data = {
            "model": self.model,
            "language": self.language,
            "initial_prompt": self.initial_prompt,
            "enhance": json.dumps(self.enhance),
            "diarize": json.dumps(self.diarize),
        }
        with open(self.audio_path, "rb") as source:
            response = self._session.post(
                f"{self.remote_url}/v1/jobs",
                headers=self._headers,
                data=data,
                files={"audio": (Path(self.audio_path).name, source, "application/octet-stream")},
                timeout=(10, 3600),
            )
        self._raise(response)
        self._job_id = response.json()["id"]

        while not self._cancelled:
            response = self._session.get(
                f"{self.remote_url}/v1/jobs/{self._job_id}",
                headers=self._headers,
                timeout=15,
            )
            self._raise(response)
            job = response.json()
            status = job["status"]
            self.progress.emit(int(job.get("progress", 0)), job.get("message", "Transcrevendo..."))
            if status == "succeeded":
                if note := job.get("diarization_note"):
                    self.progress.emit(100, note)
                self._download_result()
                return
            if status in ("failed", "cancelled"):
                if status == "failed":
                    self.failed.emit(job.get("error") or "A transcrição remota falhou.")
                return
            time.sleep(1)

    def _download_result(self) -> None:
        response = self._session.get(
            f"{self.remote_url}/v1/jobs/{self._job_id}/result",
            headers=self._headers,
            timeout=60,
        )
        self._raise(response)
        text = response.text
        for wrong, right in self.replacements:
            text = re.sub(re.escape(wrong), lambda _m, r=right: r, text, flags=re.IGNORECASE)
        target = Path(self.txt_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self.succeeded.emit(str(target))

    @staticmethod
    def _raise(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ValueError(f"Servidor respondeu HTTP {response.status_code}: {detail}")
