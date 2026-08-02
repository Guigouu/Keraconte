"""État de lecture partagé entre l'overlay, le Reader et le lecteur audio.

Feuille du DAG : aucun import du package. L'overlay ÉCRIT cet état ; le
« Reader » et « playback » le LISENT. C'est le seul point de découplage entre
l'interface, la capture et l'audio — les boutons ne touchent jamais
directement ni la capture ni le son.
"""

import enum
import threading


class Etat(enum.Enum):
    ACTIF = enum.auto()      # lecture normale
    EN_PAUSE = enum.auto()   # voix figée au milieu de la réplique
    ARRETE = enum.auto()     # analyse débrayée, plus rien n'est lu


class PlayerState:
    """Porte l'état de lecture, protégé par un « Condition ».

    Le « Condition » (plutôt qu'un simple lock) sert l'attente de pause :
    « attendre_reprise » dort dessus, et chaque transition le notifie. La
    pause du lecteur audio ne consomme donc pas de CPU en attente active, et
    reprend sans latence.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._etat = Etat.ACTIF

    @property
    def etat(self):
        with self._condition:
            return self._etat

    @property
    def en_pause(self):
        with self._condition:
            return self._etat is Etat.EN_PAUSE

    @property
    def arrete(self):
        with self._condition:
            return self._etat is Etat.ARRETE

    def _transition(self, cible):
        with self._condition:
            self._etat = cible
            self._condition.notify_all()

    def pause(self):
        """‖ : fige la voix. Sans effet si le lecteur est arrêté."""
        with self._condition:
            if self._etat is Etat.ACTIF:
                self._etat = Etat.EN_PAUSE
                self._condition.notify_all()

    def stop(self):
        """■ : débraye l'analyse et coupe la voix."""
        self._transition(Etat.ARRETE)

    def reprendre(self):
        """▶ : réarme depuis une pause OU depuis un arrêt."""
        self._transition(Etat.ACTIF)

    def reactiver(self):
        """Lève la pause SANS ressusciter un arrêt.

        Appelé par « Speaker.say » : une bascule vers un nouveau dialogue
        défige la voix. Mais un lecteur explicitement stoppé ne doit repartir
        que sur ▶ — jamais sur l'apparition d'un dialogue.
        """
        with self._condition:
            if self._etat is Etat.EN_PAUSE:
                self._etat = Etat.ACTIF
                self._condition.notify_all()

    def attendre_reprise(self, timeout):
        """Bloque tant qu'on est en pause, borné par « timeout ».

        Revient immédiatement si l'on n'est pas en pause. Le « timeout » borne
        chaque attente pour que le lecteur audio reste réactif au changement
        de génération (coupure/bascule) même figé en pause.
        """
        with self._condition:
            if self._etat is Etat.EN_PAUSE:
                self._condition.wait(timeout)
