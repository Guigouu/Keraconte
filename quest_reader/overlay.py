"""Overlay de contrôle : petite fenêtre flottante, always-on-top, 3 boutons.

Dépend de « state » : un clic écrit une transition dans PlayerState, rien de
plus (l'overlay ne touche jamais directement la capture ni l'audio). Le stop
appelle en plus un callback « couper » pour arrêter la voix en cours.

PySide6 est importé tardivement (à la construction) : le module doit rester
importable pour les tests même hors contexte Qt, et Qt est une dépendance
lourde qu'on ne charge qu'au lancement de l'interface.
"""

from quest_reader.state import Etat

# Bornes de l'échelle de taille de la barre, comme la vitesse a MIN/MAX. À
# 1.0 la barre est à sa taille naturelle ; on descend un peu (0.8) et on monte
# jusqu'à 2.5 (au-delà, la barre mange l'écran). SENSIBILITE convertit les
# pixels glissés (SOMME x+y du déplacement diagonal) en pas d'échelle : à
# 0.002, ~250 px de diagonale (250 en x + 250 en y = 500 unités) font passer
# de 1.0 à 2.0 — un geste franc sans que la poignée saute d'un bout à l'autre.
ECHELLE_MIN = 0.8
ECHELLE_MAX = 2.5
SENSIBILITE = 0.002


def _borner_echelle(valeur):
    """Ramène l'échelle dans [ECHELLE_MIN, ECHELLE_MAX], arrondie à deux
    décimales (même anti-dérive que « speed._borner »)."""
    return round(max(ECHELLE_MIN, min(ECHELLE_MAX, valeur)), 2)


