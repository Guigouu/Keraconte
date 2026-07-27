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
    """⧉ appelle le callback de re-sélection, sans toucher à l'état."""
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


def test_le_label_de_vitesse_reflete_la_valeur_courante(app):
    """Un label entre ➖ et ➕ montre la vitesse ; il suit chaque clic."""
    vitesse = Vitesse(1.0)
    overlay = _overlay(PlayerState(), vitesse=vitesse)
    assert overlay.label_vitesse.text() == "1.0×"
    overlay.on_plus()  # 1.0 → 1.1
    assert overlay.label_vitesse.text() == "1.1×"
    overlay.on_moins()  # 1.1 → 1.0
    assert overlay.label_vitesse.text() == "1.0×"


def test_les_boutons_gardent_leur_taille_naturelle(app):
    """Aucune taille n'est forcée : chaque bouton prend son « sizeHint ».

    Une version intermédiaire figeait toute la rangée à un carré du plus grand
    côté (« setFixedSize(cote, cote) »). Le « sizeHint » d'un QPushButton est
    bien plus LARGE que HAUT (padding horizontal du style) : le carré prenait
    donc la largeur comme hauteur et gonflait toute la fenêtre. Les glyphes
    emoji ➕/➖ étant abandonnés au profit de « + » et « − », l'uniformisation
    n'a plus lieu d'être — on laisse Qt dimensionner naturellement.
    """
    overlay = _overlay(PlayerState())
    boutons = [
        overlay.bouton_pause,
        overlay.bouton_stop,
        overlay.bouton_reprise,
        overlay.bouton_moins,
        overlay.bouton_plus,
        overlay.bouton_source,
        overlay.bouton_fermer,
    ]
    # Taille NON figée : min et max restent aux valeurs par défaut de Qt (min
    # sous le sizeHint, max quasi infini), preuve qu'aucun « setFixedSize »
    # carré ne subsiste.
    for bouton in boutons:
        assert bouton.minimumSize() != bouton.maximumSize()


def test_les_boutons_vitesse_sont_actifs_par_defaut(app):
    """À la vitesse par défaut 1.22, ➕/➖ ne sont ni au min ni au max :
    ils doivent être actifs. L'aspect « grisé » venait du rendu emoji, pas
    d'un vrai désactivement."""
    overlay = _overlay(PlayerState(), vitesse=Vitesse(1.22))
    assert overlay.bouton_plus.isEnabled() is True
    assert overlay.bouton_moins.isEnabled() is True


def test_les_boutons_vitesse_evitent_les_glyphes_emoji(app):
    """➕/➖ (U+2795/6) sont à présentation emoji : rendu délavé, métriques
    à part. On affiche « + » et le vrai signe moins « − » (U+2212)."""
    overlay = _overlay(PlayerState())
    assert overlay.bouton_plus.text() == "+"
    assert overlay.bouton_moins.text() == "−"


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


def test_la_poignee_de_taille_agrandit_la_barre_au_glisser(app):
    """Glisser la poignée de taille vers l'extérieur agrandit la barre.

    La barre grandit par ÉCHELLE DE POLICE, pas par géométrie : le
    QHBoxLayout épingle « minimumSize » à la somme des « sizeHint », donc un
    resize géométrique ne peut pas rétrécir et n'ajouterait que du vide. On
    vérifie que le glisser fait croître l'échelle, la police du widget, et la
    largeur du label de vitesse (dont la largeur fixe était figée à l'init —
    le bug qu'on corrige ici : « 9.9× » aurait été tronqué à grande échelle).
    """
    from PySide6.QtCore import QPoint

    overlay = _overlay(PlayerState())
    echelle_depart = overlay._echelle
    police_depart = overlay.widget.font().pointSizeF()
    label_depart = overlay.label_vitesse.width()

    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(240, 240)))

    assert overlay._echelle > echelle_depart
    assert overlay.widget.font().pointSizeF() > police_depart
    assert overlay.label_vitesse.width() > label_depart


