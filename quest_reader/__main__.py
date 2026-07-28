#!/usr/bin/env python3
"""Point d'entrée : lit à voix haute les dialogues de PNJ de Dofus.

Capture l'écran en continu via le portail ScreenCast (Wayland), détecte la
bulle de dialogue, l'OCRise et la lit avec une voix française.
"""

import argparse
import sys

import cv2

from quest_reader.detection import find_dialog
from quest_reader.engines import (
    VOICES,
    XTTS_NARRATION,
    XTTS_VOICE,
    check_xtts,
)
from quest_reader.reader import Reader
from quest_reader.text import clean


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
    parser.add_argument("--fps", type=int, default=4, help="images analysées par seconde")
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

    lancer_avec_overlay(args)


def lancer_avec_overlay(args):
    """Qt sur le thread principal, la capture dans un thread dédié.

    On n'unifie pas les boucles d'événements : on les isole. Qt tient le
    thread principal (l'overlay), et la boucle GLib de capture descend dans un
    thread. Ils ne communiquent qu'à travers PlayerState et le Speaker.
    """
    import signal
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from quest_reader.capture_factory import make_capture
    from quest_reader.overlay import Overlay
    from quest_reader.playback import player_state
    from quest_reader.reader import Reader

    app = QApplication(sys.argv)

    reader = Reader(args)
    # La capture est un backend séparé (Linux : portail/GStreamer ; Windows/mac
    # : mss) qui alimente « reader.handle » en images. Le Speaker est arrêté
    # dans le « finally » de la boucle du backend (on_stop), là où le pipeline
    # est aussi démonté — reader.py ne pilote plus rien de tout ça.
    capture = make_capture(reader.handle, args, on_stop=reader.speaker.stop)
    capture.demarrer_capture()

    # Le stop de l'overlay coupe la voix en cours ; ⧉ rouvre le sélecteur de
    # source (posté sur le thread de capture) ; ✕ quitte l'app — « app.quit »
    # déclenche « aboutToQuit » et l'arrêt propre ci-dessous.
    overlay = Overlay(
        player_state,
        couper=reader.speaker.silence,
        reselectionner=capture.demander_reselection,
        fermer=app.quit,
        vitesse=reader.vitesse,
    )
    overlay.show()

    fil_capture = threading.Thread(target=capture.boucler, daemon=True)
    fil_capture.start()

    # Ctrl+C : Qt ne rend pas la main aux handlers Python sans un réveil
    # périodique de l'interpréteur.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    reveil = QTimer()
    reveil.timeout.connect(lambda: None)
    reveil.start(200)

    # Arrêt propre : à la fermeture de Qt, on arrête la boucle GLib et on
    # attend la fin du thread de capture (qui met le pipeline à NULL et stoppe
    # le Speaker dans son finally).
    def au_depart():
        capture.arreter()
        fil_capture.join(timeout=5)

    app.aboutToQuit.connect(au_depart)

    app.exec()


if __name__ == "__main__":
    main()