def _poignee_taille(overlay):
    """Fabrique une poignée qui redimensionne la barre, tardivement (Qt ici).

    Miroir de « _poignee_deplacement », même piège : le glisser DOIT être porté
    par la poignée elle-même (Qt route les « mouseMove » vers le widget du
    « mousePress »). On mappe le glisser en ABSOLU — on ancre au press l'échelle
    et la position du curseur, puis on recalcule l'échelle depuis l'écart total.
    En incrémental avec écrêtage, dépasser une borne puis revenir « décrocherait »
    la poignée du curseur ; en absolu elle re-mord tout de suite.

    Le déplacement diagonal (x+y) donne le ressenti d'une poignée de coin : tirer
    vers le bas-droite agrandit. Contrairement au déplacement, aucun recours au
    compositeur n'est nécessaire : sous Wayland un client A le droit de se
    redimensionner lui-même (seul « move » lui est interdit).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    class PoigneeTaille(QLabel):
        def __init__(self):
            # « ◢ » (U+25E2, triangle plein bas-droite) : glyphe géométrique et
            # monochrome, présent dans la police — pas un emoji « délavé »
            # comme ➕/➖/🖥 qu'on a dû écarter ailleurs.
            super().__init__("◢")
            self.setToolTip("Glisser pour redimensionner la barre")
            self.setCursor(Qt.SizeFDiagCursor)
            # Sans ça, le QHBoxLayout centre le triangle verticalement : on
            # l'ancre en bas, là où se trouve le « coin » qu'on saisit.
            self.setAlignment(Qt.AlignBottom | Qt.AlignRight)
            # Le glyphe seul ne fait que ~12 px de large et jouxte « ✕ » : rater
            # la poignée de quelques pixels vers la gauche fermerait l'appli en
            # pleine lecture. On élargit la zone de préhension. La largeur suit
            # la police (héritée), donc c'est surtout à petite échelle qu'elle
            # protège ; on ne fige pas la hauteur (le layout gère le vertical).
            self.setMinimumWidth(24)
            self._ancre = None  # (curseur, échelle) au clic, ou None au repos

        def mousePressEvent(self, evenement):
            if evenement.button() is not Qt.LeftButton:
                return
            self._ancre = (
                evenement.globalPosition().toPoint(),
                overlay._echelle,
            )

        def mouseMoveEvent(self, evenement):
            if self._ancre is None:
                return
            curseur_depart, echelle_depart = self._ancre
            ecart = evenement.globalPosition().toPoint() - curseur_depart
            overlay._changer_echelle(
                echelle_depart + (ecart.x() + ecart.y()) * SENSIBILITE
            )

        def mouseReleaseEvent(self, evenement):
            self._ancre = None

    return PoigneeTaille()


def _poignee_deplacement(fenetre):
    """Fabrique une poignée qui déplace la fenêtre, tardivement (Qt ici).

    Le glisser DOIT être porté par la poignée elle-même, pas par la fenêtre :
    Qt envoie les « mouseMove » au widget qui a reçu le « mousePress ». Un
    QLabel nu accepte le press (donc ne le relaie pas à la fenêtre) mais n'a
    pas de handler de mouvement — d'où une zone qui « ne s'attrape pas ». On
    met donc les handlers ici, et l'on déplace « fenetre ».

    On mémorise au clic l'écart entre le curseur et le coin de la fenêtre, puis
    on recolle ce coin au curseur à chaque mouvement — la fenêtre suit sans
    sauter.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    class Poignee(QLabel):
        def __init__(self):
            super().__init__("⠿")
            self.setToolTip("Glisser pour déplacer")
            self._prise = None  # écart curseur↔coin au clic, ou None au repos

        def mousePressEvent(self, evenement):
            if evenement.button() is not Qt.LeftButton:
                return
            # Sous Wayland, un client N'A PAS le droit de positionner ses
            # propres fenêtres : « fenetre.move() » est silencieusement ignoré.
            # « startSystemMove » demande au COMPOSITEUR de mener le glisser —
            # le seul qui en a le droit. Il doit être appelé au PRESS (le
            # serial du grab pointeur doit être frais ; au move il est périmé et
            # le compositeur refuse sans rien dire).
            poignee_fenetre = self.window().windowHandle()
            if poignee_fenetre is not None and poignee_fenetre.startSystemMove():
                return  # le compositeur prend la main, on ne suit plus rien
            # Repli (X11/XWayland, autres OS, ou hors affichage en test) : on
            # suit le curseur à la main, « move() » y fonctionne.
            self._prise = (
                evenement.globalPosition().toPoint()
                - fenetre.frameGeometry().topLeft()
            )

        def mouseMoveEvent(self, evenement):
            if self._prise is not None:
                fenetre.move(evenement.globalPosition().toPoint() - self._prise)

        def mouseReleaseEvent(self, evenement):
            self._prise = None

    return Poignee()


