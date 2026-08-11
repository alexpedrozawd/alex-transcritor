"""Testes do SpeakerTracker — estabilidade dos rótulos "Pessoa N" ao vivo.

O ponto central: o pyannote devolve rótulos locais a cada execução, então a
mesma pessoa pode sair como SPEAKER_00 numa rodada e SPEAKER_01 na seguinte.
Se isso vazar para a tela, "Pessoa 1" troca de pessoa — pior que não rotular.
"""

from alex_transcritor.live_server import SpeakerTracker, speaker_for


def test_first_round_numbers_by_order_of_speaking():
    tracker = SpeakerTracker()
    turns = tracker.label_turns([
        (0.0, 2.0, "SPEAKER_01"),   # fala primeiro, apesar do número maior
        (2.0, 4.0, "SPEAKER_00"),
    ])
    assert turns == [(0.0, 2.0, "Pessoa 1"), (2.0, 4.0, "Pessoa 2")]


def test_labels_survive_when_pyannote_swaps_them_between_rounds():
    """O caso que motiva a classe: rótulos brutos trocados entre execuções."""
    tracker = SpeakerTracker()
    tracker.label_turns([(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")])
    # Rodada seguinte cobre o mesmo trecho, mas o pyannote inverteu os nomes.
    segunda = tracker.label_turns([(0.0, 5.0, "SPEAKER_01"), (5.0, 10.0, "SPEAKER_00")])
    assert segunda == [(0.0, 5.0, "Pessoa 1"), (5.0, 10.0, "Pessoa 2")]


def test_new_voice_gets_a_new_person():
    tracker = SpeakerTracker()
    tracker.label_turns([(0.0, 5.0, "SPEAKER_00")])
    segunda = tracker.label_turns([
        (0.0, 5.0, "SPEAKER_00"),    # mesma pessoa de antes
        (6.0, 9.0, "SPEAKER_01"),    # alguém que ainda não tinha falado
    ])
    assert segunda[0][2] == "Pessoa 1"
    assert segunda[1][2] == "Pessoa 2"


def test_two_raw_labels_never_collapse_into_one_person():
    """Duas vozes simultâneas na janela não podem virar a mesma pessoa só
    porque ambas se sobrepõem ao mesmo trecho anterior."""
    tracker = SpeakerTracker()
    tracker.label_turns([(0.0, 10.0, "SPEAKER_00")])
    segunda = tracker.label_turns([
        (0.0, 6.0, "SPEAKER_00"),
        (4.0, 10.0, "SPEAKER_01"),
    ])
    pessoas = {t[2] for t in segunda}
    assert len(pessoas) == 2, segunda


def test_person_count_does_not_grow_when_the_same_two_keep_talking():
    tracker = SpeakerTracker()
    for _ in range(5):
        turns = tracker.label_turns([
            (0.0, 3.0, "SPEAKER_00"),
            (3.0, 6.0, "SPEAKER_01"),
        ])
    assert {t[2] for t in turns} == {"Pessoa 1", "Pessoa 2"}


def test_empty_turns_is_safe():
    assert SpeakerTracker().label_turns([]) == []


# ── speaker_for ────────────────────────────────────────────────────────────────

def test_speaker_for_picks_maximum_overlap():
    turns = [(0.0, 1.0, "Pessoa 1"), (1.0, 5.0, "Pessoa 2")]
    assert speaker_for(0.0, 3.0, turns) == "Pessoa 2"   # 2s contra 1s


def test_speaker_for_returns_empty_without_any_overlap():
    assert speaker_for(20.0, 25.0, [(0.0, 1.0, "Pessoa 1")]) == ""


def test_speaker_for_with_no_turns():
    assert speaker_for(0.0, 5.0, []) == ""
