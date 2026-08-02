"""Overlay de contrôle : petite fenêtre flottante, always-on-top, 3 boutons.

Dépend de « state » : un clic écrit une transition dans PlayerState, rien de
plus (l'overlay ne touche jamais directement la capture ni l'audio). Le stop
appelle en plus un callback « couper » pour arrêter la voix en cours.

PySide6 est importé tardivement (à la construction) : le module doit rester
importable pour les tests même hors contexte Qt, et Qt est une dépendance
lourde qu'on ne charge qu'au lancement de l'interface.
"""

from keraconte.state import Etat

# Bornes de l'échelle de taille de la barre, comme la vitesse a MIN/MAX. À
# 1.0 la barre est à sa taille naturelle ; on descend un peu (0.8) et on monte
# jusqu'à 2.5 (au-delà, la barre mange l'écran). SENSIBILITE convertit les
# pixels glissés (SOMME x+y du déplacement diagonal) en pas d'échelle : à
# 0.002, ~250 px de diagonale (250 en x + 250 en y = 500 unités) font passer
# de 1.0 à 2.0 — un geste franc sans que la poignée saute d'un bout à l'autre.
ECHELLE_MIN = 0.8
ECHELLE_MAX = 2.5
SENSIBILITE = 0.002

# Largeur (px, à l'échelle 1) des boutons de contrôle. Un QPushButton d'un seul
# glyphe prend ~80 px par défaut (plancher de padding du style Qt) alors que le
# glyphe fait ~11 px : les 80 px sont surtout du vide. On resserre à cette
# largeur compacte — assez pour entourer le glyphe et rester cliquable — puis on
# la fait suivre l'échelle (× _echelle) comme le reste de la barre.
LARGEUR_BOUTON = 44

# Hauteur (px, à l'échelle 1) des boutons de contrôle. Le « sizeHint » d'un
# QPushButton fait ~29 px de haut : combiné aux marges du layout, la barre
# passait 47 px. On bride la hauteur pour viser une barre ~43 px sans changer la
# forme ni la largeur des boutons. Suit l'échelle (× _echelle) comme la largeur.
HAUTEUR_BOUTON = 26


def _borner_echelle(valeur):
    """Ramène l'échelle dans [ECHELLE_MIN, ECHELLE_MAX], arrondie à deux
    décimales (même anti-dérive que « speed._borner »)."""
    return round(max(ECHELLE_MIN, min(ECHELLE_MAX, valeur)), 2)


