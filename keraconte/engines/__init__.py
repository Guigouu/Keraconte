"""Moteurs de synthèse vocale : contrat commun et sélection.

« Engine » fixe le contrat « speak(text, narration) » que chaque moteur
concret implémente. « build_engine » choisit le moteur selon les arguments,
« check_xtts » vérifie en amont ce que XTTS exige (dans le fil principal, où
« sys.exit » se voit).
"""

import abc
import os
import pathlib
import sys

import platformdirs


def _racine_donnees():
    """Racine où trouver les modèles de voix, bundle figé d'abord.

    Dans l'exécutable « fat » (PyInstaller), les voix .onnx sont embarquées
    sous « sys._MEIPASS » : on les cherche là EN PRIORITÉ, sinon la voix par
    défaut se résoudrait vers un %LOCALAPPDATA%\\piper-voices inexistant et
    « PiperVoice.load » échouerait à la première réplique (même piège que le
    binaire tesseract). Hors bundle, on retombe sur la racine utilisateur
    native via platformdirs SANS nom d'appli : sous Linux elle vaut
    ~/.local/share (donc piper-voices/ et kokoro/ restent EXACTEMENT là où
    l'ancien chemin en dur les plaçait — aucune rupture) ; sous Windows
    %LOCALAPPDATA%, sous macOS ~/Library/Application Support.
    """
    racine_figee = getattr(sys, "_MEIPASS", None)
    if racine_figee and os.path.isdir(os.path.join(racine_figee, "piper-voices")):
        return pathlib.Path(racine_figee)
    return pathlib.Path(platformdirs.user_data_dir(appname=False))


_DATA = _racine_donnees()
VOICES = _DATA / "piper-voices"
KOKORO_DIR = _DATA / "kokoro"
KOKORO_MODEL = KOKORO_DIR / "kokoro.onnx"
KOKORO_VOICES = KOKORO_DIR / "voices.bin"

# Voix par défaut de XTTS, prises parmi celles du modèle. Cloner un
# échantillon reste possible, mais donne un rendu inférieur : les voix
# intégrées viennent d'enregistrements humains, pas d'une autre synthèse.
XTTS_VOICE = "Damien Black"
XTTS_NARRATION = "Sofia Hellen"


class Engine(abc.ABC):
    @abc.abstractmethod
    def speak(self, text, narration, generation):
        """Synthétise et joue le texte. narration=True pour une didascalie.

        « generation » identifie le dialogue courant : le moteur s'interrompt
        si une nouvelle génération survient (un autre dialogue a pris le
        dessus), pour ne pas finir de dire une réplique périmée.
        """


from keraconte.engines.kokoro import KokoroEngine  # noqa: E402
from keraconte.engines.piper import PiperEngine  # noqa: E402
from keraconte.engines.xtts import XttsEngine  # noqa: E402


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


def build_engine(args, vitesse):
    """Construit le moteur choisi, alimenté par la vitesse partagée.

    « vitesse » (objet « Vitesse ») remplace « args.speed » figé : le débit
    devient mutable à chaud, relu à chaque réplique par le moteur.
    """
    if args.engine == "xtts":
        return XttsEngine(
            {"dialogue": args.voice_sample, "narration": args.narration_sample},
            vitesse,
        )
    if args.engine == "kokoro":
        return KokoroEngine(vitesse)
    return PiperEngine(
        {"dialogue": args.voice, "narration": args.narration_voice},
        vitesse,
        args.pause,
    )
