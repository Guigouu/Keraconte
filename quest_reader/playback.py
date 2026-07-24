"""Lecture des sons synthétisés, interruptible depuis un autre fil (feuille :
aucun import du package). Expose une instance unique « playback » que les
moteurs appellent et que la capture interrompt.
"""

import subprocess
import threading


class Playback:
    """Joue les sons, et sait les interrompre depuis un autre fil.

    « paplay » bloque jusqu'à la fin du fichier : pour couper la voix quand
    le joueur ferme le dialogue, il faut tuer le processus. L'ordre vient du
    fil de capture, la lecture tourne dans le fil « Speaker », d'où le
    verrou — sans lui, un arrêt tombant juste avant un « Popen » laisserait
    partir le son qu'il devait empêcher.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.stopped = False

    def play(self, path):
        with self.lock:
            if self.stopped:
                return
            self.current = subprocess.Popen(
                ["paplay", path], stderr=subprocess.DEVNULL
            )
        self.current.wait()
        with self.lock:
            self.current = None

    def stop(self):
        """Coupe le son en cours et refuse les suivants."""
        with self.lock:
            self.stopped = True
            if self.current is not None:
                self.current.terminate()

    def resume(self):
        """Rouvre la lecture, à l'apparition d'un nouveau dialogue."""
        with self.lock:
            self.stopped = False


# Instance unique : les moteurs l'appellent, la capture l'interrompt.
playback = Playback()


def play_wave(path):
    playback.play(path)
