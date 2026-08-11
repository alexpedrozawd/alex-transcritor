"""Painel que mostra a transcrição ao vivo, atualizado durante a gravação."""

import html

from PyQt6.QtWidgets import QVBoxLayout, QLabel, QTextEdit, QWidget

from ..live import LiveSegment


class LivePanel(QWidget):
    """Cada segmento recebido entra na caixa e fica lá — a transcrição só
    cresce durante a gravação, nunca some ou é substituída.

    ``LiveSegment.is_final`` não distingue nada aqui de propósito: nada
    nesta implementação corrige um trecho já mostrado depois (a janela
    seguinte só evita reprocessar o áudio já coberto, não "revisa" o texto
    anterior) — então marcar um trecho como "provisório" e trocá-lo no lugar
    só fazia a tela parecer perder texto em fala contínua, sem pausas longas
    o bastante para algo ser considerado "final".
    """

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

        self._lines: list[str] = []

    def clear(self) -> None:
        self._lines = []
        self._text.clear()

    def append_segment(self, seg: LiveSegment) -> None:
        self._lines.append(seg.text)
        self._render()

    def show_unavailable(self, reason: str) -> None:
        self._text.setPlainText(f"Transcrição ao vivo indisponível: {reason}")

    def show_status(self, message: str) -> None:
        """Aviso passageiro enquanto nada foi transcrito ainda — some sozinho
        assim que o primeiro segmento chega. Nunca sobrescreve texto já
        transcrito, para não apagar a transcrição por causa de um aviso."""
        if self._lines:
            return
        self._text.setPlainText(message)

    def _render(self) -> None:
        body = " ".join(html.escape(p) for p in self._lines)
        self._text.setHtml(body)
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())
