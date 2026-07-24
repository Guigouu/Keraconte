"""Tests des moteurs de synthèse (quest_reader.engines)."""

import pathlib
import sys
import types
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.engines import build_engine, check_xtts  # noqa: E402
from quest_reader.engines.piper import PiperEngine  # noqa: E402
from quest_reader.engines.xtts import XttsEngine, voice_argument  # noqa: E402
from tests.helpers import faux_xtts  # noqa: E402


def test_speed_accelere_les_deux_moteurs():
    """« --speed » est un débit : au-dessus de 1, la parole va plus vite.

    Piper raisonne à l'inverse, en durée. Sans cette inversion, un même
    chiffre accélérait un moteur et ralentissait l'autre.
    """
    rendus = {}

    class FauxPiper:
        @staticmethod
        def load(path):
            return None

    def faux_config(length_scale):
        rendus["length_scale"] = length_scale
        return None

    faux_module = types.ModuleType("piper")
    faux_module.PiperVoice = FauxPiper
    faux_module.SynthesisConfig = faux_config
    with mock.patch.dict(sys.modules, {"piper": faux_module}):
        PiperEngine({"dialogue": "x", "narration": "y"}, 1.25, 0)

    # Un débit de 1.25 doit raccourcir la durée, non l'allonger.
    assert rendus["length_scale"] == pytest.approx(0.8)


def test_xtts_pose_la_rustine_isin_mps_friendly():
    """Sans elle, « from TTS.api import TTS » lève sur transformers 5.x.

    Coqui importe « isin_mps_friendly », retiré en 5.x. XTTS ne s'en sert
    pas, mais le module fautif est chargé au passage. Les arguments sont
    passés par mot-clé : la signature compte.
    """
    modules, pu = faux_xtts({})
    with mock.patch.dict(sys.modules, modules):
        XttsEngine({"dialogue": "a.wav", "narration": "b.wav"}, 1.0)
        assert hasattr(pu, "isin_mps_friendly")
        elements, test_elements = pu.isin_mps_friendly(
            elements="e", test_elements="t"
        )
    assert (elements, test_elements) == ("e", "t")


def test_xtts_decoupe_par_phrases_et_choisit_la_voix():
    """Le bloc entier d'un coup donnerait le délai reproché à Kokoro.

    Chaque phrase part séparément, et les didascalies prennent le second
    échantillon : XTTS clone deux voix, là où Kokoro n'en a qu'une.
    """
    rendus = {}
    modules, _ = faux_xtts(rendus)
    with mock.patch.dict(sys.modules, modules):
        moteur = XttsEngine(
            {"dialogue": "pnj.wav", "narration": "didascalie.wav"}, 1.15
        )
        moteur.speak("Bienvenue ! Approche-toi.", narration=False)
        moteur.speak("se racle la gorge", narration=True)

    appels = rendus["appels"]
    assert [appel["text"] for appel in appels] == [
        "Bienvenue !",
        "Approche-toi.",
        "se racle la gorge",
    ]
    assert [appel["speaker"] for appel in appels] == [
        "pnj.wav",
        "pnj.wav",
        "didascalie.wav",
    ]
    assert {appel["language"] for appel in appels} == {"fr"}
    # « --speed » est un débit et XTTS aussi : aucune inversion, contrairement
    # à Piper qui raisonne en durée.
    assert {appel["speed"] for appel in appels} == {1.15}


def test_xtts_ne_synthetise_pas_un_segment_vide():
    """Le découpage isole parfois une ponctuation seule (« Ah… ! »).

    Sans phonème à concaténer, les moteurs lèvent au lieu de se taire — bug
    déjà rencontré sur Kokoro.
    """
    rendus = {}
    modules, _ = faux_xtts(rendus)
    with mock.patch.dict(sys.modules, modules):
        moteur = XttsEngine({"dialogue": "a", "narration": "b"}, 1.0)
        moteur.speak("...", narration=False)

    assert rendus.get("appels", []) == []


def args_xtts(**extra):
    defauts = {"voice_sample": "Damien Black", "narration_sample": "Sofia Hellen"}
    return types.SimpleNamespace(**{**defauts, **extra})


def test_xtts_accepte_une_voix_du_modele():
    """Les voix intégrées se désignent par leur nom, pas par un fichier.

    Cloner un échantillon reste possible, mais donne un rendu inférieur
    quand la référence est elle-même synthétique.
    """
    check_xtts(
        args_xtts(voice_sample="Damien Black", narration_sample="Sofia Hellen")
    )
    assert voice_argument("Damien Black") == {"speaker": "Damien Black"}


def test_xtts_signale_un_wav_introuvable(tmp_path):
    """Un chemin en .wav qui n'existe pas est une faute de frappe."""
    with pytest.raises(SystemExit) as sortie:
        check_xtts(
            args_xtts(
                voice_sample=str(tmp_path / "absent.wav"),
                narration_sample="Sofia Hellen",
            )
        )
    assert "introuvable" in str(sortie.value)


def test_xtts_clone_un_wav_existant(tmp_path):
    """Un fichier réel doit passer par le clonage, pas par le nom."""
    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    assert voice_argument(str(echantillon)) == {"speaker_wav": str(echantillon)}


def test_xtts_refuse_un_echantillon_introuvable(tmp_path):
    """Un chemin fourni mais absent doit se dire, pas se découvrir 83 s plus
    tard au chargement du modèle."""
    present = tmp_path / "voix.wav"
    present.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(present), narration_sample=str(tmp_path / "absent.wav")
    )
    with pytest.raises(SystemExit) as sortie:
        check_xtts(args)
    assert "introuvable" in str(sortie.value)


def test_xtts_sans_cuda_explique_et_s_arrete(tmp_path):
    """Sur processeur le ratio serait dix fois pire : injouable."""
    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(echantillon), narration_sample=str(echantillon)
    )
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    with mock.patch.dict(sys.modules, {"torch": torch}):
        with pytest.raises(SystemExit) as sortie:
            check_xtts(args)
    assert "CUDA" in str(sortie.value)


def test_build_engine_route_vers_xtts():
    """Le contrôle vit dans « main », pas dans le moteur : « sys.exit »
    depuis le fil « Speaker » est avalé en silence par threading."""
    rendus = {}
    modules, _ = faux_xtts(rendus)
    args = types.SimpleNamespace(
        engine="xtts", speed=1.15, voice_sample="pnj.wav", narration_sample="dida.wav"
    )
    with mock.patch.dict(sys.modules, modules):
        moteur = build_engine(args)

    assert isinstance(moteur, XttsEngine)
    assert rendus["device"] == "cuda"
    assert rendus["model"] == "tts_models/multilingual/multi-dataset/xtts_v2"


def test_xtts_absent_du_venv_dit_comment_l_installer(tmp_path):
    """Cas courant, pas accidentel : XTTS pèse ~3 Go et vit hors du venv du
    projet. Sans ce garde-fou, l'utilisateur reçoit un ModuleNotFoundError nu.
    """
    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(echantillon), narration_sample=str(echantillon)
    )
    # Simule un venv sans torch, quel que soit celui qui exécute les tests.
    with mock.patch.dict(sys.modules, {"torch": None}):
        with pytest.raises(SystemExit) as sortie:
            check_xtts(args)
    assert "pip install" in str(sortie.value)
