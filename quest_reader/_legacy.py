#!/usr/bin/env python3
"""Lit à voix haute les dialogues de PNJ de Dofus.

Capture l'écran en continu via le portail ScreenCast (Wayland), détecte la
bulle de dialogue, l'OCRise et la lit avec une voix française.
"""

import argparse
import concurrent.futures
import contextlib
import difflib
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

# Voix par défaut de XTTS, prises parmi celles du modèle. Cloner un
# échantillon reste possible, mais donne un rendu inférieur : les voix
# intégrées viennent d'enregistrements humains, pas d'une autre synthèse.
XTTS_VOICE = "Damien Black"
XTTS_NARRATION = "Sofia Hellen"

from quest_reader.text import (  # noqa: E402
    clean,
    clearest,
    fingerprint,
    pronounce,
    same_dialog,
    speakable,
    split_narration,
    split_sentences,
    strip_choices,
    word_gap,
)

from quest_reader.detection import (  # noqa: E402
    drop_replies,
    find_bubbles,
    find_dialog,
    is_reply_block,
    keep_word,
    read_words,
    reads_like_dialogue,
)
from quest_reader.playback import Playback, play_wave, playback  # noqa: E402


class PiperEngine:
    """Voix masculine, rapide, mais qui marque mal la ponctuation.

    D'où le découpage : chaque phrase est synthétisée à part, puis suivie
    d'un silence. Laisser Piper lire un paragraphe entier donne un débit
    sans respiration.
    """

    def __init__(self, voices, speed, pause):
        from piper import PiperVoice, SynthesisConfig

        # Piper raisonne en durée : au-dessus de 1, il ralentit. On expose
        # un débit, donc on inverse.
        self.config = SynthesisConfig(length_scale=1 / speed)
        self.voices = {kind: PiperVoice.load(path) for kind, path in voices.items()}
        self.pause = pause

    def speak(self, text, narration):
        voice = self.voices["narration" if narration else "dialogue"]
        for sentence in split_sentences(pronounce(text)):
            # Le découpage isole parfois une ponctuation seule (« Ah… ! »).
            if not speakable(sentence):
                continue
            if playback.stopped:  # dialogue fermé en cours de réplique
                return
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
    # Seul signe distinctif des didascalies faute d'une seconde voix : il
    # faut donc que l'écart de débit s'entende nettement.
    NARRATION_SLOWDOWN = 0.75

    def __init__(self, speed):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        self.speed = speed

    def speak(self, text, narration):
        import soundfile

        spoken = pronounce(text)
        # Sans phonème à concaténer, « create » lève au lieu de se taire.
        if not speakable(spoken):
            return
        speed = self.speed
        if narration:
            speed *= self.NARRATION_SLOWDOWN
        samples, rate = self.kokoro.create(
            spoken, voice=self.VOICE, lang="fr-fr", speed=speed
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            soundfile.write(handle.name, samples, rate)
            play_wave(handle.name)


def voice_argument(voice):
    """Traduit une voix en argument pour XTTS.

    Le modèle embarque cinquante-huit voix humaines : les nommer donne un
    bien meilleur rendu que cloner un échantillon, surtout si celui-ci
    provient déjà d'une synthèse — les défauts s'y accumulent.
    """
    if os.path.isfile(voice):
        return {"speaker_wav": voice}
    return {"speaker": voice}


class XttsEngine:
    """Clone deux voix à partir d'échantillons WAV, sur la carte graphique.

    Mesuré sur RTX 3070 Ti : ratio 0,24× — la synthèse va quatre fois plus
    vite que la parole — pour 1,96 Go de VRAM. Le découpage par phrases,
    comme chez Piper, rend l'attente imperceptible malgré les 83 s de
    chargement initial, payées une seule fois dans le fil « Speaker ».
    """

    MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

    def __init__(self, samples, speed):
        # Import tardif, comme les autres moteurs : le venv du projet n'a
        # pas torch, et l'importer au niveau module casserait tout le reste.
        import torch
        import transformers.pytorch_utils as pu

        # Rustine obligatoire. Coqui importe « isin_mps_friendly » depuis
        # transformers, qui l'a retiré en 5.x : sans elle, « from TTS.api
        # import TTS » lève ImportError. XTTS ne s'en sert pas, mais le
        # module fautif (tortoise) est chargé au passage. Les arguments
        # sont passés par mot-clé, d'où cette signature exacte.
        if not hasattr(pu, "isin_mps_friendly"):
            pu.isin_mps_friendly = lambda elements, test_elements: torch.isin(
                elements, test_elements
            )

        from TTS.api import TTS

        self.tts = TTS(self.MODEL).to("cuda")
        self.samples = samples
        self.speed = speed
        # Un seul fil : deux synthèses simultanées se disputeraient la carte
        # sans rien gagner. Il ne sert qu'à prendre une phrase d'avance.
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def render(self, sentence, sample, path):
        # Pas de « no_grad » ici : Coqui l'applique déjà en interne. Mesuré —
        # douze répliques d'affilée, avec et sans, la mémoire reste plate à
        # 4,7 Go dans les deux cas.
        #
        # « speed » va déjà dans le sens du débit chez XTTS : au-dessus de 1,
        # plus rapide. Pas d'inversion, contrairement à Piper qui raisonne
        # en durée.
        self.tts.tts_to_file(
            text=sentence,
            language="fr",
            speed=self.speed,
            file_path=path,
            **voice_argument(sample),
        )

    def speak(self, text, narration):
        """Synthétise la phrase suivante pendant que la précédente se joue.

        « play_wave » bloque, et XTTS met environ une seconde et demie par
        phrase : les enchaîner bout à bout laissait un silence entre chacune,
        soit cinq trous dans une réplique un peu longue. Piper synthétise
        trop vite pour que cela s'entende, d'où le découpage naïf d'origine.
        """
        sample = self.samples["narration" if narration else "dialogue"]
        # Sans phonème, le moteur concatène une liste vide et lève.
        sentences = [
            sentence
            for sentence in split_sentences(pronounce(text))
            if speakable(sentence)
        ]
        with contextlib.ExitStack() as stack:
            files = [
                stack.enter_context(tempfile.NamedTemporaryFile(suffix=".wav"))
                for _ in sentences
            ]
            avance = None
            for position, sentence in enumerate(sentences):
                # Inutile d'occuper la carte pour un dialogue déjà fermé :
                # « Playback » refuserait de jouer le résultat.
                if playback.stopped:
                    break
                if avance is None:
                    self.render(sentence, sample, files[position].name)
                else:
                    avance.result()
                suivante = position + 1
                avance = (
                    self.pool.submit(
                        self.render, sentences[suivante], sample, files[suivante].name
                    )
                    if suivante < len(sentences)
                    else None
                )
                play_wave(files[position].name)


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
    # Images consécutives sans bulle avant de tenir le dialogue pour fermé.
    # À --fps 2, cela laisse une seconde et demie : assez pour absorber une
    # disparition passagère, assez court pour que la coupure suive le geste.
    CLOSED_AFTER = 3

    def __init__(self, args):
        self.args = args
        self.speaker = Speaker(lambda: build_engine(args))
        self.speaker.start()
        self.last_text = None
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
        text = find_dialog(frame)
        if not text:
            # Ne couper que si la bulle a vraiment quitté l'écran. L'OCR
            # échoue régulièrement sur une bulle bien présente — texte en
            # cours d'affichage, rafraîchissement — et couper là-dessus
            # arrêtait la voix au milieu d'une réplique qui n'avait pas
            # changé, sans jamais reprendre puisque le texte au retour est
            # reconnu comme déjà lu.
            boxes, _ = find_bubbles(frame)
            if boxes:
                return
            # La bulle disparaît parfois une image sans que le joueur ait
            # rien fermé — fondu, fenêtre qui passe devant. Couper au premier
            # trou hacherait la lecture, d'où le comptage.
            self.missing += 1
            if self.missing == self.CLOSED_AFTER:
                self.speaker.silence()
                # « last_text » survit exprès. Trois images sans bulle ne
                # prouvent pas que le joueur a fermé quoi que ce soit, et
                # effacer la mémoire faisait relire le dialogue en entier au
                # retour — quatre fois pour une réplique un peu longue. C'est
                # « repeat_after » qui autorise une relecture, pas l'oubli.
                self.pending = []
            return
        self.missing = 0
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


def check_xtts(args):
    """Vérifie de quoi XTTS a besoin, dans le fil principal.

    Ces contrôles ne peuvent pas vivre dans le moteur : celui-ci est
    construit par le fil « Speaker », où « sys.exit » ne fait que lever un
    SystemExit avalé en silence par threading — le message n'apparaîtrait
    jamais et le programme continuerait sans voix. Vérifié.
    """
    # Une voix est soit le nom d'une des voix du modèle, soit le chemin d'un
    # WAV à cloner. Un chemin qui ressemble à un fichier mais n'existe pas
    # est une faute de frappe, pas un nom de voix : le dire tout de suite.
    for option, voice in (
        ("--voice-sample", args.voice_sample),
        ("--narration-sample", args.narration_sample),
    ):
        if voice.endswith(".wav") and not os.path.isfile(voice):
            sys.exit(f"Échantillon introuvable pour {option} : {voice}")

    # XTTS pèse environ 3 Go : il est tenu hors du venv du projet, donc
    # l'absence de torch est le cas courant, pas l'accident. Le dire ici
    # plutôt que de laisser remonter un ModuleNotFoundError nu.
    try:
        import torch
    except ModuleNotFoundError:
        sys.exit(
            "XTTS n'est pas installé dans cet environnement : "
            "« pip install torch torchaudio 'coqui-tts[codec]' » "
            "(voir le README, section XTTS-v2)."
        )

    # En processeur, le ratio serait environ dix fois pire : la synthèse
    # prendrait plus longtemps que la réplique à dire, donc injouable.
    if not torch.cuda.is_available():
        sys.exit(
            "XTTS demande CUDA : sur processeur la synthèse serait plus lente "
            "que la parole. Essayez « --engine piper »."
        )


def build_engine(args):
    if args.engine == "xtts":
        return XttsEngine(
            {"dialogue": args.voice_sample, "narration": args.narration_sample},
            args.speed,
        )
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
        default=1.22,
        help="débit de la parole : au-dessus de 1, plus rapide",
    )
    parser.add_argument(
        "--engine",
        choices=("piper", "kokoro", "xtts"),
        default="piper",
        help="moteur de synthèse",
    )
    parser.add_argument(
        "--voice-sample",
        default=XTTS_VOICE,
        help="voix du PNJ : nom d'une voix du modèle, ou WAV à cloner (xtts)",
    )
    parser.add_argument(
        "--narration-sample",
        default=XTTS_NARRATION,
        help="voix des didascalies : nom ou WAV (xtts)",
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

    # Avant de lancer la capture : une fois le fil parti, plus aucun
    # message d'erreur du moteur n'atteindrait l'utilisateur.
    if args.engine == "xtts":
        check_xtts(args)

    Reader(args).run()


if __name__ == "__main__":
    main()
