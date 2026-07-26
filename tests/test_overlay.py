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

from quest_reader.speed import MAX, MIN, PAS, Vitesse  # noqa: E402
from quest_reader.state import Etat, PlayerState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def _overlay(
    state,
    couper=lambda: None,
    reselectionner=lambda: None,
    fermer=lambda: None,
    vitesse=None,
):
    from quest_reader.overlay import Overlay

    return Overlay(
        state,
        couper=couper,
        reselectionner=reselectionner,
        fermer=fermer,
        vitesse=vitesse if vitesse is not None else Vitesse(1.22),
    )


def test_pause_ecrit_en_pause(app):
    state = PlayerState()
    overlay = _overlay(state)
    overlay.on_pause()
    assert state.etat is Etat.EN_PAUSE


def test_stop_ecrit_arrete_et_coupe_la_voix(app):
    state = PlayerState()
    coupures = []
    overlay = _overlay(state, couper=lambda: coupures.append(True))
    overlay.on_stop()
    assert state.etat is Etat.ARRETE
    assert coupures == [True]  # la voix a bien été coupée


def test_reprise_ecrit_actif(app):
    state = PlayerState()
    state.pause()
    overlay = _overlay(state)
    overlay.on_reprise()
    assert state.etat is Etat.ACTIF


def test_le_bouton_source_declenche_la_reselection(app):
    """⟳ appelle le callback de re-sélection, sans toucher à l'état."""
    state = PlayerState()
    appels = []
    overlay = _overlay(state, reselectionner=lambda: appels.append(True))
    overlay.on_source()
    assert appels == [True]
    assert state.etat is Etat.ACTIF  # la re-sélection n'est pas une transition


def test_le_bouton_fermer_declenche_la_fermeture(app):
    """✕ appelle le callback de fermeture, sans toucher à l'état."""
    state = PlayerState()
    appels = []
    overlay = _overlay(state, fermer=lambda: appels.append(True))
    overlay.on_fermer()
    assert appels == [True]
    assert state.etat is Etat.ACTIF


def test_le_bouton_plus_accelere_la_parole(app):
    """➕ augmente la vitesse partagée d'un pas, sans toucher l'état."""
    state = PlayerState()
    vitesse = Vitesse(1.0)
    overlay = _overlay(state, vitesse=vitesse)
    overlay.on_plus()
    assert vitesse.valeur == pytest.approx(1.0 + PAS)
    assert state.etat is Etat.ACTIF  # la vitesse n'est pas une transition


def test_le_bouton_moins_ralentit_la_parole(app):
    """➖ diminue la vitesse partagée d'un pas, sans toucher l'état."""
    state = PlayerState()
    vitesse = Vitesse(1.0)
    overlay = _overlay(state, vitesse=vitesse)
    overlay.on_moins()
    assert vitesse.valeur == pytest.approx(1.0 - PAS)
    assert state.etat is Etat.ACTIF


def test_le_bouton_plus_est_grise_au_maximum(app):
    """Au maximum, ➕ est grisé (on ne peut plus accélérer)."""
    overlay = _overlay(PlayerState(), vitesse=Vitesse(MAX))
    assert overlay.bouton_plus.isEnabled() is False
    assert overlay.bouton_moins.isEnabled() is True


def test_le_bouton_moins_est_grise_au_minimum(app):
    """Au minimum, ➖ est grisé (on ne peut plus ralentir)."""
    overlay = _overlay(PlayerState(), vitesse=Vitesse(MIN))
    assert overlay.bouton_moins.isEnabled() is False
    assert overlay.bouton_plus.isEnabled() is True


def test_atteindre_la_borne_grise_le_bouton(app):
    """En cliquant jusqu'à la borne, le bouton concerné se grise."""
    vitesse = Vitesse(MAX - PAS)
    overlay = _overlay(PlayerState(), vitesse=vitesse)
    assert overlay.bouton_plus.isEnabled() is True
    overlay.on_plus()  # atteint MAX
    assert overlay.bouton_plus.isEnabled() is False


def test_les_boutons_vitesse_ne_touchent_pas_l_etat(app):
    """+/- ne passent jamais par PlayerState, même en pause."""
    state = PlayerState()
    state.pause()
    overlay = _overlay(state, vitesse=Vitesse(1.0))
    overlay.on_plus()
    overlay.on_moins()
    assert state.etat is Etat.EN_PAUSE  # inchangé par les boutons vitesse


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


def test_la_poignee_deplace_la_fenetre_au_glisser(app):
    """Le glisser doit être porté par la POIGNÉE, pas par la fenêtre.

    Vu en jeu : une poignée sans handlers propres n'attrapait rien — Qt envoie
    les « mouseMove » au widget qui a reçu le « mousePress », donc au label, et
    un label nu ne déplace pas la fenêtre. On glisse ici sur « overlay.poignee »
    et l'on vérifie que c'est bien la FENÊTRE qui suit.
    """
    from PySide6.QtCore import QPoint

    overlay = _overlay(PlayerState())
    overlay.widget.move(100, 100)

    overlay.poignee.mousePressEvent(_FauxEvenement(QPoint(150, 150)))
    overlay.poignee.mouseMoveEvent(_FauxEvenement(QPoint(170, 190)))

    # Déplacement du curseur : +20 en x, +40 en y → la fenêtre suit.
    assert overlay.widget.pos() == QPoint(120, 140)

    overlay.poignee.mouseReleaseEvent(_FauxEvenement(QPoint(170, 190)))
    overlay.poignee.mouseMoveEvent(_FauxEvenement(QPoint(300, 300)))
    # Bouton relâché : plus de glisser, la fenêtre ne bouge plus.
    assert overlay.widget.pos() == QPoint(120, 140)
