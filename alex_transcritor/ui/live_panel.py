"""Painel que mostra a transcrição ao vivo, atualizado durante a gravação."""

import html

from PyQt6.QtWidgets import QVBoxLayout, QLabel, QTextEdit, QWidget

from ..live import LiveSegment


class LivePanel(QWidget):
    """Segmentos finalizados viram parágrafos; o provisório fica em itálico e é
    substituído no lugar a cada nova decodificação — nunca acumulado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        label = QLabel("TRANSCRIÇÃO AO VIVO")
        label.setObjectName("label_field")

        self._text = QTextEdit()
        self._text.setObjectName("livePanel")
        self._text.setReadOnly(True)
        self._text.setFixedHeight(120)

        layout.addWidget(label)
        layout.addWidget(self._text)

        self._finalized: list[str] = []
        self._provisional: str = ""

    def clear(self) -> None:
        self._finalized = []
        self._provisional = ""
        self._text.clear()

    def append_segment(self, seg: LiveSegment) -> None:
        if seg.is_final:
            self._finalized.append(seg.text)
            self._provisional = ""
        else:
            self._provisional = seg.text
        self._render()

    def show_unavailable(self, reason: str) -> None:
        self._text.setPlainText(f"Transcrição ao vivo indisponível: {reason}")

    def _render(self) -> None:
        parts = [html.escape(p) for p in self._finalized]
        body = " ".join(parts)
        if self._provisional:
            provisional = html.escape(self._provisional)
            body += f' <span style="color:#8a8a8a; font-style:italic;">{provisional}</span>'
        self._text.setHtml(body)
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())
