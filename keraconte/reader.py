"""Boucle de lecture : orchestre détection, OCR et synthèse d'une image.

Plateforme-AGNOSTIQUE : ne connaît que « handle(frame) », qui reçoit une image
BGR (np.ndarray) et décide quoi lire. La CAPTURE (portail/PipeWire/GStreamer
sous Linux, mss ailleurs) vit dans un backend séparé (voir « capture_factory »)
qui appelle « handle » — c'est la frontière du portage multi-plateforme. Ce
module ne tire aucune dépendance système Linux : « import keraconte »
réussit sans python-gobject ni dbus (Windows/macOS).
"""

import re
import time

from keraconte.detection import (
    bubble_still_there,
    find_bubbles,
    find_dialog_box,
)
from keraconte.engines import build_engine
from keraconte.genre import canal_pour, decider_genre
from keraconte.playback import player_state
from keraconte.speaker import Speaker
from keraconte.speed import Vitesse
from keraconte.text import clean, clearest, same_dialog
from keraconte.trace import trace as _trace


CLOSED_AFTER = 2  # images sans bulle avant de couper la voix
# Une réplique achevée se termine par une ponctuation forte (« clean » a déjà
# coupé après la dernière). Un texte qui n'en a pas est une lecture saisie en
# chemin : c'est le seul garde-fou du rattrapage de « pending ».
FIN_DE_PHRASE = re.compile(r"[.!?…*][\s»\"']*$")