def test_la_poignee_de_taille_borne_l_echelle(app):
    """Un glisser énorme ne dépasse pas ECHELLE_MAX (échelle bornée).

    On mappe le glisser en ABSOLU (ancré au press), pas en incrémental : sans
    borne, ou en accumulant par événement, dépasser puis revenir « décrocherait »
    la poignée du curseur. On tire très loin et l'on vérifie l'écrêtage.
    """
    from PySide6.QtCore import QPoint

    from quest_reader.overlay import ECHELLE_MAX

    overlay = _overlay(PlayerState())
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    assert overlay._echelle == ECHELLE_MAX


def test_la_poignee_de_taille_reduit_puis_borne_au_minimum(app):
    """Glisser vers l'intérieur réduit l'échelle, sans passer sous ECHELLE_MIN."""
    from PySide6.QtCore import QPoint

    from quest_reader.overlay import ECHELLE_MAX, ECHELLE_MIN

    overlay = _overlay(PlayerState())
    # On part d'une échelle haute pour avoir de la marge de réduction.
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))
    assert overlay._echelle == ECHELLE_MAX

    # Nouveau glisser, vers l'intérieur, très loin : borné au minimum.
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(-9000, -9000)))
    assert overlay._echelle == ECHELLE_MIN


def test_la_poignee_de_taille_ne_bouge_plus_apres_relachement(app):
    """Bouton relâché : un « mouseMove » ne change plus l'échelle.

    Miroir de « test_la_poignee_deplace_la_fenetre_au_glisser » : hors glisser
    actif, la poignée ignore les mouvements.
    """
    from PySide6.QtCore import QPoint

    overlay = _overlay(PlayerState())
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(240, 240)))
    echelle_glissee = overlay._echelle

    overlay.poignee_taille.mouseReleaseEvent(_FauxEvenement(QPoint(240, 240)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(500, 500)))
    assert overlay._echelle == echelle_glissee


def test_les_boutons_gardent_taille_naturelle_meme_a_grande_echelle(app):
    """Agrandir garde « minimumSize != maximumSize » : pas de « setFixedSize ».

    On élargit les boutons par « setMinimumWidth » (le style Qt fige leur
    largeur à ~80 px sinon, la police seule ne les élargit pas), mais JAMAIS
    par « setFixedSize » — qui avait gonflé la fenêtre en carré. Le test garde
    ce contrat même à échelle maximale.
    """
    from PySide6.QtCore import QPoint

    overlay = _overlay(PlayerState())
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    boutons = [
        overlay.bouton_pause,
        overlay.bouton_stop,
        overlay.bouton_reprise,
        overlay.bouton_moins,
        overlay.bouton_plus,
        overlay.bouton_source,
        overlay.bouton_fermer,
    ]
    for bouton in boutons:
        assert bouton.minimumSize() != bouton.maximumSize()


def test_la_croix_de_fermeture_est_hors_de_la_rangee_de_controles(app):
    """Le ✕ est sorti dans son propre bandeau, coin haut-droit.

    Comme le bouton fermer d'une fenêtre classique, il n'appartient plus à la
    rangée de contrôles (⏸ ⏹ ⏵ − + ⧉) : il ne suit donc PAS l'échelle de
    police du resize (voir « _boutons_echelle »). On vérifie l'appartenance,
    pas la géométrie, qui dépend du compositeur en offscreen.
    """
    overlay = _overlay(PlayerState())
    assert overlay.bouton_fermer not in overlay._boutons_echelle


def test_la_croix_ne_grandit_pas_au_resize(app):
    """Le ✕ garde sa taille quand on agrandit la barre à fond.

    Choix assumé (façon bouton-fenêtre) : seuls les contrôles de lecture
    grossissent avec la poignée ◢. Le ✕, hors « _boutons_echelle », n'est
    jamais élargi par « setMinimumWidth(base × échelle) » : sa largeur
    minimale reste celle de départ.
    """
    from PySide6.QtCore import QPoint

    from quest_reader.overlay import ECHELLE_MAX

    overlay = _overlay(PlayerState())
    largeur_depart = overlay.bouton_fermer.minimumWidth()

    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    assert overlay._echelle == ECHELLE_MAX  # la barre a bien grandi à fond
    assert overlay.bouton_fermer.minimumWidth() == largeur_depart
