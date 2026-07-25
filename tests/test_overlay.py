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


class _FauxEvenement:
    """Tient le rôle d'un QMouseEvent pour piloter le glisser.

    La fenêtre est sans bordure : Qt ne la déplace pas tout seul, on suit le
    curseur à la main. On double l'événement pour vérifier le déplacement
    sans vrai clic ni gestionnaire de fenêtres.
    """

    def __init__(self, point, bouton=None):
        from PySide6.QtCore import Qt

        self._point = point
        self._bouton = bouton if bouton is not None else Qt.LeftButton

    def button(self):
        return self._bouton

    def globalPosition(self):
        point = self._point

        class _Position:
            def toPoint(self_inner):
                return point

        return _Position()


def test_la_fenetre_se_deplace_au_glisser(app):
    """Sans bordure, la fenêtre suit le curseur pendant le glisser."""
    from PySide6.QtCore import QPoint

    from quest_reader.overlay import Overlay

    overlay = Overlay(PlayerState(), couper=lambda: None)
    overlay.widget.move(100, 100)

    overlay.widget.mousePressEvent(_FauxEvenement(QPoint(150, 150)))
    overlay.widget.mouseMoveEvent(_FauxEvenement(QPoint(170, 190)))

    # Déplacement du curseur : +20 en x, +40 en y → la fenêtre suit.
    assert overlay.widget.pos() == QPoint(120, 140)

    overlay.widget.mouseReleaseEvent(_FauxEvenement(QPoint(170, 190)))
    overlay.widget.mouseMoveEvent(_FauxEvenement(QPoint(300, 300)))
    # Bouton relâché : plus de glisser, la fenêtre ne bouge plus.
    assert overlay.widget.pos() == QPoint(120, 140)
