"""Tests de l'overlay Qt (keraconte.overlay).

Qt tourne « offscreen » : on ne teste pas le rendu ni l'always-on-top
(vérif manuelle en jeu), seulement qu'un clic écrit la bonne transition dans
PlayerState et que le stop coupe la voix.
"""

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from keraconte.speed import MAX, MIN, PAS, Vitesse  # noqa: E402
from keraconte.state import Etat, PlayerState  # noqa: E402


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
    nb_ecrans=None,
    console_disponible=False,
):
    from keraconte.overlay import Overlay

    return Overlay(
        state,
        couper=couper,
        reselectionner=reselectionner,
        fermer=fermer,
        vitesse=vitesse if vitesse is not None else Vitesse(1.22),
        nb_ecrans=nb_ecrans,
        console_disponible=console_disponible,
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


def test_le_bouton_source_est_grise_avec_un_seul_ecran(app):
    """Un seul écran : rien à basculer, le bouton source est grisé.

    C'est la réponse directe à « je ne savais pas si ça changeait quelque
    chose » : quand il n'y a rien à changer, le bouton le montre en étant
    désactivé, au lieu de rester cliquable dans le vide.
    """
    overlay = _overlay(PlayerState(), nb_ecrans=1)
    assert overlay.bouton_source.isEnabled() is False


def test_le_bouton_source_reste_actif_avec_plusieurs_ecrans(app):
    """Deux écrans (ou plus) : le bouton source reste cliquable."""
    overlay = _overlay(PlayerState(), nb_ecrans=2)
    assert overlay.bouton_source.isEnabled() is True


def test_le_bouton_source_actif_quand_nb_ecrans_inconnu(app):
    """nb_ecrans=None (Linux/portail, ou non fourni) : bouton actif, inchangé.

    Le grisage ne concerne que le cas mono-écran mss connu. Sans info (backend
    portail Linux, où la re-sélection a toujours du sens), on ne grise pas.
    """
    overlay = _overlay(PlayerState(), nb_ecrans=None)
    assert overlay.bouton_source.isEnabled() is True


def test_flash_source_affiche_un_cadre_sur_l_ecran_capture(app):
    """Le signal flash_source crée une fenêtre-cadre sur l'écran capturé.

    Le backend émet la géométrie PHYSIQUE (mss) ; l'overlay la remappe vers le
    QScreen correspondant et dessine le cadre sur SA géométrie logique (voir
    _ecran_pour_rect_physique). On vérifie donc qu'un cadre existe et épouse un
    écran RÉEL, pas la géométrie brute émise (qui divergerait sous échelle).
    """
    from PySide6.QtGui import QGuiApplication

    overlay = _overlay(PlayerState(), nb_ecrans=2)
    overlay.flash_source.emit((0, 0, 640, 480))
    cadre = overlay._cadre  # la fenêtre-cadre en cours
    assert cadre is not None
    geo = cadre.geometry()
    # Le cadre épouse la géométrie logique d'un des écrans Qt.
    geos_ecrans = [
        (e.geometry().x(), e.geometry().y(), e.geometry().width(), e.geometry().height())
        for e in QGuiApplication.screens()
    ]
    assert (geo.x(), geo.y(), geo.width(), geo.height()) in geos_ecrans


def test_le_cadre_peint_reellement_une_bordure_cyan(app):
    """Le cadre DESSINE : un bord cyan, un centre vide (transparent).

    Sans ce test, un widget transparent dont « paintEvent » ne serait jamais
    dispatché passerait tous les autres tests tout en restant INVISIBLE en jeu
    (même classe de bug que « démarre bien, muet à l'usage »). On rend le widget
    dans un QPixmap et on inspecte deux pixels : un sur le bord, un au centre.
    """
    from keraconte.overlay import FlashCadre

    cadre = FlashCadre(0, 0, 200, 120)
    pix = cadre.grab()  # peint le widget hors écran, dispatche paintEvent
    bord = pix.toImage().pixelColor(3, 60)  # dans l'épaisseur du bord gauche
    centre = pix.toImage().pixelColor(100, 60)  # plein milieu, hors bordure
    # Bord cyan franc (0,200,255) ; on tolère l'antialiasing par des seuils.
    assert bord.blue() > 150 and bord.green() > 120 and bord.red() < 80
    # Centre non peint : pas de cyan opaque au milieu.
    assert not (centre.blue() > 150 and centre.green() > 120)
    cadre.close()


def test_flash_source_traverse_le_signal_depuis_un_autre_thread(app):
    """Émettre flash_source depuis un AUTRE thread est livré, en file, au thread Qt.

    C'est la raison d'être du signal : le backend de capture tourne sur son
    propre thread. On émet depuis un thread séparé (aucun cadre ne doit être créé
    hors thread Qt), puis on pompe la boucle d'événements sur le thread principal
    — c'est LÀ que le slot doit s'exécuter et créer le cadre.
    """
    import threading

    from PySide6.QtWidgets import QApplication

    overlay = _overlay(PlayerState(), nb_ecrans=2)

    def emettre():
        overlay.flash_source.emit((10, 10, 320, 240))

    fil = threading.Thread(target=emettre)
    fil.start()
    fil.join()
    # Avant de pomper : le slot ne s'est PAS exécuté (livraison en file).
    assert overlay._cadre is None
    QApplication.processEvents()  # traite la file : le slot crée le cadre ICI
    assert overlay._cadre is not None  # le slot s'est bien exécuté côté Qt


class _FauxRect:
    def __init__(self, x, y, w, h):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h


class _FauxEcran:
    """Tient le rôle d'un QScreen : géométrie LOGIQUE + facteur d'échelle."""

    def __init__(self, x, y, w, h, dpr):
        self._geo = _FauxRect(x, y, w, h)
        self._dpr = dpr

    def geometry(self):
        return self._geo

    def devicePixelRatio(self):
        return self._dpr


def test_le_rect_physique_mss_retrouve_le_bon_ecran_avec_echelle():
    """La géométrie mss (pixels physiques) mappe le bon QScreen à 150 %.

    Sans ce mapping, un cadre posé aux coordonnées mss brutes atterrit sur le
    mauvais écran quand Windows applique une échelle : l'écran 2 est à x=2560
    physique mais x≈1707 logique. On vérifie qu'un rect physique à left=2560
    choisit bien l'écran 2, pas l'écran 1.
    """
    from keraconte.overlay import _ecran_pour_rect_physique

    # Écran 1 : logique (0,0,1707,960) à 150 % → physique (0,0,2560,1440).
    # Écran 2 : logique (1707,0,1707,960) à 150 % → physique (2560,0,...).
    ecran1 = _FauxEcran(0, 0, 1707, 960, 1.5)
    ecran2 = _FauxEcran(1707, 0, 1707, 960, 1.5)
    ecrans = [ecran1, ecran2]

    # mss émet la géométrie PHYSIQUE de l'écran 2.
    choisi = _ecran_pour_rect_physique((2560, 0, 2560, 1440), ecrans)
    assert choisi is ecran2

    # Et l'écran 1 physique (left=0) doit choisir l'écran 1.
    assert _ecran_pour_rect_physique((0, 0, 2560, 1440), ecrans) is ecran1


def test_le_rect_physique_sans_ecran_renvoie_none():
    """Liste d'écrans vide (headless) : pas de crash, on renvoie None."""
    from keraconte.overlay import _ecran_pour_rect_physique

    assert _ecran_pour_rect_physique((0, 0, 100, 100), []) is None


def test_un_timer_perime_ne_ferme_pas_le_cadre_recent(app):
    """Le timer d'un flash remplacé ne doit PAS fermer le cadre suivant.

    Deux flashs rapprochés : le 2e remplace le 1er. Quand le timer du 1er échoit,
    « _fermer_flash(cadre1) » ne doit rien faire — cadre1 n'est plus l'actif —
    sinon le 2e cadre disparaîtrait trop tôt. Même garde que la génération audio.
    """
    overlay = _overlay(PlayerState(), nb_ecrans=2)
    overlay.flash_source.emit((0, 0, 100, 100))
    cadre1 = overlay._cadre
    overlay.flash_source.emit((50, 50, 100, 100))  # remplace cadre1
    cadre2 = overlay._cadre
    assert cadre2 is not cadre1
    # Le timer PÉRIMÉ de cadre1 échoit : il ne doit pas toucher cadre2.
    overlay._fermer_flash(cadre1)
    assert overlay._cadre is cadre2  # le cadre récent survit


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


def test_les_boutons_ne_sont_pas_un_carre_qui_gonfle_la_fenetre(app):
    """La taille des boutons est figée, mais RECTANGULAIRE (large > haut).

    Pour compacter la barre on borne min ET max des boutons (largeur ET hauteur).
    Le bug historique, lui, figeait la rangée à un CARRÉ du plus grand côté
    (« setFixedSize(cote, cote) ») : le « sizeHint » d'un QPushButton étant bien
    plus large que haut, ce carré prenait la largeur (~80) comme hauteur et
    gonflait la fenêtre. Ici on fige à des valeurs choisies, plus PETITES que le
    naturel et toujours plus larges que hautes — la fenêtre rétrécit, elle ne
    gonfle pas. On vérifie ce contrat (largeur > hauteur), pas « min != max ».
    """
    # Le ✕ est EXCLU : posé dans son coin façon bouton-fenêtre, il porte son
    # propre setFixedSize (petit carré légitime, hors rangée).
    overlay = _overlay(PlayerState())
    boutons = [
        overlay.bouton_pause,
        overlay.bouton_stop,
        overlay.bouton_reprise,
        overlay.bouton_moins,
        overlay.bouton_plus,
        overlay.bouton_source,
    ]
    for bouton in boutons:
        # Plus large que haut : pas le carré du plus grand côté qui gonflait la
        # fenêtre. Et hauteur bien sous le sizeHint naturel (~29 px).
        assert bouton.maximumWidth() > bouton.maximumHeight()
        assert bouton.maximumHeight() < 29


def test_les_boutons_sont_compacts(app):
    """Les boutons sont resserrés autour de leur glyphe, pas au plancher Qt.

    Un QPushButton d'un seul caractère prend ~80 px de large par défaut (padding
    horizontal du style Qt), alors que le glyphe fait ~11 px : 80 px, c'est
    surtout du vide. Demandé pour compacter la barre, on force une largeur de
    base bien plus petite (glyphe + petit padding), qui suit ensuite l'échelle.
    On vérifie que la largeur figée reste franchement sous le plancher, sans
    passer sous une cible de clic raisonnable.
    """
    overlay = _overlay(PlayerState())
    overlay.widget.adjustSize()
    for bouton in [
        overlay.bouton_pause,
        overlay.bouton_stop,
        overlay.bouton_reprise,
        overlay.bouton_moins,
        overlay.bouton_plus,
        overlay.bouton_source,
    ]:
        # Largeur AFFICHÉE (pas seulement le minimumWidth) : le sizeHint de 80 px
        # tire la largeur réelle si on ne borne pas aussi le maximum. Nettement
        # sous le plancher de 80 px, mais assez large pour cliquer.
        assert 30 <= bouton.width() <= 50


def test_la_barre_a_des_marges_verticales_fines(app):
    """Les marges haut/bas de la barre sont resserrées, sans toucher aux boutons.

    Par défaut le QHBoxLayout pose 11 px de marge en haut ET en bas : la barre
    fait ~61 px alors que les boutons n'en font que ~29. Demandé pour l'affiner,
    on réduit ces marges verticales — les boutons GARDENT leur taille et leur
    forme, seule la bande autour rétrécit. On vérifie que la barre serre les
    boutons de près (marge verticale totale faible), pas la hauteur des boutons.
    """
    overlay = _overlay(PlayerState())
    overlay.widget.adjustSize()
    hauteur_barre = overlay.widget.sizeHint().height()
    hauteur_bouton = overlay.bouton_pause.sizeHint().height()
    # La barre ne dépasse le plus grand bouton que d'une marge fine. Avec les
    # marges par défaut (11 px h/b) l'écart valait 32 px ; resserrées, il tombe
    # bien plus bas. Garde-fou contre le retour de la bande vide.
    assert hauteur_barre - hauteur_bouton <= 20


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

    from keraconte.overlay import ECHELLE_MAX

    overlay = _overlay(PlayerState())
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    assert overlay._echelle == ECHELLE_MAX


def test_la_poignee_de_taille_reduit_puis_borne_au_minimum(app):
    """Glisser vers l'intérieur réduit l'échelle, sans passer sous ECHELLE_MIN."""
    from PySide6.QtCore import QPoint

    from keraconte.overlay import ECHELLE_MAX, ECHELLE_MIN

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


def test_les_boutons_restent_rectangulaires_meme_a_grande_echelle(app):
    """À échelle max, les boutons restent RECTANGULAIRES (large > haut).

    On borne largeur ET hauteur des boutons (× échelle) pour compacter la barre,
    mais à des valeurs choisies plus larges que hautes — jamais le CARRÉ du plus
    grand côté (« setFixedSize(cote, cote) ») qui avait gonflé la fenêtre. Le
    test garde ce contrat même à échelle maximale : chaque bouton demeure plus
    large que haut, donc la barre grandit sans devenir un pavé.
    """
    from PySide6.QtCore import QPoint

    overlay = _overlay(PlayerState())
    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    # ✕ exclu : hors rangée, hors échelle, seul à porter un « setFixedSize ».
    boutons = [
        overlay.bouton_pause,
        overlay.bouton_stop,
        overlay.bouton_reprise,
        overlay.bouton_moins,
        overlay.bouton_plus,
        overlay.bouton_source,
    ]
    for bouton in boutons:
        assert bouton.maximumWidth() > bouton.maximumHeight()


def test_la_croix_ne_suit_pas_l_echelle_de_police(app):
    """Le ✕ est exclu de « _boutons_echelle » : il ne grandit pas au resize.

    Il vit dans la colonne du coin haut-droit (au-dessus de la poignée ◢), sur
    la même rangée, mais garde une taille fixe façon bouton-fenêtre. On vérifie
    l'exclusion de la liste d'échelle, pas la géométrie, qui dépend du
    compositeur en offscreen.
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

    from keraconte.overlay import ECHELLE_MAX

    overlay = _overlay(PlayerState())
    largeur_depart = overlay.bouton_fermer.minimumWidth()

    overlay.poignee_taille.mousePressEvent(_FauxEvenement(QPoint(200, 200)))
    overlay.poignee_taille.mouseMoveEvent(_FauxEvenement(QPoint(9000, 9000)))

    assert overlay._echelle == ECHELLE_MAX  # la barre a bien grandi à fond
    assert overlay.bouton_fermer.minimumWidth() == largeur_depart
    # Taille FIXE (petit carré) : min == max. C'est ce contrat, absent du
    # « minimumWidth » ci-dessus (qui passerait sans setFixedSize), qui garantit
    # que le ✕ ne s'étire jamais.
    assert overlay.bouton_fermer.minimumSize() == overlay.bouton_fermer.maximumSize()


def test_l_overlay_ne_vole_jamais_le_focus_au_jeu(app):
    """Vu en jeu (Windows) : le curseur scintillait plusieurs fois par seconde.

    Une fenêtre « always-on-top » qui accepte l'activation fait reperdre le
    premier plan au jeu en boucle : Dofus le reprend, l'overlay le lui vole,
    et le curseur clignote. Les deux attributs ci-dessous disent à Qt de
    montrer et de garder la barre SANS jamais l'activer.
    """
    from PySide6.QtCore import Qt

    overlay = _overlay(PlayerState())
    assert overlay.widget.testAttribute(Qt.WA_ShowWithoutActivating)
    assert overlay.widget.windowFlags() & Qt.WindowDoesNotAcceptFocus


def test_le_cadre_de_flash_ne_vole_jamais_le_focus(app):
    """Le cadre apparaît PENDANT le jeu : lui non plus ne doit rien activer."""
    from PySide6.QtCore import Qt

    from keraconte.overlay import FlashCadre

    cadre = FlashCadre(0, 0, 100, 100)
    assert cadre.testAttribute(Qt.WA_ShowWithoutActivating)
    assert cadre.windowFlags() & Qt.WindowDoesNotAcceptFocus


def test_le_bouton_console_bascule_l_affichage(app):
    """Le ▤ montre puis recache la console (Windows).

    La console reste construite dans l'exe (« console=True » : la CI lit la
    sortie de --test), mais elle est masquée au démarrage. Ce bouton la rend
    consultable à la demande.
    """
    from keraconte import console as module_console

    appels = []
    overlay = _overlay(PlayerState(), console_disponible=True)
    with mock.patch.object(module_console, "montrer", lambda v: appels.append(v) or v):
        overlay.on_console()
        overlay.on_console()
    assert appels == [True, False]


def test_sans_console_le_bouton_est_absent(app):
    """Sous Linux (ou sans console attachée), pas de bouton qui ne ferait rien."""
    overlay = _overlay(PlayerState(), console_disponible=False)
    assert overlay.bouton_console is None
