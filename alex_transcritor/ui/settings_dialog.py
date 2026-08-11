from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QPlainTextEdit, QTabWidget, QWidget, QFormLayout, QLineEdit,
)
from PyQt6.QtCore import Qt

from ..config import (
    DEVICES, TRANSCRIPTION_BACKENDS, load_config, save_config,
    list_monitor_sources, list_input_sources,
)
from ..constants import AUDIO_FORMATS, WHISPER_MODELS
from ..hardware import gpu_vram_gb
from .styles import DIALOG_STYLE

NO_SOURCE_PLACEHOLDER = "(nenhuma fonte encontrada)"

#: Rótulo exibido para cada modelo, com o custo de qualidade/velocidade medido
#: em um i5-10300H (8 threads): "turbo" leva ~1,2x a duração do áudio em CPU.
MODEL_LABELS: dict[str, str] = {
    "tiny": "tiny — o mais rápido, precisão baixa",
    "base": "base — rápido, precisão baixa",
    "small": "small — rápido em GPU de 4 GB, precisão média",
    "medium": "medium — preciso, pede ~6 GB de VRAM",
    "large-v3": "large-v3 — o mais preciso, pede ~10 GB de VRAM",
    "turbo": "turbo — recomendado: muito mais preciso, pede ~5 GB de VRAM",
}

SOURCE_LABELS: list[tuple[str, str]] = [
    ("system", "Áudio do sistema (o que você ouve)"),
    ("mic", "Microfone"),
    ("both", "Sistema + microfone (reunião)"),
]

LANGUAGE_LABELS: list[tuple[str, str]] = [
    ("pt", "Português"),
    ("en", "Inglês"),
    ("es", "Espanhol"),
    ("auto", "Detectar automaticamente"),
]

FORMAT_LABELS: dict[str, str] = {
    "flac": "FLAC — sem perda (recomendado)",
    "wav": "WAV — sem perda, arquivo grande",
    "mp3": "MP3 — comprimido, reduz a precisão",
}

DEVICE_LABELS: dict[str, str] = {
    "auto": "Automático (GPU se couber na VRAM)",
    "cuda": "Forçar GPU",
    "cpu": "Forçar CPU",
}

