"""Painel que mostra a transcrição ao vivo, atualizado durante a gravação."""

import html

from PyQt6.QtWidgets import QVBoxLayout, QLabel, QTextEdit, QWidget

from ..live import LiveSegment


def _bloco(locutor: str | None, partes: list[str]) -> str:
    texto = html.escape(" ".join(partes))
    if not locutor:
        return texto
    return f'<b style="color:#8ab4f8;">{html.escape(locutor)}:</b> {texto}'


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

        #: (locutor, texto) — locutor vazio quando não há diarização.
        self._lines: list[tuple[str, str]] = []
        #: Avisos de falha não fatal, mostrados ao pé do texto.
        self._notices: list[str] = []

    def clear(self) -> None:
        self._lines = []
        self._notices = []
        self._text.clear()

    def append_segment(self, seg: LiveSegment) -> None:
        self._lines.append((seg.speaker, seg.text))
        self._render()

    def show_unavailable(self, reason: str) -> None:
        """Aviso de falha, **sem apagar o que já foi transcrito**.

        Nem todo erro é fatal: a diarização pode falhar no meio da sessão e a
        transcrição continuar normalmente. Substituir a caixa inteira nesse
        caso apagaria da tela texto bom que o usuário estava lendo.
        """
        if self._lines:
            self._notices.append(reason)
            self._render()
            return
        self._text.setPlainText(f"Transcrição ao vivo indisponível: {reason}")

    def show_status(self, message: str) -> None:
        """Aviso passageiro enquanto nada foi transcrito ainda — some sozinho
        assim que o primeiro segmento chega. Nunca sobrescreve texto já
        transcrito, para não apagar a transcrição por causa de um aviso."""
        if self._lines:
            return
        self._text.setPlainText(message)

    def _render(self) -> None:
        # Falas seguidas da mesma pessoa viram um parágrafo só: repetir
        # "Pessoa 1:" a cada bloco de poucos segundos polui a leitura.
        blocos: list[str] = []
        atual_locutor: str | None = None
        atual_texto: list[str] = []
        for locutor, texto in self._lines:
            if locutor != atual_locutor:
                if atual_texto:
                    blocos.append(_bloco(atual_locutor, atual_texto))
                atual_locutor, atual_texto = locutor, [texto]
            else:
                atual_texto.append(texto)
        if atual_texto:
            blocos.append(_bloco(atual_locutor, atual_texto))

        corpo = "<br><br>".join(blocos) if len(blocos) > 1 else "".join(blocos)
        for aviso in dict.fromkeys(self._notices):  # sem repetir o mesmo aviso
            corpo += f'<br><br><i style="color:#c98a8a;">⚠ {html.escape(aviso)}</i>'
        self._text.setHtml(corpo)
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())
