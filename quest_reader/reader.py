"""Boucle de lecture : capture l'écran, détecte la bulle, la lit.

Sommet du DAG : dépend de la détection, du texte, du fil de synthèse et de la
capture. Décode le flux vidéo via Gst et orchestre le tout.
"""

import signal
import time

import numpy as np

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import dbus.mainloop.glib  # noqa: E402

from quest_reader.capture import ScreenCast  # noqa: E402
from quest_reader.detection import (  # noqa: E402
    bubble_still_there,
    find_dialog_box,
)
from quest_reader.engines import build_engine  # noqa: E402
from quest_reader.playback import player_state  # noqa: E402
from quest_reader.speaker import Speaker  # noqa: E402
from quest_reader.text import clean, clearest, same_dialog  # noqa: E402


CLOSED_AFTER = 2  # images sans bulle avant de couper la voix


class Reader:
    def __init__(self, args):
        self.args = args
        self.speaker = Speaker(lambda: build_engine(args))
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

    def on_node(self, fd, node_id):
        Gst.init(None)
        # videorate limite l'OCR : le flux monte à 60 fps, on n'en veut qu'un peu.
        self.pipeline = Gst.parse_launch(
            f"pipewiresrc fd={fd} path={node_id} ! videorate ! "
            f"video/x-raw,framerate={self.args.fps}/1 ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink name=sink emit-signals=true "
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
            # Ne couper que si la bulle a vraiment quitté l'écran. L'OCR
            # échoue régulièrement sur une bulle bien présente — texte en
            # cours d'affichage, rafraîchissement — et couper là-dessus
            # arrêtait la voix au milieu d'une réplique qui n'avait pas
            # changé, sans jamais reprendre puisque le texte au retour est
            # reconnu comme déjà lu. On vérifie que c'est bien LA bulle lue
            # qui est encore là, et non le décor : le chat et la barre de
            # sorts ressemblent à des bulles, mais n'occupent pas sa place.
            if bubble_still_there(frame, self.last_box):
                return
            # Deux images sans bulle avant de couper. À --fps 4 cela fait une
            # demi-seconde : assez pour absorber un raté de détection isolé
            # (find_bubbles peut manquer une image sous bruit fort), assez
            # court pour suivre le geste de fermeture. L'égalité fait couper
            # une seule fois, pas à chaque image absente au-delà.
            self.missing += 1
            if self.missing == CLOSED_AFTER:
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
        print(f"\n> {text}", flush=True)
        self.speaker.say(text)

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        cast = ScreenCast(self.on_node)
        cast.start()
        loop = GLib.MainLoop()
        signal.signal(signal.SIGINT, lambda *_: loop.quit())
        try:
            loop.run()
        finally:
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
            self.speaker.stop()
