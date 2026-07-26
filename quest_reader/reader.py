"""Boucle de lecture : capture l'écran, détecte la bulle, la lit.

Sommet du DAG : dépend de la détection, du texte, du fil de synthèse et de la
capture. Décode le flux vidéo via Gst et orchestre le tout.
"""

import os
import signal
import sys
import time

import numpy as np

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import dbus.mainloop.glib  # noqa: E402

from quest_reader.capture import ScreenCast, forget_token  # noqa: E402
from quest_reader.detection import (  # noqa: E402
    bubble_still_there,
    find_dialog_box,
)
from quest_reader.engines import build_engine  # noqa: E402
from quest_reader.playback import player_state  # noqa: E402
from quest_reader.speaker import Speaker  # noqa: E402
from quest_reader.speed import Vitesse  # noqa: E402
from quest_reader.text import clean, clearest, same_dialog  # noqa: E402


CLOSED_AFTER = 2  # images sans bulle avant de couper la voix

# Journal de diagnostic, silencieux par défaut. Activé par « QR_DEBUG=1 » dans
# l'environnement, il trace sur stderr le verdict de détection de chaque image
# et chaque décision (say/silence), pour localiser une coupure sans changer le
# comportement. À n'utiliser que pour déboguer en jeu.
_DEBUG = bool(os.environ.get("QR_DEBUG"))


def _trace(message):
    if _DEBUG:
        print(f"[qr] {message}", file=sys.stderr, flush=True)


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
        self.pipeline = None
        self.cast = None
        self.loop = None

    def on_node(self, fd, node_id):
        Gst.init(None)
        # Démonter l'ancien pipeline ICI, et non avant le sélecteur : si le
        # joueur annule la re-sélection, aucun nouveau « on_node » n'arrive et
        # la capture en cours doit survivre. On ne coupe donc l'ancienne source
        # qu'une fois la nouvelle obtenue — sinon deux pipelines resteraient
        # branchés sur « on_sample » et entremêleraient leurs images.
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        # videorate limite l'OCR : le flux monte à 60 fps, on n'en veut qu'un peu.
        # « queue leaky=downstream » est indispensable : l'OCR (250–820 ms/image)
        # est plus lent que le débit, et le « drop » de l'appsink ne suffit pas
        # — les tampons de videoconvert/videorate accumulaient les vieilles
        # images, d'où un retard qui grandissait sans fin (plusieurs minutes) et
        # un décalage d'un dialogue. La queue jette les images ANCIENNES
        # (downstream) dès que l'aval traîne : on traite toujours la plus
        # récente, on suit le direct (retard borné, mesuré ~4 ms au lieu de 4 s
        # accumulées en 6 s).
        self.pipeline = Gst.parse_launch(
            f"pipewiresrc fd={fd} path={node_id} ! videorate ! "
            f"video/x-raw,framerate={self.args.fps}/1 ! videoconvert ! "
            "video/x-raw,format=BGR ! "
            "queue leaky=downstream max-size-buffers=1 ! "
            "appsink name=sink emit-signals=true "
            "max-buffers=1 drop=true sync=false"
        )
        sink = self.pipeline.get_by_name("sink")
        sink.connect("new-sample", self.on_sample)
        self.pipeline.set_state(Gst.State.PLAYING)
        print("Lecture active. Ctrl+C pour arrêter.", flush=True)

    def on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            # Les lignes PipeWire sont alignées : on retire le remplissage
            # ligne par ligne, sans supposer que le pas soit multiple de 3.
            stride = info.size // height
            raw = np.frombuffer(info.data, np.uint8, count=height * stride)
            frame = raw.reshape(height, stride)[:, : width * 3].reshape(
                height, width, 3
            )
        finally:
            buffer.unmap(info)
        self.handle(frame.copy())
        return Gst.FlowReturn.OK

    def handle(self, frame):
        # Stoppé : on débraye l'analyse. La voix a déjà été coupée par le
        # bouton ■ (state.stop() + silence()). En pause, au contraire, on
        # continue : l'analyse doit repérer un nouveau dialogue, qui reprendra
        # le dessus et lèvera la pause.
        if player_state.arrete:
            return
        text, box = find_dialog_box(frame)
        if not text:
            revue = bubble_still_there(frame, self.last_box)
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
        # Dofus écrit sa réplique progressivement, et l'OCR la saisit en
        # chemin : « ...apaiser le molosse. » à une image, la phrase entière
        # à la suivante. Lire la première donnerait un dialogue amputé dont
        # la fin ne serait jamais dite, et chaque état intermédiaire passait
        # pour une nouvelle réplique. On accumule donc les variantes tant que
        # le texte grandit, et l'on ne parle qu'une fois qu'il s'est posé.
        if self.pending and same_dialog(text, self.pending[-1]):
            self.pending.append(text)
        else:
            self.pending = [text]
            return
        # Encore en train de s'écrire : attendre l'image suivante.
        if len(text) > max(len(seen) for seen in self.pending[:-1]):
            return
        text = clearest(*self.pending)
        self.pending = []
        self.last_text = text
        self.last_seen = now
        _trace(f">>> SAY : lance la lecture ({len(text)} car.)")
        print(f"\n> {text}", flush=True)
        self.speaker.say(text)

    def demarrer_capture(self):
        """Lance la capture et rend la boucle GLib prête à tourner.

        SIGINT n'est PAS installé ici : « signal.signal » ne fonctionne que
        sur le thread principal, et cette méthode tourne dans un thread dédié
        (l'overlay Qt tient le thread principal). L'arrêt vient de l'extérieur
        via « self.loop.quit() » (voir __main__).
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.cast = ScreenCast(self.on_node)
        self.cast.start()
        self.loop = GLib.MainLoop()

    def boucler(self):
        """Corps du thread de capture : fait tourner la boucle GLib."""
        try:
            self.loop.run()
        finally:
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
            self.speaker.stop()

    def arreter(self):
        """Demande l'arrêt de la boucle GLib (appelé depuis un autre thread)."""
        if getattr(self, "loop", None) is not None:
            self.loop.quit()

    def demander_reselection(self):
        """Rouvre le sélecteur de source. Appelé depuis le thread Qt.

        La capture vit sur le thread GLib : on ne touche pas au portail depuis
        Qt directement, on POSTE l'action sur la boucle GLib via « idle_add »,
        qui l'exécutera sur le bon thread.
        """
        GLib.idle_add(self._reselectionner)

    def _reselectionner(self):
        """Recrée une session portail pour re-choisir la source (thread GLib).

        On ne détruit PAS l'ancien pipeline ici : c'est « on_node » qui le
        démonte, une fois la nouvelle source obtenue — annuler le sélecteur
        doit laisser la capture en cours intacte. On ferme l'ancienne session
        (sinon collision de chemin d'objet côté portail) et on oublie le jeton
        (sinon le portail réutilise l'ancien choix sans rien demander).
        """
        self.cast.close()
        forget_token()
        self.cast = ScreenCast(self.on_node)
        self.cast.start()
        return False  # ne pas répéter l'idle

    def run(self):
        """Lancement autonome (sans overlay), pour compat/débogage.

        Installe SIGINT ici car on est alors sur le thread principal.
        """
        self.demarrer_capture()
        signal.signal(signal.SIGINT, lambda *_: self.loop.quit())
        self.boucler()
