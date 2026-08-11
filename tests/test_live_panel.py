"""Testes do LivePanel — a caixa de transcrição ao vivo."""

from alex_transcritor.live import LiveSegment
from alex_transcritor.ui.live_panel import LivePanel


def _seg(text: str, is_final: bool = True) -> LiveSegment:
    return LiveSegment(text=text, start_s=0.0, end_s=1.0, is_final=is_final)


def test_segments_accumulate_instead_of_replacing_each_other(qtbot):
    """Regressão: o texto sumia/era substituído em fala contínua, porque
    quase nada era marcado 'final' pela heurística de pausa antiga. Agora
    tudo que chega acumula, independente de is_final."""
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("primeira frase"))
    panel.append_segment(_seg("segunda frase", is_final=False))
    panel.append_segment(_seg("terceira frase", is_final=False))
    text = panel._text.toPlainText()
    assert "primeira frase" in text
    assert "segunda frase" in text
    assert "terceira frase" in text


def test_clear_resets_accumulated_text(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("algo"))
    panel.clear()
    assert panel._text.toPlainText() == ""
    panel.append_segment(_seg("depois de limpar"))
    assert panel._text.toPlainText() == "depois de limpar"


def test_show_unavailable_overwrites_with_the_reason(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("texto que já apareceu"))
    panel.show_unavailable("faster-whisper não instalado")
    assert "faster-whisper não instalado" in panel._text.toPlainText()


def test_special_characters_are_escaped_not_interpreted_as_html(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("<script>alert(1)</script> & outros <tags>"))
    assert "<script>" not in panel._text.toHtml()
    assert "alert(1)" in panel._text.toPlainText()