def _ecran_pour_rect_physique(rect_physique, ecrans):
    """Retrouve le QScreen dont la géométrie PHYSIQUE matche le rect mss émis.

    mss donne des coordonnées en pixels physiques ; Qt raisonne en pixels
    logiques (géométrie ÷ devicePixelRatio). On reconstruit la géométrie
    physique de chaque écran (« geometry() × devicePixelRatio ») et l'on choisit
    celui dont le coin haut-gauche est le plus proche du (left, top) émis — la
    correspondance d'origine suffit à identifier l'écran, sans dépendre d'un
    arrondi exact de taille. Renvoie None si la liste est vide (headless).

    Isolé du slot pour être testable sans vrai serveur d'affichage : « ecrans »
    est une liste d'objets à « geometry() » et « devicePixelRatio() ».
    """
    left, top, _w, _h = rect_physique
    meilleur, meilleure_dist = None, None
    for ecran in ecrans:
        g = ecran.geometry()
        dpr = ecran.devicePixelRatio()
        phys_x = g.x() * dpr
        phys_y = g.y() * dpr
        dist = abs(phys_x - left) + abs(phys_y - top)
        if meilleure_dist is None or dist < meilleure_dist:
            meilleur, meilleure_dist = ecran, dist
    return meilleur


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
            # On ancre le triangle en bas (là où se trouve le « coin » qu'on
            # saisit) et CENTRÉ horizontalement : dans la colonne du coin, le ✕
            # est juste au-dessus ; un « AlignRight » décalerait le glyphe de la
            # poignée hors de l'axe du ✕ (chacun centré sur une verticale
            # différente). Centrer les deux les aligne parfaitement.
            self.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
            # Le glyphe seul ne fait que ~12 px de large : on élargit la zone de
            # préhension pour ne pas rater la poignée. La largeur suit la police
            # (héritée) ; on ne fige pas la hauteur (le layout gère le vertical).
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

    def __init__(
        self,
        state,
        couper,
        reselectionner,
        fermer,
        vitesse,
        nb_ecrans=None,
        console_disponible=False,
    ):
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
        # Nombre d'écrans physiques, transmis par le backend mss (None si non
        # fourni : backend portail Linux, ou tests). Sert UNIQUEMENT à griser le
        # bouton source quand il n'y a qu'un écran — rien à basculer.
        self.nb_ecrans = nb_ecrans
        # Fenêtre-cadre du retour visuel, vivante seulement pendant le flash.
        self._cadre = None
        # La console existe-t-elle et peut-on la piloter ? (Windows seulement.)
        # Faux sous Linux : le terminal appartient à l'utilisateur, et un bouton
        # sans effet vaut moins que pas de bouton du tout.
        self.console_disponible = console_disponible
        # Masquée au démarrage (voir « console.masquer_au_demarrage ») : l'état
        # de départ du bouton doit dire la même chose.
        self._console_visible = False
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
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            # Ne JAMAIS prendre le focus. Vu en jeu (Windows) : le curseur
            # scintillait plusieurs fois par seconde. Une fenêtre always-on-top
            # qui accepte l'activation dispute sans cesse le premier plan au
            # jeu — Dofus le reprend, la barre le lui revole. Les boutons
            # restent cliquables : un clic agit sans activer la fenêtre.
            | Qt.WindowDoesNotAcceptFocus
        )
        # Le pendant du drapeau ci-dessus pour l'affichage : « show() » ne doit
        # pas non plus activer la barre au démarrage, sinon le jeu perd le
        # premier plan à l'instant où l'overlay apparaît.
        self.widget.setAttribute(Qt.WA_ShowWithoutActivating)

        disposition = QHBoxLayout(self.widget)
        # Marges verticales resserrées (défaut Qt = 11 px en haut ET en bas) : la
        # barre faisait ~61 px pour des boutons de ~29 px, soit 22 px de bande
        # vide. On garde 11 px sur les côtés (l'air horizontal ne gêne pas) et on
        # réduit haut/bas à 2 px : combiné au bridage de la hauteur des boutons
        # (HAUTEUR_BOUTON), la barre vise ~43 px sans changer la forme des boutons.
        disposition.setContentsMargins(11, 2, 11, 2)

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
        # « ▤ » (rectangle rayé, U+25A4) : la console, masquée par défaut mais
        # consultable à la demande (traces QR_DEBUG, messages d'erreur). N'existe
        # QUE s'il y a vraiment une console à piloter — sous Linux, le terminal
        # n'appartient pas à l'application.
        self.bouton_console = None
        if self.console_disponible:
            self.bouton_console = QPushButton("▤")
            self.bouton_console.setToolTip("Afficher la console")
        # Bouton de fermeture : sans lui, seul Ctrl+C dans le terminal quittait.
        # Petit carré fixe, façon ✕ de barre de titre — sinon le sizeHint d'un
        # QPushButton le rend large (~80 px) et le bandeau haut trop épais. Le
        # « setFixedSize » n'est PAS le bug historique (qui figeait TOUTE la
        # rangée de contrôles) : ce bouton est hors rangée et hors échelle, on
        # VEUT qu'il reste petit et constant.
        self.bouton_fermer = QPushButton("✕")
        self.bouton_fermer.setToolTip("Fermer")
        self.bouton_fermer.setFixedSize(24, 22)
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
        if self.bouton_console is not None:
            self.bouton_console.clicked.connect(self.on_console)
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
        if self.bouton_console is not None:
            disposition.addWidget(self.bouton_console)

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
        # Le ▤ suit la même échelle que la rangée (quand il existe) : laissé de
        # côté, il resterait figé à 44 px pendant que ses voisins grandissent.
        if self.bouton_console is not None:
            self._boutons_echelle.append(self.bouton_console)
        # Largeur de base COMPACTE, pas le « sizeHint » (80 px, surtout du vide).
        # On force LARGEUR_BOUTON pour resserrer la barre autour des glyphes ;
        # « _appliquer_echelle » la multiplie ensuite par l'échelle courante.
        self._largeurs_base = [LARGEUR_BOUTON for _ in self._boutons_echelle]
        self._appliquer_echelle()  # pose la largeur fixe du label à l'échelle 1

        # Retour visuel de la source : le backend de capture (autre thread)
        # émet la géométrie du moniteur ciblé. On PASSE PAR UN SIGNAL Qt et non
        # par un appel direct : « flash_source.emit » posté depuis le thread de
        # capture est mis en file par PySide6 et le slot s'exécute sur le thread
        # Qt (le seul autorisé à créer un widget). Un appel direct au widget
        # depuis l'autre thread serait la même faute que fermer un OutputStream
        # inter-thread (segfault) — d'où le pont QObject.
        self._pont = _PontSource()
        self.flash_source = self._pont.flash_source
        self.flash_source.connect(self._montrer_flash)

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
            # On borne min ET max à la largeur compacte : le « sizeHint » (~80 px)
            # tire sinon la largeur réelle vers le plancher du style, malgré le
            # minimumWidth plus petit. La HAUTEUR reste libre → « minimumSize() !=
            # maximumSize() » tient toujours (ce n'est PAS le setFixedSize carré
            # qui gonflait la fenêtre : ici seule la largeur est figée, à une
            # valeur volontairement petite).
            largeur = round(base * self._echelle)
            bouton.setMinimumWidth(largeur)
            bouton.setMaximumWidth(largeur)
            # Hauteur bridée aussi (à HAUTEUR_BOUTON × échelle) pour affiner la
            # barre. On fige donc les DEUX dimensions, mais à des valeurs
            # RECTANGULAIRES choisies (44×26) — ce n'est pas le « setFixedSize
            # carré » du bug historique, qui prenait la largeur (~80) comme
            # hauteur et gonflait la fenêtre. Ici la fenêtre rétrécit.
            hauteur = round(HAUTEUR_BOUTON * self._echelle)
            bouton.setMinimumHeight(hauteur)
            bouton.setMaximumHeight(hauteur)

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

    def on_console(self):
        """Montre ou recache la fenêtre console (Windows).

        Elle est masquée au démarrage : ce bouton la rend consultable quand on
        veut voir les traces, sans imposer une fenêtre noire au joueur le reste
        du temps. On suit l'état RENVOYÉ par « montrer » et non celui qu'on a
        demandé : sans console pilotable, il reste faux et le libellé ne ment
        pas.
        """
        from keraconte import console

        self._console_visible = console.montrer(not self._console_visible)
        self.bouton_console.setToolTip(
            "Masquer la console" if self._console_visible else "Afficher la console"
        )

    def _montrer_flash(self, geometrie):
        """Affiche 2 s un cadre autour du moniteur capturé (slot du thread Qt).

        Reçu via « flash_source » : le backend (autre thread) a émis la
        géométrie, PySide6 a mis l'appel en file, on est donc bien sur le thread
        Qt ici et créer un widget est légal. On remplace tout cadre encore
        affiché (double clic rapide) pour ne pas empiler les fenêtres.
        """
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QGuiApplication

        # mss émet des pixels PHYSIQUES ; QWidget.setGeometry attend des pixels
        # LOGIQUES. Sous Windows à 125/150 % d'échelle, les deux divergent : un
        # écran physique à left=2560 devient logique ~1707, et un cadre posé
        # avec les coordonnées mss atterrirait sur le mauvais écran, voire hors
        # champ. On retrouve donc le QScreen qui correspond au rect physique et
        # on dessine le cadre sur SA géométrie logique.
        ecran = _ecran_pour_rect_physique(geometrie, QGuiApplication.screens())
        if ecran is not None:
            g = ecran.geometry()  # déjà en pixels logiques
            left, top, width, height = g.x(), g.y(), g.width(), g.height()
        else:
            # Aucun écran Qt ne matche (cas dégénéré/headless) : on retombe sur
            # les coordonnées mss brutes — mieux qu'aucun cadre.
            left, top, width, height = geometrie
        if self._cadre is not None:
            self._cadre.close()
        cadre = FlashCadre(left, top, width, height)
        self._cadre = cadre
        cadre.show()
        # Auto-fermeture après 2 s : un flash, pas un cadre permanent. On LIE le
        # cadre visé à la fermeture (« cadre », pas « self._cadre ») : sinon un
        # second flash lancé avant l'échéance remplacerait « self._cadre », et le
        # timer du PREMIER fermerait le SECOND trop tôt. On garde une référence
        # le temps du flash, sinon le GC de Python détruirait le QWidget avant.
        QTimer.singleShot(2000, lambda: self._fermer_flash(cadre))

    def _fermer_flash(self, cadre):
        """Ferme CE cadre s'il est encore l'actif (échéance du QTimer, thread Qt).

        Ne ferme que si « cadre » est toujours le cadre courant : un flash plus
        récent l'a peut-être déjà remplacé (et fermé), auquel cas ce timer périmé
        ne doit toucher à rien — même garde que la génération de « playback ».
        """
        if self._cadre is cadre:
            cadre.close()
            self._cadre = None

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
        # Un seul écran (mss) : rien à basculer, on grise le bouton source pour
        # qu'il ne reste pas cliquable dans le vide. nb_ecrans=None (portail
        # Linux, où re-sélectionner garde du sens) laisse le bouton actif.
        un_seul_ecran = self.nb_ecrans == 1
        self.bouton_source.setEnabled(not un_seul_ecran)
        # Le tooltip ne doit pas promettre ce qu'un bouton grisé ne fera pas.
        self.bouton_source.setToolTip(
            "Un seul écran : rien à changer"
            if un_seul_ecran
            else "Choisir la fenêtre ou l'écran à lire"
        )
        self.label_vitesse.setText(f"{self.vitesse.valeur:.1f}×")

    def show(self):
        self.widget.show()


