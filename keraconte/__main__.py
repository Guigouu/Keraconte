#!/usr/bin/env python3
"""Point d'entrée : lit à voix haute les dialogues de PNJ de Dofus.

Capture l'écran en continu via le portail ScreenCast (Wayland), détecte la
bulle de dialogue, l'OCRise et la lit avec une voix française.
"""

import argparse
import os
import sys

import cv2

from keraconte.detection import find_dialog
from keraconte.engines import (
    PIPER_FEMININ,
    VOICES,
    XTTS_FEMININ,
    XTTS_NARRATION,
    XTTS_VOICE,
    check_xtts,
)
from keraconte.text import clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voice",
        default=str(VOICES / "fr_FR-tom-medium.onnx"),
        help="voix du PNJ masculin (et de l'inconnu)",
    )
    parser.add_argument(
        "--voice-feminine",
        default=str(VOICES / PIPER_FEMININ),
        help="voix du PNJ féminin (piper) ; « chemin.onnx#locuteur » pour "
        "choisir dans un modèle multi-locuteurs. Absente : repli sur --voice",
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
        help="voix du PNJ masculin : nom d'une voix du modèle, ou WAV à "
        "cloner (xtts)",
    )
    parser.add_argument(
        "--feminine-sample",
        default=XTTS_FEMININ,
        help="voix du PNJ féminin : nom ou WAV (xtts)",
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
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="lister les voix Piper installées (et leurs locuteurs) puis quitter",
    )
    parser.add_argument("--test", metavar="IMAGE", help="tester l'OCR sur une image")
    parser.add_argument(
        "--dire",
        metavar="TEXTE",
        help="synthétiser une phrase de test et quitter (smoke test TTS du "
        "bundle : exerce espeak-ng + le moteur ; un « *mot* » teste la voix "
        "narrateur en plus de la voix PNJ)",
    )
    parser.add_argument(
        "--tesseract",
        metavar="CHEMIN",
        help="chemin du binaire tesseract (sinon QR_TESSERACT, puis le PATH)",
    )
    args = parser.parse_args()

    # Override explicite du binaire OCR : posé dans l'environnement puis
    # appliqué. detection.py résout tesseract à l'import (avant ce point) ;
    # on rejoue donc la résolution pour que « --tesseract » prenne effet.
    if args.tesseract:
        os.environ["QR_TESSERACT"] = args.tesseract
        from keraconte.detection import configurer_tesseract

        configurer_tesseract()

    if args.list_voices:
        _lister_voix()
        return

    if args.test:
        frame = cv2.imread(args.test)
        if frame is None:
            sys.exit(f"Image illisible : {args.test}")
        text = find_dialog(frame)
        print(clean(text) if text else "Aucun dialogue détecté.")
        return

    if args.dire is not None:
        _smoke_tts(args)
        return

    # Avant de lancer la capture : une fois le fil parti, plus aucun
    # message d'erreur du moteur n'atteindrait l'utilisateur.
    if args.engine == "xtts":
        check_xtts(args)

    lancer_avec_overlay(args)


def _smoke_tts(args):
    """Smoke test de la synthèse dans le bundle figé : exerce espeak + le moteur.

    Le chemin « --test » n'exerce QUE l'OCR ; la synthèse peut être cassée dans
    l'exe sans que rien ne le montre (données espeak-ng absentes -> Piper
    phonémise dans le vide, muet au 1er mot). Ce mode construit le moteur réel
    et le fait synthétiser, par le MÊME chemin que la production, sur les TROIS
    canaux (ADR-0001/0002) : PNJ masculin, PNJ féminin, narration. Dans le
    bundle, la voix féminine (upmc) est embarquée : une voix manquante ou un
    locuteur introuvable se voit ici, pas chez le joueur. Hors bundle sans la
    voix téléchargée, le repli du moteur (voix masculine) laisse le smoke
    passer — c'est le comportement voulu en production aussi.

    On neutralise la seule sortie carte son (pas de PortAudio en CI) : ce qu'on
    veut prouver — espeak phonémise, le moteur génère le WAV — précède la
    lecture. Une erreur de synthèse remonte (exit != 0) ; l'absence d'audio non.
    """
    from keraconte import playback
    from keraconte.engines import build_engine
    from keraconte.genre import Canal
    from keraconte.speed import Vitesse

    playback.playback.play = lambda *a, **k: None  # sortie audio neutralisée
    moteur = build_engine(args, Vitesse(args.speed))
    generation = playback.playback.generation
    texte = args.dire or "Bonjour, *il hoche la tête*, ceci est un test."
    moteur.speak(texte, canal=Canal.PNJ_MASCULIN, generation=generation)
    # Forcer aussi les deux autres canaux, indépendamment du contenu passé.
    moteur.speak("Je suis prête.", canal=Canal.PNJ_FEMININ, generation=generation)
    moteur.speak("il acquiesce", canal=Canal.NARRATION, generation=generation)
    print("Synthèse OK (voix PNJ masculin + féminin + narrateur).", flush=True)