BACKEND_LABELS: dict[str, str] = {
    "local": "Neste computador",
    "remote": "Servidor privado via Tailscale",
}


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    """ComboBox cujos itens carregam o valor de config em ``userData``."""
    combo = QComboBox()
    for value, label in items:
        combo.addItem(label, value)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(DIALOG_STYLE)
        # A altura mínima acima é só um piso — o conteúdo real (que cresce
        # conforme os campos das abas) decide o tamanho de fato. Sem o
        # resize() explícito abaixo, alguns gerenciadores de janela abrem o
        # diálogo no tamanho mínimo em vez do sizeHint(), espremendo os
        # campos mais novos (ex.: a seção de transcrição ao vivo).
        self.config = load_config()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_audio_tab(), "Áudio")
        tabs.addTab(self._build_transcription_tab(), "Transcrição")
        tabs.addTab(self._build_vocabulary_tab(), "Vocabulário")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("btn_secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Salvar")
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)

        self.resize(self.sizeHint())

    # ── Abas ──────────────────────────────────────────────────────────────────

    def _build_audio_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 18, 16, 16)
        form.setSpacing(10)

        self.combo_source = _combo(SOURCE_LABELS, self.config["source_mode"])
        self.combo_source.currentIndexChanged.connect(self._sync_source_fields)

        monitors = list_monitor_sources()
        self.combo_monitor = QComboBox()
        self.combo_monitor.addItems(monitors or [NO_SOURCE_PLACEHOLDER])
        if self.config["monitor"] in monitors:
            self.combo_monitor.setCurrentText(self.config["monitor"])

        mics = list_input_sources()
        self.combo_mic = QComboBox()
        self.combo_mic.addItems(mics or [NO_SOURCE_PLACEHOLDER])
        if self.config["mic"] in mics:
            self.combo_mic.setCurrentText(self.config["mic"])

        self.combo_format = _combo(
            [(key, FORMAT_LABELS[key]) for key in AUDIO_FORMATS], self.config["audio_format"]
        )

        self.check_enhance = QCheckBox("Corrigir volume baixo antes de transcrever")
        self.check_enhance.setChecked(self.config["enhance_audio"])

        form.addRow(QLabel("O QUE GRAVAR"), self.combo_source)
        form.addRow(QLabel("DISPOSITIVO DE SAÍDA"), self.combo_monitor)
        form.addRow(QLabel("MICROFONE"), self.combo_mic)
        form.addRow(QLabel("FORMATO DO ARQUIVO"), self.combo_format)
        form.addRow(QLabel(""), self.check_enhance)
        form.addRow(self._hint(
            "O ganho só é aplicado quando o áudio está mesmo baixo, e apenas na "
            "cópia enviada ao modelo — a gravação salva fica intacta."
        ))
        self._sync_source_fields()
        return page

    def _build_transcription_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 18, 16, 16)
        form.setSpacing(10)

        self.combo_model = _combo(
            [(m, MODEL_LABELS[m]) for m in WHISPER_MODELS], self.config["model"]
        )
        self.combo_language = _combo(LANGUAGE_LABELS, self.config["language"])
        self.combo_device = _combo(
            [(d, DEVICE_LABELS[d]) for d in DEVICES], self.config["device"]
        )
        self.combo_backend = _combo(
            [(b, BACKEND_LABELS[b]) for b in TRANSCRIPTION_BACKENDS],
            self.config["transcription_backend"],
        )
        self.input_remote_url = QLineEdit(self.config["remote_url"])
        self.input_remote_url.setPlaceholderText("http://100.84.64.122:8300")
        self.input_remote_token = QLineEdit(self.config["remote_token"])
        self.input_remote_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_remote_token.setPlaceholderText("Token compartilhado")
        self.combo_backend.currentIndexChanged.connect(self._sync_backend_fields)

        form.addRow(QLabel("ONDE TRANSCREVER"), self.combo_backend)
        form.addRow(QLabel("SERVIDOR"), self.input_remote_url)
        form.addRow(QLabel("TOKEN"), self.input_remote_token)
        form.addRow(QLabel("MODELO"), self.combo_model)
        form.addRow(QLabel("IDIOMA"), self.combo_language)
        form.addRow(QLabel("PROCESSAMENTO"), self.combo_device)
        form.addRow(self._hint(self._hardware_hint()))

        self.check_diarize = QCheckBox("Identificar quem falou (Pessoa 1, Pessoa 2...)")
        self.check_diarize.setChecked(self.config["diarize_speakers"])
        form.addRow(QLabel(""), self.check_diarize)
        form.addRow(self._hint(
            "Só funciona no servidor remoto e aumenta o tempo de processamento. "
            "Os falantes recebem rótulos genéricos, sem identificação por nome."
        ))

        self.check_live = QCheckBox("Mostrar transcrição em tempo real durante a gravação")
        self.check_live.setChecked(self.config["live_transcription"])
        self.combo_live_model = _combo(
            [(m, MODEL_LABELS[m]) for m in WHISPER_MODELS], self.config["live_model"]
        )
        form.addRow(QLabel(""), self.check_live)
        form.addRow(QLabel("MODELO AO VIVO"), self.combo_live_model)
        form.addRow(self._hint(
            "Experimental, roda em blocos de alguns segundos (não é legenda "
            "instantânea). Usa a GPU local quando o passe final é remoto (ela "
            "fica ociosa nesse caso); roda em CPU só quando o passe final "
            "também é local, para não disputar VRAM. Exige o pacote opcional "
            "faster-whisper instalado."
        ))

        self._sync_backend_fields()
        return page

    def _build_vocabulary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(6)

        layout.addWidget(QLabel("TERMOS QUE COSTUMAM APARECER"))
        self.edit_vocabulary = QPlainTextEdit(self.config["vocabulary"])
        self.edit_vocabulary.setPlaceholderText("Alexandre Pedroza, PipeWire, Kubernetes, Dr. Sobral")
        self.edit_vocabulary.setFixedHeight(80)
        layout.addWidget(self.edit_vocabulary)
        layout.addWidget(self._hint(
            "Nomes próprios e termos técnicos separados por vírgula. São enviados "
            "ao modelo como contexto, o que reduz muito o erro nessas palavras."
        ))

        layout.addSpacing(10)
        layout.addWidget(QLabel("CORREÇÕES AUTOMÁTICAS"))
        self.edit_replacements = QPlainTextEdit(self.config["replacements"])
        self.edit_replacements.setPlaceholderText("pipe lady => PipeWire\npedrona => Pedroza")
        layout.addWidget(self.edit_replacements)
        layout.addWidget(self._hint(
            "Uma correção por linha, no formato  errado => certo.  Aplicadas ao "
            "texto final, sem diferenciar maiúsculas."
        ))
        return page

    # ── Auxiliares ────────────────────────────────────────────────────────────

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("label_hint")
        label.setWordWrap(True)
        return label

    def _hardware_hint(self) -> str:
        vram = gpu_vram_gb()
        if vram <= 0:
            return (
                "Nenhuma GPU NVIDIA detectada — a transcrição roda em CPU. "
                "Com 'turbo', reserve cerca de 1,2x a duração do áudio."
            )
        return (
            f"GPU detectada com {vram:.1f} GB de VRAM. Modelos que não couberem "
            "rodam automaticamente em CPU, sem interromper a transcrição."
        )

    def _sync_source_fields(self) -> None:
        """Desabilita o dispositivo que o modo escolhido não usa."""
        mode = self.combo_source.currentData()
        self.combo_monitor.setEnabled(mode in ("system", "both"))
        self.combo_mic.setEnabled(mode in ("mic", "both"))

    def _sync_backend_fields(self) -> None:
        remote = self.combo_backend.currentData() == "remote"
        self.input_remote_url.setEnabled(remote)
        self.input_remote_token.setEnabled(remote)
        self.combo_device.setEnabled(not remote)
        self.check_diarize.setEnabled(remote)

    @staticmethod
    def _selected_source(combo: QComboBox) -> str:
        text = combo.currentText()
        return "" if text == NO_SOURCE_PLACEHOLDER else text

    def _save(self) -> None:
        self.config.update(
            source_mode=self.combo_source.currentData(),
            monitor=self._selected_source(self.combo_monitor),
            mic=self._selected_source(self.combo_mic),
            audio_format=self.combo_format.currentData(),
            enhance_audio=self.check_enhance.isChecked(),
            model=self.combo_model.currentData(),
            language=self.combo_language.currentData(),
            device=self.combo_device.currentData(),
            transcription_backend=self.combo_backend.currentData(),
            remote_url=self.input_remote_url.text().strip().rstrip("/"),
            remote_token=self.input_remote_token.text().strip(),
            diarize_speakers=self.check_diarize.isChecked(),
            vocabulary=self.edit_vocabulary.toPlainText().strip(),
            replacements=self.edit_replacements.toPlainText().strip(),
            live_transcription=self.check_live.isChecked(),
            live_model=self.combo_live_model.currentData(),
        )
        save_config(self.config)
        self.accept()