class _PontSource:
    """Porteur du signal « flash_source », construit tardivement (QObject Qt).

    On ne peut pas mettre un « Signal » sur « Overlay » : ce n'est pas un
    QObject (il COMPOSE un QWidget, il n'en hérite pas). Ce petit pont EST un
    QObject et porte le signal ; « Overlay » expose « .flash_source ». Le
    backend de capture reçoit « flash_source.emit » comme callback : émis depuis
    le thread de capture, PySide6 met la livraison en file jusqu'au thread Qt.
    """

    def __new__(cls):
        from PySide6.QtCore import QObject, Signal

        # QObject/Signal sont importés tardivement (comme le reste de l'overlay)
        # : on fabrique la classe ici pour ne pas exiger PySide6 à l'import du
        # module. Le signal transporte un tuple (left, top, width, height).
        if not hasattr(cls, "_Impl"):

            class _Impl(QObject):
                flash_source = Signal(tuple)

            cls._Impl = _Impl
        return cls._Impl()


EPAISSEUR_CADRE = 6  # bord du cadre de flash, en pixels


def _classe_cadre():
    """Fabrique (une fois) la sous-classe QWidget qui peint le cadre.

    On sous-classe VRAIMENT QWidget et l'on redéfinit « paintEvent » dans la
    classe : monkey-patcher « widget.paintEvent = … » sur une instance nue n'est
    pas garanti d'être dispatché par Qt (le virtuel se résout au niveau classe).
    Import tardif comme le reste de l'overlay ; classe mémoïsée pour ne pas la
    reconstruire à chaque flash.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QWidget

    class _Cadre(QWidget):
        def __init__(self, left, top, width, height):
            super().__init__()
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowTransparentForInput  # cliquable à travers : ne bloque pas le jeu
                # Le cadre surgit PENDANT que le joueur joue : lui non plus ne
                # doit jamais disputer le premier plan au jeu (même cause de
                # scintillement que la barre de contrôles).
                | Qt.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WA_TranslucentBackground)  # fond transparent
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setGeometry(left, top, width, height)

        def paintEvent(self, _event):
            """Dessine le seul cadre : un rectangle creux sur tout le pourtour."""
            peintre = QPainter(self)
            stylo = QPen(QColor(0, 200, 255))  # cyan franc, bien visible
            stylo.setWidth(EPAISSEUR_CADRE)
            peintre.setPen(stylo)
            # Rétréci d'une demi-épaisseur pour que le trait reste DANS la
            # fenêtre (un QPen centre le trait ; sans marge il déborderait).
            demi = EPAISSEUR_CADRE // 2
            peintre.drawRect(
                demi,
                demi,
                self.width() - EPAISSEUR_CADRE,
                self.height() - EPAISSEUR_CADRE,
            )
            peintre.end()

    return _Cadre


def FlashCadre(left, top, width, height):
    """Fenêtre transparente qui dessine un cadre autour d'un moniteur.

    Retour visuel « voilà ce que je capture » : un rectangle vide à bord épais,
    sans fond, cliquable à travers (le jeu dessous reste utilisable), always-on
    -top, sans bordure. Vit ~2 s puis se ferme (piloté par l'overlay via un
    QTimer). Renvoie un QWidget prêt à « show() ».
    """
    return _classe_cadre()(left, top, width, height)
