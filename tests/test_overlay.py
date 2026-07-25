"""Tests de l'overlay Qt (quest_reader.overlay).

Qt tourne « offscreen » : on ne teste pas le rendu ni l'always-on-top
(vérif manuelle en jeu), seulement qu'un clic écrit la bonne transition dans
PlayerState et que le stop coupe la voix.
"""

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from quest_reader.state import Etat, PlayerState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def test_pause_ecrit_en_pause(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    overlay = Overlay(state, couper=lambda: None)
    overlay.on_pause()
    assert state.etat is Etat.EN_PAUSE


def test_stop_ecrit_arrete_et_coupe_la_voix(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    coupures = []
    overlay = Overlay(state, couper=lambda: coupures.append(True))
    overlay.on_stop()
    assert state.etat is Etat.ARRETE
    assert coupures == [True]  # la voix a bien été coupée


def test_reprise_ecrit_actif(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    state.pause()
    overlay = Overlay(state, couper=lambda: None)
    overlay.on_reprise()
    assert state.etat is Etat.ACTIF