class Reader:
    def __init__(self, args):
        self.args = args
        # Vitesse partagée : le moteur la lit à chaque réplique, l'overlay la
        # mute via ses boutons +/-. Créée ici pour la donner aux deux.
        self.vitesse = Vitesse(args.speed)
        self.speaker = Speaker(lambda: build_engine(args, self.vitesse))
        self.speaker.start()
        self.last_text = None
        # Position de la dernière bulle lue : sert à savoir, quand l'OCR
        # redevient muet, si c'est toujours elle qui est à l'écran.
        self.last_box = None
        self.last_seen = 0.0
        self.missing = 0
        # Texte vu à l'image précédente, pas encore lu : on attend de voir
        # s'il grandit encore avant de le confier à la synthèse.
        self.pending = []

    def handle(self, frame):
        # Stoppé : on débraye l'analyse. La voix a déjà été coupée par le
        # bouton ■ (state.stop() + silence()). En pause, au contraire, on
        # continue : l'analyse doit repérer un nouveau dialogue, qui reprendra
        # le dessus et lèvera la pause.
        if player_state.arrete:
            return
        # Segmenter une seule fois par image : « find_dialog_box » et, en
        # l'absence de texte, « bubble_still_there » travaillent sur la même
        # image. Sans ce partage, « find_bubbles » (morphologie pleine image,
        # ~6–50 ms) tournait deux fois sur chaque image sans dialogue.
        _t0 = time.perf_counter()
        boxes, _ = find_bubbles(frame)
        _trace(f"segmentation : {(time.perf_counter() - _t0) * 1000:.0f}ms | {len(boxes)} boxe(s)")
        text, box = find_dialog_box(frame, boxes)
        if not text:
            revue = bubble_still_there(frame, self.last_box, boxes)
            _trace(
                f"image SANS texte | bulle_encore_là={revue} "
                f"| missing={self.missing} | last_box={self.last_box}"
            )
            # Ne couper que si la bulle a vraiment quitté l'écran. L'OCR
            # échoue régulièrement sur une bulle bien présente — texte en
            # cours d'affichage, rafraîchissement — et couper là-dessus
            # arrêtait la voix au milieu d'une réplique qui n'avait pas
            # changé, sans jamais reprendre puisque le texte au retour est
            # reconnu comme déjà lu. On vérifie que c'est bien LA bulle lue
            # qui est encore là, et non le décor : le chat et la barre de
            # sorts ressemblent à des bulles, mais n'occupent pas sa place.
            if revue:
                return
            # Deux images sans bulle avant de couper. À --fps 4 cela fait une
            # demi-seconde : assez pour absorber un raté de détection isolé
            # (find_bubbles peut manquer une image sous bruit fort), assez
            # court pour suivre le geste de fermeture. L'égalité fait couper
            # une seule fois, pas à chaque image absente au-delà.
            self.missing += 1
            if self.missing == CLOSED_AFTER:
                # Un texte encore en attente est sur le point d'être jeté : la
                # bulle a disparu, la deuxième image qui l'aurait confirmé ne
                # viendra jamais. Vu en jeu (Affreudite, fond très contrasté) :
                # « find_bubbles » ne dégageait la bulle qu'une image sur dix,
                # le dialogue entier était vu une fois puis effacé sans avoir
                # été dit. À cet instant le choix n'est plus « lire tôt ou lire
                # juste » — le portail à deux images n'a plus rien à arbitrer —
                # mais « lire ou ne rien lire du tout ».
                self._dire_le_texte_en_attente()
                _trace(f">>> SILENCE (bulle absente {CLOSED_AFTER} images) : coupe la voix")
                self.speaker.silence()
                # « last_text » survit exprès. Trois images sans bulle ne
                # prouvent pas que le joueur a fermé quoi que ce soit, et
                # effacer la mémoire faisait relire le dialogue en entier au
                # retour — quatre fois pour une réplique un peu longue. C'est
                # « repeat_after » qui autorise une relecture, pas l'oubli.
                self.pending = []
                # « last_box », lui, n'a plus lieu d'être : la bulle est bel
                # et bien partie. Le garder ferait qu'une bulle d'un autre PNJ
                # tombant à la même place (l'OCR clignant à sa première image)
                # passerait pour l'ancienne, et la coupure suivante manquerait.
                self.last_box = None
            return
        _trace(f"image AVEC texte ({len(text)} car.) | box={box}")
        self.missing = 0
        # La bulle est là : on retient sa place, même si le texte n'est pas
        # encore lu (il s'écrit peut-être encore). C'est ce repère qui, à
        # l'image suivante où l'OCR se tait, dira que la bulle est toujours là.
        self.last_box = box
        text = clean(text)
        now = time.time()
        # Même dialogue tant qu'il reste affiché : ne pas relire en boucle.
        # La comparaison est tolérante, car l'OCR fait varier quelques
        # lettres d'une image à l'autre sans que la réplique change.
        if (
            self.last_text is not None
            and same_dialog(text, self.last_text)
            and now - self.last_seen < self.args.repeat_after
        ):
            self.last_seen = now
            return
        # Le jeu n'écrit PAS sa réplique progressivement : la bulle s'affiche
        # d'un coup. C'est l'OCR qui la saisit en chemin — une version tronquée
        # (dernière ligne ratée) à une image, « ...apaiser le molosse. », puis
        # le texte complet à la suivante. Lire la première donnerait un dialogue
        # amputé dont la fin ne serait jamais dite, et chaque état intermédiaire
        # passait pour une nouvelle réplique. On accumule donc les variantes tant
        # que le texte grandit, et l'on ne parle qu'une fois qu'il s'est posé.
        if self.pending and same_dialog(text, self.pending[-1]):
            self.pending.append(text)
        else:
            self.pending = [text]
            return
        # Encore en train de s'écrire : attendre l'image suivante.
        if len(text) > max(len(seen) for seen in self.pending[:-1]):
            _trace(
                f"pending: encore en croissance ({len(text)} car., "
                f"{len(self.pending)} variante(s))"
            )
            return
        self._dire(clearest(*self.pending), len(self.pending), now)

    def _dire_le_texte_en_attente(self):
        """Lit le texte en attente au lieu de le jeter, s'il paraît complet.

        Appelé au seul moment où « pending » serait perdu. Un fragment sans
        ponctuation finale est une lecture d'OCR saisie en chemin (mémoire
        « texte-progressif ») : le taire reste le bon choix, c'est exactement ce
        que le portail à deux images protège. Mais un texte qui se termine
        proprement et qu'aucune image ne viendra plus confirmer doit être dit,
        sans quoi la réplique est perdue en silence.
        """
        if not self.pending:
            return
        text = clearest(*self.pending)
        if not FIN_DE_PHRASE.search(text):
            _trace(f"pending jeté : texte tronqué ({len(text)} car.)")
            return
        # Même garde de relecture que le chemin normal : sans elle, une réplique
        # déjà dite repartirait en lecture à la fermeture de sa propre bulle.
        now = time.time()
        if (
            self.last_text is not None
            and same_dialog(text, self.last_text)
            and now - self.last_seen < self.args.repeat_after
        ):
            return
        _trace(f"RATTRAPAGE : texte vu une seule fois, dit avant d'être jeté")
        self._dire(text, len(self.pending), now)

    def _dire(self, text, images_vues, now):
        """Confie le texte à la synthèse et note qu'il a été lu.

        Le genre du PNJ est décidé ICI, une fois par réplique — jamais par
        image : la voix ne change pas en cours de phrase quand l'OCR cligne
        (invariant ADR-0001). Sans signal sûr, « canal_pour » rend le canal
        masculin : le comportement d'avant, à l'identique.
        """
        self.pending = []
        self.last_text = text
        self.last_seen = now
        genre, source = decider_genre(text)
        _trace(
            f">>> SAY : lance la lecture ({len(text)} car., "
            f"posé après {images_vues} image(s)) "
            f"| genre={genre or 'abstention'} ({source})"
        )
        print(f"\n> {text}", flush=True)
        self.speaker.say(text, canal_pour(genre))
