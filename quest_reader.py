#!/usr/bin/env python3
"""Lit à voix haute les dialogues de PNJ de Dofus.

Capture l'écran en continu via le portail ScreenCast (Wayland), détecte la
bulle de dialogue, l'OCRise et la lit avec une voix française.
"""

import argparse
import hashlib
import os
import queue
import re
import signal
import sys
import threading
import time

import cv2
import numpy as np
import pytesseract
import pyttsx3
from PIL import Image

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import dbus  # noqa: E402
import dbus.mainloop.glib  # noqa: E402

TOKEN_FILE = os.path.expanduser("~/.cache/quest-reader/restore-token")

# La bulle est un aplat gris neutre ; le décor du jeu est coloré.
MAX_CHANNEL_SPREAD = 12
VALUE_MIN, VALUE_MAX = 18, 75

# CLOSE 7 sépare le dialogue du bloc de réponses. Un noyau plus large
# soude les deux quand l'écart est serré (vérifié sur deux captures).
OPEN_KERNEL = np.ones((9, 9), np.uint8)
CLOSE_KERNEL = np.ones((7, 7), np.uint8)

MIN_AREA = 40000
MIN_WIDTH = 300
MIN_CHARS = 20

# Le texte de dialogue est blanc sur gris. Mesuré : 2.9 % dans une vraie
# bulle contre 0.1 % pour un bloc d'interface sans texte.
MIN_WHITE_RATIO = 0.008
MAX_WHITE_RATIO = 0.15

# Écart vertical entre la bulle et le bloc de réponses. Mesuré à -16 px :
# les deux blocs se touchent, avec un léger recouvrement.
MAX_REPLY_GAP = 160
MAX_REPLY_OVERLAP = 40
ALIGN_TOLERANCE = 60

# Bordure ignorée à l'OCR, pour écarter les icônes des coins.
MARGIN = 34


def find_dialog(frame):
    """Renvoie le texte de la bulle de dialogue, ou None.

    Le bloc de réponses partage l'aspect de la bulle : on ne garde que le
    bloc le plus haut, qui est toujours le dialogue lui-même.
    """
    height, width = frame.shape[:2]
    blue, green, red = cv2.split(frame.astype(np.int16))
    spread = np.maximum(np.maximum(blue, green), red) - np.minimum(
        np.minimum(blue, green), red
    )
    value = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]

    mask = (
        (spread < MAX_CHANNEL_SPREAD) & (value > VALUE_MIN) & (value < VALUE_MAX)
    ).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, OPEN_KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, CLOSE_KERNEL)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < MIN_AREA or w < MIN_WIDTH:
            continue
        # L'interface de droite touche le bord ; le reste (chat compris)
        # est écarté par l'exigence d'un bloc de réponses apparié.
        if x + w > width * 0.99:
            continue
        boxes.append((y, x, w, h))

    # Un dialogue de PNJ est toujours suivi d'un bloc de réponses juste
    # en dessous. Les panneaux d'interface, eux, sont isolés : exiger la
    # paire écarte les faux positifs.
    boxes.sort()
    for index, (y, x, w, h) in enumerate(boxes):
        replies = next(
            (
                other
                for other in boxes[index + 1 :]
                if is_reply_block((y, x, w, h), other)
            ),
            None,
        )
        if replies is None:
            continue
        region = frame[y : y + h, x : x + w]
        white = (region > 200).all(2).mean()
        if not MIN_WHITE_RATIO <= white <= MAX_WHITE_RATIO:
            continue
        # Pas de rognage : la boîte est parfois déjà serrée sur le texte,
        # et rogner amputerait le dialogue. Les icônes des coins sont
        # écartées ensuite, au nettoyage du texte.
        crop = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
        text = pytesseract.image_to_string(Image.fromarray(crop), lang="fra").strip()
        if len(text) >= MIN_CHARS:
            return text
    return None


def is_reply_block(dialog, candidate):
    """Le bloc candidat est-il la liste de réponses sous ce dialogue ?"""
    dialog_y, dialog_x, dialog_w, dialog_h = dialog
    y, x, w, _ = candidate
    # Les deux blocs se chevauchent parfois de quelques pixels.
    gap = y - (dialog_y + dialog_h)
    if not -MAX_REPLY_OVERLAP <= gap <= MAX_REPLY_GAP:
        return False
    # Les deux blocs partagent le même bord gauche et une largeur voisine.
    if abs(x - dialog_x) > ALIGN_TOLERANCE:
        return False
    return abs(w - dialog_w) <= dialog_w * 0.35


def clean(text):
    """Recolle les lignes et retire les parasites laissés par les icônes."""
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Les icônes de la bulle produisent un préfixe parasite instable d'une
    # image à l'autre : des fragments courts, souvent mêlés de symboles.
    # Le dialogue commence par un vrai mot, donc on démarre là.
    # Les icônes et bordures de la bulle laissent des fragments courts,
    # instables d'une image à l'autre, collés au début et à la fin. Ils
    # imitent des mots, donc on ancre plutôt sur la phrase elle-même :
    # elle ouvre sur une majuscule et se ferme sur une ponctuation.
    # Ces fragments sont des lettres isolées ; une phrase, elle, enchaîne
    # au moins deux mots.
    start = re.search(r"[A-Za-zÀ-ÿ'’-]{3,}[,;:]?\s+[A-Za-zÀ-ÿ'’-]{2,}", text)
    if start:
        text = text[start.start() :]
    # La fin doit suivre un vrai mot : une ponctuation isolée en queue
    # ("\\ ; .") appartient encore au bruit de bordure.
    ends = list(re.finditer(r"[A-Za-zÀ-ÿ0-9’'][.!?…]+", text))
    if ends:
        text = text[: ends[-1].end()]
    return text.strip()


