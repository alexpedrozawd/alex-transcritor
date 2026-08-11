"""Transcrição incremental (ao vivo), opcional e best-effort.

Roda em paralelo à gravação principal, lendo PCM bruto do stdout do ffmpeg
(ver ``audio.record_command(..., live_pcm=True)``) e decodificando em janelas
curtas com ``faster-whisper``. Qualquer falha aqui é reportada por sinal e
nunca deve interromper a gravação/transcrição principal — por isso o import
do motor é protegido e toda a ``run()`` está isolada em try/except.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import BinaryIO

from PyQt6.QtCore import QThread, pyqtSignal

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover — exercitado via testes com monkeypatch
    WhisperModel = None

#: PCM s16le mono a 16 kHz: 2 bytes por amostra, 16000 amostras/segundo.
BYTES_PER_SECOND = 16000 * 2

#: Janela de decodificação e sobreposição usada só como contexto acústico —
#: o texto da sobreposição já foi emitido pela janela anterior e é descartado
#: (ver ``_should_emit``), não reemitido. O piso mínimo de latência é
#: WINDOW_S + tempo de transcrição — reduzir a janela é o jeito mais direto
#: de acelerar a resposta, à custa de um pouco menos de contexto por trecho
#: decodificado (mais chance de fragmentação, principalmente em CPU).
WINDOW_S = 2.0
OVERLAP_S = 0.5
WINDOW_BYTES = int(WINDOW_S * BYTES_PER_SECOND)
OVERLAP_BYTES = int(OVERLAP_S * BYTES_PER_SECOND)
ADVANCE_BYTES = WINDOW_BYTES - OVERLAP_BYTES

#: Quanto silêncio ao final da janela para considerar a fala finalizada (pausa
#: real) em vez de cortada no meio — só afeta o rótulo ``is_final``.
TRAILING_SILENCE_S = 0.3

READ_CHUNK_BYTES = 4096

#: Se a fila de blocos pendentes passar disso, a transcrição caiu atrás do
#: tempo real — pular o acúmulo em vez de gastar tempo (que só afunda mais)
#: transcrevendo áudio que já não é mais "ao vivo" quando terminar. Sem esse
#: teto, uma transcrição lenta nunca alcança o presente: a cada janela
#: processada, mais áudio novo já se acumulou, e ao clicar Parar o app fica
#: minutos "catching up" um atraso que não serve mais pra nada.
#: Alto o bastante para tolerar a rajada normal de uma única janela cheia
#: chegando de uma vez (~23 blocos de 4096 bytes) sem descartar áudio válido
#: — ~6s de áudio pendente com READ_CHUNK_BYTES=4096 a 32000 bytes/s.
MAX_QUEUED_CHUNKS = 50


@dataclass
class LiveSegment:
    """Um trecho decodificado da fala ao vivo.

    Dataclass simples, sem Qt, para que um futuro cruzamento por palavra-chave
    (fase seguinte, fora de escopo aqui) possa consumir o sinal ``segment``
    sem depender do PyQt6.
    """

    text: str
    start_s: float
    end_s: float
    is_final: bool  # True = pausa detectada ao fim da janela, não será revisado


def accumulate(buffer: bytes, chunk: bytes) -> tuple[bytes, bytes | None]:
    """Acrescenta ``chunk`` ao ``buffer`` e extrai uma janela pronta, se houver.

    Devolve ``(buffer_restante, janela_ou_None)``. O buffer restante inclui os
    últimos ``OVERLAP_BYTES`` da janela extraída, como contexto para a próxima
    decodificação — função pura, testável sem ffmpeg nem modelo.
    """
    buffer += chunk
    if len(buffer) < WINDOW_BYTES:
        return buffer, None
    window = buffer[:WINDOW_BYTES]
    return buffer[ADVANCE_BYTES:], window


def should_emit(rel_end_s: float, is_first_window: bool) -> bool:
    """Um segmento cujo fim cai dentro da sobreposição já foi emitido antes."""
    return is_first_window or rel_end_s > OVERLAP_S


class LiveTranscriber(QThread):
    """Lê PCM do stdout do ffmpeg e emite texto incremental por janela."""

    segment = pyqtSignal(object)  # LiveSegment
    failed = pyqtSignal(str)      # não fatal — a gravação principal segue

    def __init__(
        self,
        stdout: BinaryIO,
        model_size: str = "tiny",
        device: str = "cpu",
        language: str = "pt",
    ) -> None:
        super().__init__()
        self._stdout = stdout
        self.model_size = model_size
        self.device = device
        self.language = language
        self._stopped = False
        # Fila entre a leitura do pipe e a transcrição — ver run()/_read_loop.
        self._chunks: queue.Queue[bytes | None] = queue.Queue()

    def stop(self) -> None:
        self._stopped = True
        self._chunks.put(None)  # desbloqueia get() se estiver esperando dado

    def run(self) -> None:
        if WhisperModel is None:
            self.failed.emit(
                "faster-whisper não instalado — veja requirements-live.txt"
            )
            return

        # Thread só de leitura, independente da transcrição: se a leitura
        # esperasse cada model.transcribe() terminar (como era antes), o
        # buffer do pipe do SO enche em ~2s de áudio não lido e o ffmpeg
        # trava no write() — não só o painel ao vivo para, a GRAVAÇÃO
        # inteira trava, porque é o mesmo processo ffmpeg escrevendo os dois
        # arquivos. Essa thread garante que o pipe é sempre drenado, não
        # importa quão lenta esteja a transcrição.
        reader = threading.Thread(target=self._read_loop, daemon=True)
        reader.start()

        if self._stopped:
            reader.join(timeout=5)
            return

        model = self._load_model()
        if model is None:
            self.stop()
            reader.join(timeout=5)
            return

        buffer = b""
        elapsed_s = 0.0
        first_window = True
        already_failed = False

        while not self._stopped:
            chunk = self._chunks.get()
            if chunk is None:  # EOF do ffmpeg, ou stop() pedindo para sair
                break
            if self._chunks.qsize() > MAX_QUEUED_CHUNKS:
                # Muito atrás do tempo real: descarta este bloco e o que
                # estava acumulado, sem transcrever — só avança o relógio.
                buffer = b""
                elapsed_s += len(chunk) / BYTES_PER_SECOND
                continue
            buffer, window = accumulate(buffer, chunk)
            if window is None:
                continue
            try:
                self._transcribe_window(model, window, elapsed_s, first_window)
            except Exception as exc:
                if not already_failed:
                    self.failed.emit(f"Erro na transcrição ao vivo: {exc}")
                    already_failed = True
            elapsed_s += ADVANCE_BYTES / BYTES_PER_SECOND
            first_window = False

        self._stopped = True
        reader.join(timeout=5)

    def _load_model(self):
        """Carrega o modelo no device pedido; se for GPU e falhar (driver
        incompleto, bibliotecas CUDA ausentes etc.), tenta CPU antes de
        desistir de vez — best-effort, gravação principal nunca depende
        disto. Devolve ``None`` (já tendo emitido ``failed``) se as duas
        tentativas falharem.

        ``compute_type`` varia por device: "int8" é o ganho de velocidade
        certo em CPU, mas em GPU "float16" decodifica mais rápido — a GPU
        tem suporte nativo a fp16, e o ganho do int8 ali é bem menor (às
        vezes nem existe, dependendo da arquitetura).
        """
        try:
            compute_type = "int8" if self.device == "cpu" else "float16"
            return WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
        except Exception as exc:
            if self.device == "cpu":
                self.failed.emit(f"Não foi possível carregar o modelo ao vivo: {exc}")
                return None
        try:
            return WhisperModel(self.model_size, device="cpu", compute_type="int8")
        except Exception as exc:
            self.failed.emit(f"Não foi possível carregar o modelo ao vivo: {exc}")
            return None

    def _read_loop(self) -> None:
        """Só drena o pipe, o mais rápido possível — nunca espera a transcrição."""
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

    def _transcribe_window(
        self, model, window: bytes, window_start_s: float, is_first_window: bool
    ) -> None:
        import numpy as np

        audio = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            condition_on_previous_text=False,
            # Busca em feixe (padrão do faster-whisper: beam_size=5) é várias
            # vezes mais lenta que decodificação gulosa — inviável para uma
            # janela de poucos segundos em CPU. O passe final continua com
            # qualidade plena; aqui a prioridade é acompanhar em tempo real.
            beam_size=1,
            best_of=1,
        )
        segments = list(segments)
        last_idx = len(segments) - 1
        for i, seg in enumerate(segments):
            if not should_emit(seg.end, is_first_window):
                continue
            text = seg.text.strip()
            if not text:
                continue
            is_last = i == last_idx
            finalized = (not is_last) or (WINDOW_S - seg.end > TRAILING_SILENCE_S)
            self.segment.emit(
                LiveSegment(
                    text=text,
                    start_s=window_start_s + seg.start,
                    end_s=window_start_s + seg.end,
                    is_final=finalized,
                )
            )
