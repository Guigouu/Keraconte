"""Overlay de contrôle : petite fenêtre flottante, always-on-top, 3 boutons.

Dépend de « state » : un clic écrit une transition dans PlayerState, rien de
plus (l'overlay ne touche jamais directement la capture ni l'audio). Le stop
appelle en plus un callback « couper » pour arrêter la voix en cours.

PySide6 est importé tardivement (à la construction) : le module doit rester
importable pour les tests même hors contexte Qt, et Qt est une dépendance
lourde qu'on ne charge qu'au lancement de l'interface.
"""

from quest_reader.state import Etat


def _fenetre_deplacable():
    """Fabrique la classe de fenêtre, tardivement (Qt importé ici).

    Sans bordure, Qt ne déplace pas la fenêtre : le glisser se fait à la main.
    On mémorise au clic l'écart entre le curseur et le coin, puis on recolle
    ce coin au curseur à chaque mouvement — la fenêtre suit sans sauter.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    class Fenetre(QWidget):
        def __init__(self):
            super().__init__()
            self._prise = None  # écart curseur↔coin au clic, ou None au repos

        def mousePressEvent(self, evenement):
            if evenement.button() is Qt.LeftButton:
                self._prise = (
                    evenement.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )

        def mouseMoveEvent(self, evenement):
            if self._prise is not None:
                self.move(evenement.globalPosition().toPoint() - self._prise)

        def mouseReleaseEvent(self, evenement):
            self._prise = None

    return Fenetre


class Overlay:
    """Trois boutons — ‖ ■ ▶ — qui pilotent l'état de lecture.

    N'hérite pas de QWidget au niveau module (Qt importé tardivement) : la
    vraie fenêtre est construite dans « __init__ ». Les méthodes on_* sont
    testables sans affichage réel.
    """

    def __init__(self, state, couper):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout, QPushButton

        self.state = state
        self.couper = couper

        self.widget = _fenetre_deplacable()()
        self.widget.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        disposition = QHBoxLayout(self.widget)

        self.bouton_pause = QPushButton("‖")
        self.bouton_stop = QPushButton("■")
        self.bouton_reprise = QPushButton("▶")
        self.bouton_pause.clicked.connect(self.on_pause)
        self.bouton_stop.clicked.connect(self.on_stop)
        self.bouton_reprise.clicked.connect(self.on_reprise)
        for bouton in (self.bouton_pause, self.bouton_stop, self.bouton_reprise):
            disposition.addWidget(bouton)

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

    def _rafraichir(self):
        """Grise le bouton correspondant à l'état courant."""
        etat = self.state.etat
        self.bouton_pause.setEnabled(etat is not Etat.EN_PAUSE)
        self.bouton_stop.setEnabled(etat is not Etat.ARRETE)
        self.bouton_reprise.setEnabled(etat is not Etat.ACTIF)

    def show(self):
        self.widget.show()
