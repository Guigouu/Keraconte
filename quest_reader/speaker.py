"""Fil de synthèse : dépile les dialogues et les fait dire par le moteur.

Le moteur est reçu en paramètre (construit ici, dans le fil qui peut
attendre le chargement). Dépend de « playback » (pour couper) et de « text »
(pour séparer narration et dialogue).
"""

import queue
import sys
import threading

from quest_reader.playback import playback, player_state
from quest_reader.text import split_narration


class Speaker(threading.Thread):
    """Synthétise dans un thread pour ne pas bloquer la capture.

    Le moteur est construit ici, et non par l'appelant : charger un modèle
    prend du temps, et ce fil est justement celui qui peut attendre.
    """

    daemon = True

    BACKLOG = 1  # un seul énoncé : un nouveau dialogue coupe, il n'empile pas.

    def __init__(self, build_engine):
        super().__init__()
        self.queue = queue.Queue(maxsize=self.BACKLOG)
        self.build_engine = build_engine

    def run(self):
        engine = self.build_engine()
        while True:
            item = self.queue.get()
            if item is None:
                return
            generation, segments = item
            for narration, part in segments:
                # Un nouveau dialogue a pu survenir : ne pas entamer la suite
                # d'un énoncé périmé.
                if generation != playback.generation:
                    break
                try:
                    engine.speak(part, narration, generation)
                except Exception as error:
                    print(f"synthèse impossible : {error}", file=sys.stderr)

    def silence(self):
        """Coupe la voix et jette ce qui restait à dire."""
        playback.bump()
        self._drain()

    def say(self, text):
        # Un nouveau dialogue lève une éventuelle pause (le design veut que
        # la pause « saute » à la bascule) — mais pas un arrêt explicite :
        # « reactiver » ne touche que EN_PAUSE, jamais ARRETE.
        player_state.reactiver()
        # Un nouveau dialogue coupe l'actuel et ouvre sa propre génération.
        generation = playback.bump()
        self._drain()
        try:
            self.queue.put_nowait((generation, split_narration(text)))
        except queue.Full:
            # Jamais bloquer ici : cet appel vient du fil de capture.
            print("lecture en retard : dialogue ignoré", file=sys.stderr)

    def _drain(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def stop(self, timeout=5):
        """Arrête le fil et attend sa fin avant que l'interpréteur ferme.

        Sans cette attente, le fil « daemon » survit au Ctrl+C et rappelle
        espeak alors que ses dossiers temporaires sont déjà détruits :
        « [Errno 2] libespeak-ng.so », une fois par élément restant.
        """
        # Purger d'abord : sinon l'arrêt attend que toute la file soit lue.
        self._drain()
        self.queue.put(None)
        # Borné : une lecture bloquée ne doit pas retenir la fermeture.
        self.join(timeout)
