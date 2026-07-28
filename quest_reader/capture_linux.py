"""Backend de capture Linux : portail ScreenCast → PipeWire → GStreamer.

Isole TOUT le plumbing spécifique à Linux (gi/GStreamer, dbus/portail, boucle
GLib) hors de « reader.py ». C'est la frontière du portage : « reader.py » ne
connaît plus que « handle(frame) » ; ce module produit les frames et les lui
transmet via le callback « on_frame ». Importer ce module exige python-gobject
et dbus — présents uniquement sous Linux. La factory (« capture_factory ») ne
l'importe donc que sur cette plateforme, paresseusement.
"""

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import dbus.mainloop.glib  # noqa: E402

import numpy as np  # noqa: E402

from quest_reader.capture import ScreenCast, forget_token  # noqa: E402


class LinuxCapture:
    """Capture l'écran via le portail et alimente « on_frame » en images BGR.

    Reçoit deux callbacks : « on_frame(np.ndarray) » pour chaque image, et
    « on_stop() » exécuté à la fin de la boucle (arrêt propre du Speaker, que
    « reader.py » ne pilote plus lui-même). « args » fournit « fps ».
    """

    def __init__(self, on_frame, args, on_stop=None):
        self.on_frame = on_frame
        self.args = args
        self.on_stop = on_stop
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
        self.on_frame(frame.copy())
        return Gst.FlowReturn.OK

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
            if self.on_stop is not None:
                self.on_stop()

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