def _lister_voix():
    """Inventaire des voix Piper trouvées localement (« --list-voices »).

    Liste les modèles du dossier de voix avec leurs locuteurs (les modèles
    multi-locuteurs comme upmc en portent plusieurs, choisis par la syntaxe
    « chemin.onnx#locuteur »). Ne télécharge rien : dit seulement ce qui est
    là et comment s'en servir.
    """
    import json

    if not VOICES.is_dir():
        print(f"Aucun dossier de voix : {VOICES}")
        print("Installer des voix : python -m piper.download_voices fr_FR-tom-medium")
        return
    modeles = sorted(VOICES.glob("*.onnx"))
    if not modeles:
        print(f"Aucune voix .onnx dans {VOICES}")
        return
    print(f"Voix Piper dans {VOICES} :")
    for onnx in modeles:
        config = onnx.parent / (onnx.name + ".json")
        locuteurs = {}
        try:
            with open(config, encoding="utf-8") as fichier:
                locuteurs = json.load(fichier).get("speaker_id_map") or {}
        except (OSError, ValueError):
            pass  # config absente ou illisible : la voix reste listée
        if locuteurs:
            noms = ", ".join(sorted(locuteurs))
            print(f"  {onnx.name} — locuteurs : {noms} (choisir : {onnx.name}#nom)")
        else:
            print(f"  {onnx.name}")
    print(
        "Usage : --voice, --voice-feminine et --narration-voice acceptent un "
        "chemin .onnx (plus « #locuteur » pour les modèles multi-locuteurs)."
    )


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

    from keraconte.capture_factory import make_capture
    from keraconte.overlay import Overlay
    from keraconte.playback import player_state
    from keraconte.reader import Reader

    from keraconte import console

    app = QApplication(sys.argv)

    # La console est masquée dès le lancement de l'interface : l'exe est bâti
    # avec « console=True » (le smoke test de la CI lit la sortie de --test, et
    # un build fenêtré n'a pas de stdout), mais le joueur n'a rien à faire d'une
    # fenêtre noire derrière son jeu. Le bouton ▤ la rappelle au besoin. No-op
    # hors Windows, où le terminal appartient à l'utilisateur.
    console_disponible = console.masquer_au_demarrage()

    reader = Reader(args)
    # La capture est un backend séparé (Linux : portail/GStreamer ; Windows/mac
    # : mss) qui alimente « reader.handle » en images. Le Speaker est arrêté
    # dans le « finally » de la boucle du backend (on_stop), là où le pipeline
    # est aussi démonté — reader.py ne pilote plus rien de tout ça.
    capture = make_capture(reader.handle, args, on_stop=reader.speaker.stop)
    capture.demarrer_capture()

    # Nombre d'écrans, connu du backend mss seulement (pas du portail Linux, où
    # re-sélectionner garde du sens) : l'overlay s'en sert pour griser le bouton
    # source quand il n'y a qu'un écran, rien à basculer.
    nombre = getattr(capture, "nombre_ecrans", None)
    nb_ecrans = nombre() if nombre is not None else None

    # Le stop de l'overlay coupe la voix en cours ; ⧉ rouvre le sélecteur de
    # source (posté sur le thread de capture) ; ✕ quitte l'app — « app.quit »
    # déclenche « aboutToQuit » et l'arrêt propre ci-dessous.
    overlay = Overlay(
        player_state,
        couper=reader.speaker.silence,
        reselectionner=capture.demander_reselection,
        fermer=app.quit,
        vitesse=reader.vitesse,
        nb_ecrans=nb_ecrans,
        console_disponible=console_disponible,
    )
    overlay.show()

    # Retour visuel de la source : le backend émet la géométrie du moniteur
    # capturé, l'overlay dessine un cadre 2 s. On branche « flash_source.emit »
    # (un SIGNAL Qt, livraison inter-thread mise en file par PySide6) et JAMAIS
    # un appel direct au widget — fait juste AVANT que le thread de capture
    # démarre, donc lu sans course par la boucle. Seul le backend mss lit
    # « on_source » aujourd'hui ; l'assigner au backend portail Linux est inerte
    # (le flash y viendra plus tard, depuis on_node) mais sans effet de bord.
    capture.on_source = overlay.flash_source.emit

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
