"""Testes do LivePanel — a caixa de transcrição ao vivo."""

from alex_transcritor.live import LiveSegment
from alex_transcritor.ui.live_panel import LivePanel


def _seg(text: str, is_final: bool = True, speaker: str = "") -> LiveSegment:
    return LiveSegment(text=text, start_s=0.0, end_s=1.0, is_final=is_final, speaker=speaker)


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


def test_speaker_labels_are_shown(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("bom dia", speaker="Pessoa 1"))
    panel.append_segment(_seg("bom dia pra você", speaker="Pessoa 2"))
    texto = panel._text.toPlainText()
    assert "Pessoa 1: bom dia" in texto
    assert "Pessoa 2: bom dia pra você" in texto


def test_consecutive_turns_of_the_same_speaker_are_merged(qtbot):
    """Repetir "Pessoa 1:" a cada bloco de poucos segundos polui a leitura."""
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("primeira parte", speaker="Pessoa 1"))
    panel.append_segment(_seg("segunda parte", speaker="Pessoa 1"))
    texto = panel._text.toPlainText()
    assert texto.count("Pessoa 1") == 1
    assert "primeira parte segunda parte" in texto


def test_without_diarization_no_label_prefix(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("texto simples"))
    assert panel._text.toPlainText().strip() == "texto simples"


def test_special_characters_are_escaped_not_interpreted_as_html(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("<script>alert(1)</script> & outros <tags>"))
    assert "<script>" not in panel._text.toHtml()
    assert "alert(1)" in panel._text.toPlainText()


def test_error_does_not_erase_already_transcribed_text(qtbot):
    """Regressão: um erro não fatal (ex.: diarização caindo no meio da sessão)
    apagava a caixa inteira, sumindo com texto bom que o usuário estava lendo."""
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("primeira frase importante"))
    panel.append_segment(_seg("segunda frase importante"))
    panel.show_unavailable("Identificação de locutor indisponível")
    texto = panel._text.toPlainText()
    assert "primeira frase importante" in texto
    assert "segunda frase importante" in texto
    assert "Identificação de locutor indisponível" in texto


def test_repeated_errors_are_not_duplicated(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("texto"))
    for _ in range(4):
        panel.show_unavailable("mesma falha")
    assert panel._text.toPlainText().count("mesma falha") == 1


def test_error_before_any_text_still_replaces_the_box(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.show_unavailable("faster-whisper não instalado")
    assert "faster-whisper não instalado" in panel._text.toPlainText()


def test_clear_also_clears_notices(qtbot):
    panel = LivePanel()
    qtbot.addWidget(panel)
    panel.append_segment(_seg("texto"))
    panel.show_unavailable("falha antiga")
    panel.clear()
    panel.append_segment(_seg("gravação nova"))
    assert "falha antiga" not in panel._text.toPlainText()
