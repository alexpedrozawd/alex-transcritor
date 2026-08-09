import os
import re
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import audio
from .hardware import pick_device

#: tqdm escreve o percentual em stderr, sobrescrevendo a linha com \r.
_PROGRESS_RE = re.compile(rb"(\d{1,3})%\|")

#: Mínimo de tempo concedido à transcrição, e multiplicador sobre a duração do
#: áudio. Um teto fixo de uma hora interrompia gravações longas: em CPU o
#: Whisper roda perto de 1x tempo real, então uma hora de áudio precisa de mais
#: de uma hora de processamento.
MIN_TIMEOUT_S = 900
TIMEOUT_FACTOR = 25


class WhisperThread(QThread):
    """Transcreve um arquivo de áudio em uma thread separada.

    Os sinais se chamam ``succeeded``/``failed`` em vez de ``finished``/``error``
    para não sombrear ``QThread.finished``, que o Qt emite por conta própria.
    """

    succeeded = pyqtSignal(str)      # caminho do .txt gerado
    failed = pyqtSignal(str)         # mensagem de erro
    progress = pyqtSignal(int, str)  # percentual, rótulo da etapa

    def __init__(
        self,
        audio_path: str,
        txt_path: str,
        whisper_bin: str,
        model: str = "small",
        language: str = "pt",
        device: str = "auto",
        initial_prompt: str = "",
        enhance: bool = True,
        replacements: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.audio_path = audio_path
        self.txt_path = txt_path
        self.whisper_bin = whisper_bin
        self.model = model
        self.language = language
        self.device = device
        self.initial_prompt = initial_prompt
        self.enhance = enhance
        self.replacements = replacements or []
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._last_error = ""

    # ── Controle ──────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Interrompe a transcrição e o processo filho.

        Necessário porque ``QThread.terminate()`` mata apenas a thread e deixa o
        Whisper rodando órfão, segurando GPU e vários GB de RAM.
        """
        self._cancelled = True
        self._kill_process()

    def _kill_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        except OSError:
            pass

    # ── Execução ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._transcribe()
        except Exception as exc:  # rede de segurança: uma thread não pode morrer calada
            if not self._cancelled:
                self.failed.emit(f"Erro inesperado na transcrição: {exc}")

    def _transcribe(self) -> None:
        if not Path(self.audio_path).exists():
            self.failed.emit(f"Arquivo de áudio não encontrado:\n{self.audio_path}")
            return

        duration = audio.probe_duration(self.audio_path)
        if 0 < duration < 0.5:
            self.failed.emit(
                "A gravação ficou vazia (menos de meio segundo de áudio).\n"
                "Verifique em ⚙ Configurações se o dispositivo de áudio está correto."
            )
            return

        with tempfile.TemporaryDirectory(prefix="alex-transcritor-") as workdir:
            source = self._prepare_source(workdir)
            device = pick_device(self.model, self.device)
            result = self._run_whisper(source, workdir, device, duration)

            if result is None and not self._cancelled and device == "cuda":
                # Falta de VRAM e logits NaN em fp16 são falhas específicas de
                # GPU; a CPU é mais lenta, mas conclui.
                self.progress.emit(0, "Falha na GPU — refazendo em CPU...")
                result = self._run_whisper(source, workdir, "cpu", duration)

            if self._cancelled:
                return
            if result is None:
                self.failed.emit(self._last_error or "Whisper terminou sem gerar transcrição.")
                return

            try:
                final = self._publish(result)
            except OSError as exc:
                self.failed.emit(f"Não foi possível salvar a transcrição:\n{exc}")
                return

        self.succeeded.emit(str(final))

    def _prepare_source(self, workdir: str) -> str:
        """Normaliza o nível do áudio, quando compensa, mantendo o original."""
        if not self.enhance:
            return self.audio_path
        self.progress.emit(0, "Analisando áudio...")
        gain = audio.needed_gain_db(self.audio_path)
        if gain <= 0:
            return self.audio_path  # já está em nível adequado
        self.progress.emit(0, f"Normalizando volume (+{gain:g} dB)...")
        target = os.path.join(workdir, "entrada.flac")
        try:
            result = subprocess.run(
                audio.gain_command(self.audio_path, target, gain),
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode == 0 and os.path.exists(target):
                return target
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        # O ajuste é um extra: falhar nele não deve impedir a transcrição.
        return self.audio_path

    def _run_whisper(self, source: str, workdir: str, device: str, duration: float) -> Path | None:
        """Roda o Whisper isolado em ``workdir``; devolve o .txt gerado ou ``None``."""
        outdir = Path(workdir) / f"saida-{device}"
        shutil.rmtree(outdir, ignore_errors=True)
        outdir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.whisper_bin, source,
            "--model", self.model,
            "--output_format", "txt",
            "--output_dir", str(outdir),
            "--device", device,
            # fp16 produz logits NaN em várias GPUs Turing/Pascal, e a
            # implementação de referência carrega os pesos em float32 de todo
            # jeito — desligar não custa VRAM nem velocidade relevante.
            "--fp16", "False",
            "--beam_size", "5",
            "--temperature", "0",
            # Impede que o modelo siga repetindo a janela anterior ao encontrar
            # silêncio ou ruído — origem clássica de alucinação.
            "--condition_on_previous_text", "False",
            "--verbose", "False",
        ]
        if self.language and self.language != "auto":
            cmd += ["--language", self.language]
        if self.initial_prompt:
            cmd += ["--initial_prompt", self.initial_prompt]

        self._last_error = ""
        timeout = max(MIN_TIMEOUT_S, duration * TIMEOUT_FACTOR)
        tail = self._stream_process(cmd, timeout, device)
        if tail is None:
            return None

        produced = sorted(outdir.glob("*.txt"))
        if produced:
            return produced[0]

        # Whisper captura exceções por arquivo, imprime "Skipping ..." e mesmo
        # assim sai com código 0 — sem esta verificação a falha vira "sucesso".
        self._last_error = tail or "Whisper terminou sem gerar o arquivo de transcrição."
        return None

    def _stream_process(self, cmd: list[str], timeout: float, device: str) -> str | None:
        """Executa o comando repassando o progresso; devolve o fim do stderr."""
        label = f"Transcrevendo ({self.model} · {device.upper()})"
        self.progress.emit(0, label + "...")
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._last_error = (
                f"Binário do Whisper não encontrado: {self.whisper_bin}\n"
                "Verifique se o Whisper está instalado no ambiente virtual."
            )
            return None
        except OSError as exc:
            self._last_error = f"Não foi possível iniciar o Whisper: {exc}"
            return None

        stream = self._process.stderr
        buffer = b""
        deadline = time.monotonic() + timeout
        while True:
            if self._cancelled:
                self._kill_process()
                return None
            if time.monotonic() > deadline:
                self._kill_process()
                self._last_error = f"Tempo limite de transcrição excedido ({int(timeout / 60)} min)."
                return None
            # select evita bloquear numa leitura sem saída e, com isso, perder o
            # prazo ou o pedido de cancelamento.
            ready, _, _ = select.select([stream], [], [], 0.5)
            if ready:
                chunk = stream.read1(4096)
                if not chunk:
                    break
                buffer += chunk
                self._emit_progress(buffer, label)
                buffer = buffer[-8192:]
            elif self._process.poll() is not None:
                break

        buffer += stream.read() or b""
        stream.close()
        self._process.wait()
        if self._cancelled:
            return None
        return buffer[-4000:].decode("utf-8", "replace")

    def _emit_progress(self, buffer: bytes, label: str) -> None:
        matches = _PROGRESS_RE.findall(buffer)
        if not matches:
            return
        percent = min(100, int(matches[-1]))
        # Antes de transcrever, o mesmo formato de barra reporta o download do
        # modelo; distinguir evita a UI dizer "transcrevendo" durante o download.
        downloading = b"iB/s" in buffer.rsplit(b"\r", 2)[-1]
        self.progress.emit(percent, "Baixando modelo..." if downloading else label + "...")

    # ── Pós-processamento ─────────────────────────────────────────────────────

    def _publish(self, produced: Path) -> Path:
        """Aplica as correções e move a transcrição para o destino final."""
        text = produced.read_text(encoding="utf-8")
        for wrong, right in self.replacements:
            text = re.sub(re.escape(wrong), lambda _m, r=right: r, text, flags=re.IGNORECASE)

        target = Path(self.txt_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target
