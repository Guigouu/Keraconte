"""Lecture des sons synthétisés, par tranches, interruptible et pausable.

Réécrit paplay (qui jouait un fichier d'un bloc, sans pause) par une lecture
tranche par tranche via sounddevice (PortAudio, multiplateforme). Entre deux
tranches, on consulte la génération (coupure/bascule, mécanisme conservé) et
l'état de pause. Dépend de « state » ; expose les instances uniques
« playback » et « player_state » que les moteurs, l'overlay et la capture
partagent.
"""

import threading
import wave

import numpy as np

from quest_reader.state import PlayerState


TRANCHE_MS = 20  # durée d'une tranche : compromis latence de pause / surcoût.


class Playback:
    """Joue les sons par tranches, sait les couper et les figer.

    Le compteur de génération est INCHANGÉ : couper puis reprendre pour un
    nouveau dialogue incrémente la génération, et un son périmé ne part pas.
    La pause est une couche ajoutée : entre deux tranches, si l'état est
    EN_PAUSE, la boucle attend sur « player_state » sans tenir « self.lock »
    (sinon « bump » — qui prend ce lock — ne pourrait plus couper).
    """

    def __init__(self, state):
        self.lock = threading.Lock()
        self.current = None  # flux sounddevice en cours, ou None
        self.generation = 0
        self.state = state

    def begin(self):
        with self.lock:
            return self.generation

    def bump(self):
        """Ouvre une nouvelle génération et coupe le son en cours."""
        with self.lock:
            self.generation += 1
            if self.current is not None:
                self.current.close()
            return self.generation

    def _lire_wav(self, path):
        """Lit un WAV en tableau (frames, canaux) int16 + fréquence.

        Isolé pour être doublé en test — seul point qui touche le disque.
        """
        with wave.open(path, "rb") as fichier:
            frequence = fichier.getframerate()
            canaux = fichier.getnchannels()
            brut = fichier.readframes(fichier.getnframes())
        echantillons = np.frombuffer(brut, dtype=np.int16).reshape(-1, canaux)
        return echantillons, frequence

    def _ouvrir_sortie(self, frequence, canaux):
        """Ouvre un flux sounddevice. Import tardif : PortAudio peut manquer.

        « import sounddevice » lève OSError à l'import quand PortAudio est
        absent — d'où l'import ici et non au niveau module, sur le modèle de
        torch dans xtts.py. Renvoie un OutputStream déjà démarré.
        """
        import sounddevice

        flux = sounddevice.OutputStream(
            samplerate=frequence, channels=canaux, dtype="int16"
        )
        flux.start()
        return flux

    def play(self, path, generation):
        try:
            echantillons, frequence = self._lire_wav(path)
        except Exception as erreur:
            print(f"lecture audio impossible : {erreur}")
            return
        canaux = echantillons.shape[1]
        taille = max(1, int(frequence * TRANCHE_MS / 1000))

        # Ouverture du flux sous lock (comme le Popen d'avant), pour que
        # « bump » puisse le fermer. La BOUCLE, elle, tourne hors lock.
        # L'ouverture peut échouer (« import sounddevice » lève OSError sans
        # PortAudio ; « OutputStream » sans périphérique) : on le signale et
        # l'app continue, comme le design le demande — sans laisser
        # « self.current » accroché à un flux mort.
        with self.lock:
            if generation != self.generation:
                return
            try:
                flux = self._ouvrir_sortie(frequence, canaux)
            except Exception as erreur:
                print(f"lecture audio impossible : {erreur}")
                return
            self.current = flux
        try:
            for debut in range(0, len(echantillons), taille):
                # Lecture non verrouillée de la génération, comme
                # speaker.py:42 : un nouveau dialogue abandonne la lecture.
                if generation != self.generation:
                    break
                # Pause : on attend, borné, pour rester réactif à une coupure.
                while self.state.en_pause and generation == self.generation:
                    self.state.attendre_reprise(timeout=0.1)
                if generation != self.generation:
                    break
                flux.write(echantillons[debut : debut + taille])
        finally:
            flux.close()
            with self.lock:
                if self.current is flux:
                    self.current = None


# Instances uniques partagées : les moteurs jouent, la capture coupe, l'overlay
# écrit l'état.
player_state = PlayerState()
playback = Playback(player_state)


def play_wave(path, generation):
    playback.play(path, generation)
