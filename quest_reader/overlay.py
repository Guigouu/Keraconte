"""Overlay de contrôle : petite fenêtre flottante, always-on-top, 3 boutons.

Dépend de « state » : un clic écrit une transition dans PlayerState, rien de
plus (l'overlay ne touche jamais directement la capture ni l'audio). Le stop
appelle en plus un callback « couper » pour arrêter la voix en cours.

PySide6 est importé tardivement (à la construction) : le module doit rester
importable pour les tests même hors contexte Qt, et Qt est une dépendance
lourde qu'on ne charge qu'au lancement de l'interface.
"""

from quest_reader.state import Etat


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
    """Boutons — ⏸ ⏹ ⏵ − + ⟳ ✕ — pilotent la lecture, la vitesse et la source.

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
    """

    def __init__(self, state, couper, reselectionner, fermer, vitesse):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QPushButton,
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
        self.label_vitesse = QLabel()
        self.label_vitesse.setAlignment(Qt.AlignCenter)
        self.label_vitesse.setFixedWidth(
            QFontMetrics(self.label_vitesse.font()).horizontalAdvance("9.9×")
        )
        self.bouton_source = QPushButton("⟳")
        self.bouton_source.setToolTip("Choisir la fenêtre ou l'écran à lire")
        # Bouton de fermeture : sans lui, seul Ctrl+C dans le terminal quittait.
        self.bouton_fermer = QPushButton("✕")
        self.bouton_fermer.setToolTip("Fermer")
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
        # remplacés par « + » et « − » (qui s'alignent déjà avec ⏸⏹⏵⟳✕),
        # l'uniformisation n'a plus lieu d'être.

        # Ordre visuel : commandes, puis − [label] +, puis source et fermer.
        disposition.addWidget(self.bouton_pause)
        disposition.addWidget(self.bouton_stop)
        disposition.addWidget(self.bouton_reprise)
        disposition.addWidget(self.bouton_moins)
        disposition.addWidget(self.label_vitesse)
        disposition.addWidget(self.bouton_plus)
        disposition.addWidget(self.bouton_source)
        disposition.addWidget(self.bouton_fermer)

        self._rafraichir()

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
