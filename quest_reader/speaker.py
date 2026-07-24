"""Fil de synthèse : dépile les dialogues et les fait dire par le moteur.

Le moteur est reçu en paramètre (construit ici, dans le fil qui peut
attendre le chargement). Dépend de « playback » (pour couper) et de « text »
(pour séparer narration et dialogue).
"""

import queue
import sys
import threading

from quest_reader.playback import playback
from quest_reader.text import split_narration


class Speaker(threading.Thread):
    """Synthétise dans un thread pour ne pas bloquer la capture.

    Le moteur est construit ici, et non par l'appelant : charger un modèle
    prend du temps, et ce fil est justement celui qui peut attendre.
    """

    daemon = True

    # Le dialogue en cours et trois qui attendent : de quoi enchaîner une
    # conversation sans rien perdre. Au-delà, la lecture a tant de retard
    # sur l'écran que le joueur est déjà ailleurs.
    #
    # Deux ne suffisaient pas : XTTS met plusieurs secondes par réplique, et
    # « lecture en retard » sautait des dialogues d'un échange normal.
    BACKLOG = 4

    def __init__(self, build_engine):
        super().__init__()
        self.queue = queue.Queue(maxsize=self.BACKLOG)
        self.build_engine = build_engine

    def run(self):
        engine = self.build_engine()
        while True:
            segments = self.queue.get()
            if segments is None:
                return
            for narration, part in segments:
                # Le dialogue a pu se fermer entre deux segments : ne pas
                # entamer la didascalie d'une bulle qui n'est plus là.
                if playback.stopped:
                    break
                try:
                    engine.speak(part, narration)
                except Exception as error:
                    # Mieux vaut un dialogue amputé qu'une partie interrompue.
                    print(f"synthèse impossible : {error}", file=sys.stderr)

    def silence(self):
        """Coupe la voix et jette ce qui restait à dire."""
        playback.stop()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def say(self, text):
        # Un nouveau dialogue lève l'interdiction posée par « silence ».
        playback.resume()
        try:
            self.queue.put_nowait(split_narration(text))
        except queue.Full:
            # Jamais bloquer ici : cet appel vient du fil de capture. Le
            # chargement de XTTS dure 83 s, pendant lesquelles « run » ne
            # dépile rien ; une file sans limite y accumulait tout ce que
            # l'écran affichait, puis le synthétisait en rafale — de quoi
            # remplir la machine. Mieux vaut sauter un dialogue périmé.
            print("lecture en retard : dialogue ignoré", file=sys.stderr)

    def stop(self, timeout=5):
        """Arrête le fil et attend sa fin avant que l'interpréteur ferme.

        Sans cette attente, le fil « daemon » survit au Ctrl+C et rappelle
        espeak alors que ses dossiers temporaires sont déjà détruits :
        « [Errno 2] libespeak-ng.so », une fois par élément restant.
        """
        # Purger d'abord : sinon l'arrêt attend que toute la file soit lue.
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.queue.put(None)
        # Borné : une lecture bloquée ne doit pas retenir la fermeture.
        self.join(timeout)
