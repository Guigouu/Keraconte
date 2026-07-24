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

VOICES = pathlib.Path(os.path.expanduser("~/.local/share/piper-voices"))
KOKORO_DIR = pathlib.Path(os.path.expanduser("~/.local/share/kokoro"))
KOKORO_MODEL = KOKORO_DIR / "kokoro.onnx"
KOKORO_VOICES = KOKORO_DIR / "voices.bin"

# Voix par défaut de XTTS, prises parmi celles du modèle. Cloner un
# échantillon reste possible, mais donne un rendu inférieur : les voix
# intégrées viennent d'enregistrements humains, pas d'une autre synthèse.
XTTS_VOICE = "Damien Black"
XTTS_NARRATION = "Sofia Hellen"


class Engine(abc.ABC):
    @abc.abstractmethod
    def speak(self, text, narration):
        """Synthétise et joue le texte. narration=True pour une didascalie."""


from quest_reader.engines.kokoro import KokoroEngine  # noqa: E402
from quest_reader.engines.piper import PiperEngine  # noqa: E402
from quest_reader.engines.xtts import XttsEngine  # noqa: E402


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
