"""Lecture des sons synthétisés, interruptible depuis un autre fil (feuille :
aucun import du package). Expose une instance unique « playback » que les
moteurs appellent et que la capture interrompt.
"""

import subprocess
import threading


class Playback:
    """Joue les sons, et sait les interrompre depuis un autre fil.

    « paplay » bloque jusqu'à la fin du fichier : pour couper la voix quand
    le joueur ferme le dialogue ou passe au suivant, il faut tuer le
    processus. Un compteur de génération, plutôt qu'un booléen, évite une
    course : couper puis reprendre pour un nouveau dialogue incrémente la
    génération, et un son d'une génération périmée ne part pas — même si le
    fil « Speaker » n'a pas encore vu le changement.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.generation = 0

    def begin(self):
        """Génération courante, relevée au début d'un énoncé."""
        with self.lock:
            return self.generation

    def bump(self):
        """Ouvre une nouvelle génération et coupe le son en cours.

        Renvoie le nouveau numéro : « say » l'attache à l'énoncé qu'il enfile.
        """
        with self.lock:
            self.generation += 1
            if self.current is not None:
                self.current.terminate()
            return self.generation

    def play(self, path, generation):
        with self.lock:
            if generation != self.generation:
                return
            self.current = subprocess.Popen(
                ["paplay", path], stderr=subprocess.DEVNULL
            )
        self.current.wait()
        with self.lock:
            self.current = None


# Instance unique : les moteurs l'appellent, la capture l'interrompt.
playback = Playback()


def play_wave(path, generation):
    playback.play(path, generation)
