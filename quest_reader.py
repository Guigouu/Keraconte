#!/usr/bin/env python3
"""Lit à voix haute les dialogues de PNJ de Dofus.

Capture l'écran en continu via le portail ScreenCast (Wayland), détecte la
bulle de dialogue, l'OCRise et la lit avec une voix française.
"""

import argparse
import hashlib
import os
import pathlib
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave

import cv2
import numpy as np
import pytesseract
from PIL import Image

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import dbus  # noqa: E402
import dbus.mainloop.glib  # noqa: E402

TOKEN_FILE = os.path.expanduser("~/.cache/quest-reader/restore-token")
VOICES = pathlib.Path(os.path.expanduser("~/.local/share/piper-voices"))
KOKORO_DIR = pathlib.Path(os.path.expanduser("~/.local/share/kokoro"))
KOKORO_MODEL = KOKORO_DIR / "kokoro.onnx"
KOKORO_VOICES = KOKORO_DIR / "voices.bin"

# Réécritures appliquées avant la synthèse seulement. Sans voyelle, les
# moteurs épellent l'onomatopée lettre à lettre.
PRONUNCIATION = [(r"\bPs+t\b", "Pssit")]

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

    # Les icônes et bordures de la bulle laissent des fragments de lettres
    # isolées, collés au début et à la fin, et instables d'une image à
    # l'autre. Une vraie phrase, elle, enchaîne au moins deux mots ; une
    # didascalie ouvre sur un astérisque.
    start = re.search(
        r"\*\s*[A-Za-zÀ-ÿ]|[A-Za-zÀ-ÿ'’-]{3,}[,;:]?\s+[A-Za-zÀ-ÿ'’-]{2,}", text
    )
    if start:
        text = text[start.start() :]

    # La fin suit un vrai mot ou ferme une didascalie ; une ponctuation
    # isolée en queue ("\\ ; .") relève encore du bruit.
    # Le français place une espace avant « ? » et « ! » : on l'accepte.
    ends = list(
        re.finditer(r"[A-Za-zÀ-ÿ0-9’'](?:\s?[.!?…]+|\s*\*)", text)
    )
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


def split_narration(text):
    """Découpe le texte en segments (est_narration, contenu).

    Les jeux notent les actions entre astérisques — « * se racle la gorge * »
    — et on les prononce avec une autre voix que la parole du PNJ.
    """
    segments = []
    for index, part in enumerate(re.split(r"\*([^*]+)\*", text)):
        part = part.strip(" *")
        if part:
            segments.append((index % 2 == 1, part))
    return segments


def pronounce(text):
    """Réécrit ce qui se prononce mal, sans toucher au texte affiché.

    Les synthétiseurs épellent les onomatopées dépourvues de voyelle :
    « Pssst » sort en « p-s-s-s-t ». Ajouter une voyelle suffit à les
    faire prononcer, en gardant la sonorité sifflante.
    """
    for pattern, replacement in PRONUNCIATION:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def split_sentences(text):
    """Découpe en phrases, ponctuation comprise."""
    parts = re.findall(r"[^.!?…]+[.!?…]*", text)
    return [part.strip() for part in parts if part.strip()]


def play_wave(path):
    subprocess.run(["paplay", path], check=False, stderr=subprocess.DEVNULL)


class PiperEngine:
    """Voix masculine, rapide, mais qui marque mal la ponctuation.

    D'où le découpage : chaque phrase est synthétisée à part, puis suivie
    d'un silence. Laisser Piper lire un paragraphe entier donne un débit
    sans respiration.
    """

    def __init__(self, voices, speed, pause):
        from piper import PiperVoice, SynthesisConfig

        self.config = SynthesisConfig(length_scale=speed)
        self.voices = {kind: PiperVoice.load(path) for kind, path in voices.items()}
        self.pause = pause

    def speak(self, text, narration):
        voice = self.voices["narration" if narration else "dialogue"]
        for sentence in split_sentences(pronounce(text)):
            with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
                with wave.open(handle.name, "wb") as output:
                    voice.synthesize_wav(sentence, output, syn_config=self.config)
                play_wave(handle.name)
            time.sleep(self.pause / 1000)


class KokoroEngine:
    """Respecte mieux la ponctuation, mais n'a qu'une voix française.

    Faute d'une seconde voix, les didascalies se distinguent par un débit
    plus lent. Le modèle tourne sur le processeur : la carte graphique est
    réservée au jeu.
    """

    VOICE = "ff_siwis"
    NARRATION_SLOWDOWN = 0.85

    def __init__(self, speed):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        self.speed = speed

    def speak(self, text, narration):
        import soundfile

        speed = 1 / self.speed
        if narration:
            speed *= self.NARRATION_SLOWDOWN
        samples, rate = self.kokoro.create(
            pronounce(text), voice=self.VOICE, lang="fr-fr", speed=speed
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            soundfile.write(handle.name, samples, rate)
            play_wave(handle.name)


class Speaker(threading.Thread):
    """Synthétise dans un thread pour ne pas bloquer la capture.

    Le moteur est construit ici, et non par l'appelant : charger un modèle
    prend du temps, et ce fil est justement celui qui peut attendre.
    """

    daemon = True

    def __init__(self, build_engine):
        super().__init__()
        self.queue = queue.Queue()
        self.build_engine = build_engine

    def run(self):
        engine = self.build_engine()
        while True:
            segments = self.queue.get()
            if segments is None:
                return
            for narration, part in segments:
                try:
                    engine.speak(part, narration)
                except Exception as error:
                    # Mieux vaut un dialogue amputé qu'une partie interrompue.
                    print(f"synthèse impossible : {error}", file=sys.stderr)

    def say(self, text):
        self.queue.put(split_narration(text))


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
        self.speaker = Speaker(lambda: build_engine(args))
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


def build_engine(args):
    if args.engine == "kokoro":
        return KokoroEngine(args.speed)
    return PiperEngine(
        {"dialogue": args.voice, "narration": args.narration_voice},
        args.speed,
        args.pause,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voice", default=str(VOICES / "fr_FR-tom-medium.onnx"), help="voix du PNJ"
    )
    parser.add_argument(
        "--narration-voice",
        default=str(VOICES / "fr_FR-siwis-medium.onnx"),
        help="voix des actions entre astérisques",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.05,
        help="durée de la parole : au-dessus de 1, plus lent",
    )
    parser.add_argument(
        "--engine",
        choices=("piper", "kokoro"),
        default="piper",
        help="moteur de synthèse",
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=320,
        help="silence entre deux phrases, en millisecondes (piper)",
    )
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
