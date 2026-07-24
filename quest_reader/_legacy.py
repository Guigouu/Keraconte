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

from quest_reader.engines import (  # noqa: E402
    VOICES,
    XTTS_NARRATION,
    XTTS_VOICE,
    PiperEngine,
    XttsEngine,
    build_engine,
    check_xtts,
)
from quest_reader.engines.xtts import voice_argument  # noqa: E402
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
from quest_reader.speaker import Speaker  # noqa: E402
from quest_reader.capture import ScreenCast  # noqa: E402
from quest_reader.reader import Reader  # noqa: E402


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
