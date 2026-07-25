"""Tests de l'état de lecture partagé (quest_reader.state)."""

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.state import Etat, PlayerState  # noqa: E402


def test_depart_actif():
    assert PlayerState().etat is Etat.ACTIF


def test_pause_puis_reprise():
    state = PlayerState()
    state.pause()
    assert state.etat is Etat.EN_PAUSE
    assert state.en_pause
    state.reprendre()
    assert state.etat is Etat.ACTIF
    assert not state.en_pause


def test_stop_puis_reprise_reactive():
    """▶ réarme un lecteur arrêté (ARRETE → ACTIF)."""
    state = PlayerState()
    state.stop()
    assert state.arrete
    state.reprendre()
    assert state.etat is Etat.ACTIF


def test_reactiver_leve_la_pause_mais_pas_le_stop():
    """Un nouveau dialogue lève la pause, mais ne ressuscite pas un stop.

    « reactiver » sert à « Speaker.say » : une bascule vers un nouveau
    dialogue doit défiger la voix. Mais si l'utilisateur a stoppé le lecteur,
    aucun dialogue ne doit le relancer — seul ▶ le fait.
    """
    state = PlayerState()
    state.pause()
    state.reactiver()
    assert state.etat is Etat.ACTIF

    state.stop()
    state.reactiver()
    assert state.arrete  # inchangé


def test_pause_sans_effet_si_arrete():
    state = PlayerState()
    state.stop()
    state.pause()
    assert state.arrete


def test_attendre_reprise_debloque_a_la_reprise():
    """L'attente de pause revient dès qu'un autre fil reprend."""
    state = PlayerState()
    state.pause()
    reveille = threading.Event()

    def attendre():
        state.attendre_reprise(timeout=1.0)
        reveille.set()

    fil = threading.Thread(target=attendre)
    fil.start()
    assert not reveille.wait(timeout=0.1)  # bloqué tant qu'en pause
    state.reprendre()
    assert reveille.wait(timeout=1.0)      # débloqué
    fil.join()


def test_attendre_reprise_ne_bloque_pas_si_actif():
    state = PlayerState()
    state.attendre_reprise(timeout=1.0)  # revient tout de suite