class Overlay:
    """Boutons — ⏸ ⏹ ⏵ − + ⧉ ✕ — pilotent la lecture, la vitesse et la source.

    N'hérite pas de QWidget au niveau module (Qt importé tardivement) : la
    vraie fenêtre est construite dans « __init__ ». Les méthodes on_* sont
    testables sans affichage réel. Les glyphes média Unicode (U+23F8/9/5) sont
    vérifiés présents dans la police : « ⏸ » remplace deux barres collées.
    Pour la vitesse on n'utilise PAS « ➕/➖ » (U+2795/6) : ces points de code
    ont une présentation emoji, que Qt résout vers la police couleur — rendu
    délavé (aspect « grisé ») et métriques différentes des autres boutons. On
    affiche donc « + » et le vrai signe moins « − » (U+2212), et l'on donne à
    toute la rangée une taille uniforme pour que les glyphes ne la fassent pas
    tressauter. Un label entre − et + montre la vitesse courante.

    Une poignée « ◢ » au coin permet de REDIMENSIONNER la barre. On agrandit par
    ÉCHELLE DE POLICE, pas par géométrie : le QHBoxLayout épingle « minimumSize »
    à la somme des « sizeHint » des boutons, donc un resize géométrique ne peut
    pas rétrécir et n'ajouterait que du vide. Grossir la police élargit peu les
    boutons (le style Qt fige leur largeur à ~80 px), on force donc leur largeur
    par « setMinimumWidth(base × échelle) » — jamais « setFixedSize ». La largeur
    fixe du label de vitesse est recalculée à chaque échelle : figée à l'init,
    elle tronquait « 9.9× » dès que la barre grandissait.
    """

    def __init__(self, state, couper, reselectionner, fermer, vitesse):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self.state = state
        self.couper = couper
        # La re-sélection et la fermeture ne sont PAS des transitions d'état de
        # lecture : elles ne passent pas par PlayerState (qui reste le seul
        # découplage de la lecture), mais par des callbacks à part, comme
        # « couper ».
        self.reselectionner = reselectionner
        self.fermer = fermer
        # Vitesse partagée avec le moteur (via le Reader) : les boutons +/- la
        # mutent à chaud, le moteur la relit dès la phrase suivante. Comme la
        # re-sélection, ce n'est PAS une transition d'état de lecture — elle ne
        # passe pas par PlayerState.
        self.vitesse = vitesse

        self.widget = QWidget()
        self.widget.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )

        disposition = QHBoxLayout(self.widget)

        # Poignée de déplacement : sans elle, les boutons couvrent toute la
        # fenêtre et il n'y a aucune zone à saisir. Le glisser est porté par la
        # poignée elle-même (voir « _poignee_deplacement »), pas par la
        # fenêtre — sans quoi le clic sur le label ne déplace rien.
        self.poignee = _poignee_deplacement(self.widget)
        disposition.addWidget(self.poignee)

        self.bouton_pause = QPushButton("⏸")
        self.bouton_stop = QPushButton("⏹")
        self.bouton_reprise = QPushButton("⏵")
        # Boutons de vitesse : ralentir (« − », U+2212) et accélérer (« + »).
        # On évite « ➕/➖ » (U+2795/6), à présentation emoji : Qt les résout
        # vers la police couleur, d'où un rendu délavé et des métriques qui
        # dépareillaient la rangée. Le vrai signe moins est plus lisible que le
        # tiret ASCII.
        self.bouton_moins = QPushButton("−")
        self.bouton_plus = QPushButton("+")
        self.bouton_moins.setToolTip("Ralentir la parole")
        self.bouton_plus.setToolTip("Accélérer la parole")
        # Label de vitesse, entre − et + : sans lui, on ne sait pas à quel
        # débit on est. Largeur fixe (le plus large affichage possible, « 9.9× »)
        # pour que la rangée ne tressaute pas quand le texte change de longueur.
        # La largeur EST recalculée à chaque changement d'échelle (voir
        # « _appliquer_echelle ») : figée une fois à l'init, elle tronquait
        # « 9.9× » dès que la barre grandissait.
        self.label_vitesse = QLabel()
        self.label_vitesse.setAlignment(Qt.AlignCenter)
        # « ⧉ » (deux fenêtres superposées, U+29C9) : « choisir/changer la
        # source ». On évite « ⟳ » (rotation), qui disait « recharger » et
        # prêtait à confusion, et les vrais emoji d'écran/appareil photo
        # (🖥/📷), absents de la police — ils rendraient délavé et dépareillé,
        # comme les ➕/➖ qu'on a dû abandonner.
        self.bouton_source = QPushButton("⧉")
        self.bouton_source.setToolTip("Choisir la fenêtre ou l'écran à lire")
        # Bouton de fermeture : sans lui, seul Ctrl+C dans le terminal quittait.
        # Petit carré fixe, façon ✕ de barre de titre — sinon le sizeHint d'un
        # QPushButton le rend large (~80 px) et le bandeau haut trop épais. Le
        # « setFixedSize » n'est PAS le bug historique (qui figeait TOUTE la
        # rangée de contrôles) : ce bouton est hors rangée et hors échelle, on
        # VEUT qu'il reste petit et constant.
        self.bouton_fermer = QPushButton("✕")
        self.bouton_fermer.setToolTip("Fermer")
        self.bouton_fermer.setFixedSize(22, 22)
        # Glyphe plat, sans fond ni bordure — façon ✕ de barre de titre. Un
        # QPushButton par défaut reste une boîte en relief qui « pèse » à l'œil ;
        # à plat, 22 px retrouvent la taille du ✕ des fenêtres voisines (Konsole)
        # sans le poids visuel de la boîte. Léger fond au survol pour signaler
        # qu'il est cliquable.
        self.bouton_fermer.setFlat(True)
        self.bouton_fermer.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: #b0b0b0; }"
            "QPushButton:hover { background: rgba(255,255,255,0.15);"
            " border-radius: 3px; color: #ffffff; }"
        )
        self.bouton_pause.clicked.connect(self.on_pause)
        self.bouton_stop.clicked.connect(self.on_stop)
        self.bouton_reprise.clicked.connect(self.on_reprise)
        self.bouton_moins.clicked.connect(self.on_moins)
        self.bouton_plus.clicked.connect(self.on_plus)
        self.bouton_source.clicked.connect(self.on_source)
        self.bouton_fermer.clicked.connect(self.on_fermer)
        # Pas de taille forcée : chaque bouton garde son « sizeHint », compact.
        # Une version passée figeait toute la rangée à un carré du plus grand
        # côté — mais le sizeHint d'un QPushButton est bien plus large que haut,
        # et le carré gonflait la fenêtre entière. Les glyphes emoji ➕/➖ étant
        # remplacés par « + » et « − » (qui s'alignent déjà avec ⏸⏹⏵⧉✕),
        # l'uniformisation n'a plus lieu d'être.

        # Ordre visuel de la rangée : commandes, puis − [label] +, puis source.
        disposition.addWidget(self.bouton_pause)
        disposition.addWidget(self.bouton_stop)
        disposition.addWidget(self.bouton_reprise)
        disposition.addWidget(self.bouton_moins)
        disposition.addWidget(self.label_vitesse)
        disposition.addWidget(self.bouton_plus)
        disposition.addWidget(self.bouton_source)

        # Coin droit : une petite colonne ✕ (haut) au-dessus de ◢ (bas), au
        # bout de la MÊME rangée — pas d'étage séparé, qui créait une bande
        # vide pleine largeur. Le ✕ occupe ainsi le vrai coin haut-droit, juste
        # au-dessus de la poignée de resize. Marges/espacement à zéro, sinon on
        # réintroduit la hauteur qu'on cherche justement à retirer.
        self.poignee_taille = _poignee_taille(self)
        coin = QVBoxLayout()
        coin.setContentsMargins(0, 0, 0, 0)
        coin.setSpacing(0)
        coin.addWidget(self.bouton_fermer, alignment=Qt.AlignTop | Qt.AlignRight)
        coin.addWidget(
            self.poignee_taille, alignment=Qt.AlignBottom | Qt.AlignRight
        )
        disposition.addLayout(coin)

        # État de l'échelle de taille. On agrandit la barre par ÉCHELLE DE
        # POLICE, pas par géométrie : le QHBoxLayout épingle « minimumSize » à
        # la somme des « sizeHint », donc un resize géométrique ne peut pas
        # rétrécir et n'ajouterait que du vide. On mémorise la police de départ
        # (multiplier la police courante à chaque pas accumulerait la dérive) et
        # la largeur naturelle de chaque bouton : le style Qt la fige à ~80 px
        # quelle que soit la police, donc grossir la police ne les élargit pas —
        # on force la largeur par « setMinimumWidth(base × échelle) ». JAMAIS
        # « setFixedSize » (qui avait gonflé la fenêtre en carré).
        self._echelle = 1.0
        self._police_base = self.widget.font()
        # Le ✕ n'y figure PAS : posé dans le bandeau haut façon bouton-fenêtre,
        # il garde une taille fixe et ne suit pas l'échelle de la barre.
        self._boutons_echelle = [
            self.bouton_pause,
            self.bouton_stop,
            self.bouton_reprise,
            self.bouton_moins,
            self.bouton_plus,
            self.bouton_source,
        ]
        self._largeurs_base = [b.sizeHint().width() for b in self._boutons_echelle]
        self._appliquer_echelle()  # pose la largeur fixe du label à l'échelle 1

        self._rafraichir()

    def _changer_echelle(self, valeur):
        """Fixe l'échelle (bornée) et réapplique. Appelée par la poignée."""
        nouvelle = _borner_echelle(valeur)
        if nouvelle != self._echelle:
            self._echelle = nouvelle
            self._appliquer_echelle()

    def _appliquer_echelle(self):
        """Met la barre à l'échelle courante : police, largeurs, label.

        On construit la QFont d'échelle et l'on MESURE le label sur ce même
        objet (pas via « label.font() » après coup, qui dépendrait du timing de
        propagation de la police au widget). On force ensuite la largeur des
        boutons — le style les fige sinon — et l'on rafraîchit la géométrie.
        """
        from PySide6.QtGui import QFont, QFontMetrics

        police = QFont(self._police_base)
        # pointSizeF renvoie -1 si la police a été définie en pixels (fontconfig
        # le fait sur certains setups Linux) : on bascule alors sur pixelSize.
        if self._police_base.pointSizeF() > 0:
            police.setPointSizeF(self._police_base.pointSizeF() * self._echelle)
        else:
            police.setPixelSize(round(self._police_base.pixelSize() * self._echelle))
        self.widget.setFont(police)

        largeur_label = QFontMetrics(police).horizontalAdvance("9.9×")
        self.label_vitesse.setFixedWidth(largeur_label)
        for bouton, base in zip(self._boutons_echelle, self._largeurs_base):
            bouton.setMinimumWidth(round(base * self._echelle))

        self.widget.adjustSize()

    def on_plus(self):
        """Accélère la parole d'un pas (effet dès la phrase suivante)."""
        self.vitesse.augmenter()
        self._rafraichir()

    def on_moins(self):
        """Ralentit la parole d'un pas (effet dès la phrase suivante)."""
        self.vitesse.diminuer()
        self._rafraichir()

    def on_pause(self):
        self.state.pause()
        self._rafraichir()

    def on_stop(self):
        # Ordre voulu : d'abord débrayer l'analyse, puis couper la voix.
        self.state.stop()
        self.couper()
        self._rafraichir()

    def on_reprise(self):
        self.state.reprendre()
        self._rafraichir()

    def on_source(self):
        """Rouvre le sélecteur de source (fenêtre ou écran)."""
        self.reselectionner()

    def on_fermer(self):
        """Ferme l'application (arrêt propre orchestré par __main__)."""
        self.fermer()

    def _rafraichir(self):
        """Grise le bouton correspondant à l'état courant, met à jour la vitesse.

        Grise aussi +/− aux bornes de vitesse : au maximum on ne peut plus
        accélérer, au minimum plus ralentir. Rafraîchit enfin le label qui
        affiche le débit courant, appelé à chaque clic +/-.
        """
        etat = self.state.etat
        self.bouton_pause.setEnabled(etat is not Etat.EN_PAUSE)
        self.bouton_stop.setEnabled(etat is not Etat.ARRETE)
        self.bouton_reprise.setEnabled(etat is not Etat.ACTIF)
        self.bouton_plus.setEnabled(not self.vitesse.au_maximum())
        self.bouton_moins.setEnabled(not self.vitesse.au_minimum())
        self.label_vitesse.setText(f"{self.vitesse.valeur:.1f}×")

    def show(self):
        self.widget.show()