def fingerprint(text):
    """Empreinte tolérante aux caractères parasites de l'OCR.

    Le même dialogue peut être lu avec de légères variations d'une image à
    l'autre : comparer les seules lettres évite de le relire en boucle.
    """
    letters = re.sub(r"[^a-zà-ÿ]", "", text.lower())
    # Ignore les extrémités, où se logent les parasites d'icônes.
    core = letters[8:-8] if len(letters) > 40 else letters
    return hashlib.sha1(core.encode()).hexdigest()


class Speaker(threading.Thread):
    """Lit dans un thread pour ne pas bloquer la capture."""

    daemon = True

    def __init__(self, rate, voice):
        super().__init__()
        self.queue = queue.Queue()
        self.rate = rate
        self.voice = voice

    def run(self):
        engine = pyttsx3.init()
        engine.setProperty("voice", self.voice)
        engine.setProperty("rate", self.rate)
        while True:
            text = self.queue.get()
            if text is None:
                return
            engine.say(text)
            engine.runAndWait()

    def say(self, text):
        self.queue.put(text)


class ScreenCast:
    """Ouvre un flux PipeWire via le portail xdg-desktop-portal.

    Le jeton de restauration évite de redemander l'autorisation à chaque
    lancement : la boîte de dialogue n'apparaît qu'une seule fois.
    """

    def __init__(self, on_node):
        self.on_node = on_node
        self.bus = dbus.SessionBus()
        self.portal = self.bus.get_object(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
        )
        self.session = None
        unique = self.bus.get_unique_name()[1:].replace(".", "_")
        self.sender = unique
        self.counter = 0

    def _request(self, callback):
        self.counter += 1
        token = f"qr{self.counter}"
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        self.bus.add_signal_receiver(
            callback,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=path,
        )
        return token

    def start(self):
        token = self._request(self._on_session)
        self.portal.CreateSession(
            {
                "session_handle_token": "qrsession",
                "handle_token": token,
            },
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_session(self, code, results):
        if code != 0:
            sys.exit("Création de session refusée.")
        self.session = results["session_handle"]
        token = self._request(self._on_sources)
        options = {
            "types": dbus.UInt32(1),  # écrans uniquement
            "multiple": False,
            "handle_token": token,
            "persist_mode": dbus.UInt32(2),  # mémoriser l'autorisation
        }
        saved = self._load_token()
        if saved:
            options["restore_token"] = saved
        self.portal.SelectSources(
            self.session, options, dbus_interface="org.freedesktop.portal.ScreenCast"
        )

    def _on_sources(self, code, results):
        if code != 0:
            sys.exit("Sélection de source refusée.")
        token = self._request(self._on_started)
        self.portal.Start(
            self.session,
            "",
            {"handle_token": token},
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_started(self, code, results):
        if code != 0:
            sys.exit("Partage d'écran refusé.")
        if "restore_token" in results:
            self._save_token(str(results["restore_token"]))
        streams = results["streams"]
        if not streams:
            sys.exit("Aucun flux renvoyé par le portail.")
        node_id = int(streams[0][0])
        fd = self.portal.OpenPipeWireRemote(
            self.session, {}, dbus_interface="org.freedesktop.portal.ScreenCast"
        )
        self.on_node(fd.take(), node_id)

    def _load_token(self):
        try:
            with open(TOKEN_FILE) as handle:
                return handle.read().strip()
        except OSError:
            return None

    def _save_token(self, token):
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as handle:
            handle.write(token)


class Reader:
    def __init__(self, args):
        self.args = args
        self.speaker = Speaker(args.rate, args.voice)
        self.speaker.start()
        self.last_hash = None
        self.last_seen = 0.0
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
        text = find_dialog(frame)
        if not text:
            return
        text = clean(text)
        digest = fingerprint(text)
        now = time.time()
        # Même dialogue tant qu'il reste affiché : ne pas relire en boucle.
        if digest == self.last_hash and now - self.last_seen < self.args.repeat_after:
            self.last_seen = now
            return
        self.last_hash = digest
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, default=165, help="vitesse de lecture")
    parser.add_argument("--voice", default="roa/fr", help="voix espeak-ng")
    parser.add_argument("--fps", type=int, default=2, help="images analysées par seconde")
    parser.add_argument(
        "--repeat-after",
        type=float,
        default=30.0,
        help="secondes avant de relire un dialogue identique",
    )
    parser.add_argument("--test", metavar="IMAGE", help="tester l'OCR sur une image")
    args = parser.parse_args()

    if args.test:
        frame = cv2.imread(args.test)
        if frame is None:
            sys.exit(f"Image illisible : {args.test}")
        text = find_dialog(frame)
        print(clean(text) if text else "Aucun dialogue détecté.")
        return

    Reader(args).run()


if __name__ == "__main__":
    main()
