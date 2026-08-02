"""Tests des moteurs de synthèse (keraconte.engines)."""

import pathlib
import sys
import types
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte.engines import build_engine, check_xtts  # noqa: E402
from keraconte.engines.piper import PiperEngine  # noqa: E402
from keraconte.engines.xtts import XttsEngine, voice_argument  # noqa: E402
from keraconte.playback import playback  # noqa: E402
from keraconte.speed import Vitesse  # noqa: E402
from tests.helpers import faux_xtts  # noqa: E402


def faux_piper(rendus):
    """Double la bibliothèque « piper » et capture le « length_scale ».

    « SynthesisConfig » n'enregistre que le dernier « length_scale » reçu, et
    la voix ne synthétise rien de réel — on vérifie le câblage du débit, pas
    la synthèse. On patche aussi « play_wave » pour ne rien jouer.
    """

    class FausseVoix:
        @staticmethod
        def load(path):
            return FausseVoix()

        def synthesize_wav(self, texte, sortie, syn_config):
            # Le vrai Piper remplit l'objet « wave » ; on écrit un cadre
            # minimal pour que « wave.open » se ferme sans « # channels
            # not specified ». On ne joue rien (« play_wave » est patché).
            sortie.setnchannels(1)
            sortie.setsampwidth(2)
            sortie.setframerate(22050)
            sortie.writeframes(b"\x00\x00")

    def faux_config(length_scale):
        rendus["length_scale"] = length_scale
        return None

    faux_module = types.ModuleType("piper")
    faux_module.PiperVoice = FausseVoix
    faux_module.SynthesisConfig = faux_config
    return faux_module


def faux_piper_suite(rendus, apres_phrase=None):
    """Double « piper » et capture le « length_scale » de CHAQUE phrase.

    À la différence de « faux_piper » (qui n'écrase qu'un seul scale), on
    empile la suite complète dans « rendus["scales"] ». « apres_phrase » est
    un crochet appelé après la synthèse de chaque phrase (numéro depuis 1) :
    il sert à muter la Vitesse entre deux phrases pour éprouver le débit à
    chaud AU SEIN d'une même réplique.
    """

    class FausseVoix:
        def __init__(self):
            self._rang = 0

        @staticmethod
        def load(path):
            return FausseVoix()

        def synthesize_wav(self, texte, sortie, syn_config):
            sortie.setnchannels(1)
            sortie.setsampwidth(2)
            sortie.setframerate(22050)
            sortie.writeframes(b"\x00\x00")
            self._rang += 1
            if apres_phrase is not None:
                apres_phrase(self._rang)

    def faux_config(length_scale):
        rendus.setdefault("scales", []).append(length_scale)
        return None

    faux_module = types.ModuleType("piper")
    faux_module.PiperVoice = FausseVoix
    faux_module.SynthesisConfig = faux_config
    return faux_module


def test_piper_relit_la_vitesse_entre_deux_phrases():
    """La vitesse change DÈS la phrase suivante de la réplique EN COURS.

    Piper calculait « SynthesisConfig(length_scale) » UNE fois avant la boucle
    « for sentence » : le débit était figé pour toute la réplique. On le
    reconstruit désormais à chaque phrase. Ce test mute la Vitesse après la
    1ʳᵉ phrase et attend un « length_scale » différent sur la 2ᵉ. ROUGE tant
    que la config est calculée hors de la boucle.
    """
    rendus = {}
    vitesse = Vitesse(1.0)

    def muter(rang):
        if rang == 1:
            vitesse.augmenter()  # 1.0 → 1.1, au milieu de la réplique

    faux_module = faux_piper_suite(rendus, apres_phrase=muter)
    with mock.patch.dict(sys.modules, {"piper": faux_module}), mock.patch(
        "keraconte.engines.piper.play_wave"
    ):
        moteur = PiperEngine({"dialogue": "x", "narration": "y"}, vitesse, 0)
        moteur.speak(
            "Bonjour. Rebonjour.", narration=False, generation=playback.generation
        )

    scales = rendus["scales"]
    assert len(scales) == 2  # deux phrases synthétisées
    assert scales[0] == pytest.approx(1 / 1.0)
    assert scales[1] == pytest.approx(1 / 1.1)


@pytest.mark.parametrize(
    "texte, pauses_attendues",
    [
        ("Bonjour. Rebonjour.", 1),  # deux phrases : UNE pause entre elles
        ("Bonjour seul.", 0),  # une seule phrase : aucune pause
    ],
)
def test_piper_pause_entre_phrases_pas_apres_la_derniere(texte, pauses_attendues):
    """La pause sépare deux phrases ; elle ne suit jamais la dernière.

    Le « sleep(pause) » était placé en fin de boucle, donc s'exécutait aussi
    après la dernière phrase : un silence mort avant que la voix se rende. On
    l'a déplacé en tête, sauf avant la 1ʳᵉ phrase. N phrases → N−1 pauses.
    """
    rendus = {}
    faux_module = faux_piper_suite(rendus)
    with mock.patch.dict(sys.modules, {"piper": faux_module}), mock.patch(
        "keraconte.engines.piper.play_wave"
    ), mock.patch("keraconte.engines.piper.time.sleep") as dors:
        moteur = PiperEngine({"dialogue": "x", "narration": "y"}, vitesse=Vitesse(1.0), pause=320)
        moteur.speak(texte, narration=False, generation=playback.generation)

    assert dors.call_count == pauses_attendues


def test_speed_accelere_les_deux_moteurs():
    """« --speed » est un débit : au-dessus de 1, la parole va plus vite.

    Piper raisonne à l'inverse, en durée. Sans cette inversion, un même
    chiffre accélérait un moteur et ralentissait l'autre.
    """
    rendus = {}
    faux_module = faux_piper(rendus)
    with mock.patch.dict(sys.modules, {"piper": faux_module}), mock.patch(
        "keraconte.engines.piper.play_wave"
    ):
        moteur = PiperEngine({"dialogue": "x", "narration": "y"}, Vitesse(1.25), 0)
        moteur.speak("Bonjour.", narration=False, generation=playback.generation)

    # Un débit de 1.25 doit raccourcir la durée, non l'allonger.
    assert rendus["length_scale"] == pytest.approx(0.8)


def test_piper_relit_la_vitesse_a_chaud():
    """Muter la Vitesse change le débit à la réplique SUIVANTE.

    Piper pré-calculait « SynthesisConfig(length_scale) » à la construction :
    le débit était figé pour la vie du moteur. On le reconstruit désormais à
    chaque « speak », depuis la vitesse partagée. Ce test est ROUGE tant que
    la config reste figée dans « __init__ ».
    """
    rendus = {}
    faux_module = faux_piper(rendus)
    vitesse = Vitesse(1.0)
    with mock.patch.dict(sys.modules, {"piper": faux_module}), mock.patch(
        "keraconte.engines.piper.play_wave"
    ):
        moteur = PiperEngine({"dialogue": "x", "narration": "y"}, vitesse, 0)
        moteur.speak("Bonjour.", narration=False, generation=playback.generation)
        assert rendus["length_scale"] == pytest.approx(1.0)  # 1/1.0
        vitesse.augmenter()  # 1.0 → 1.1
        moteur.speak("Rebonjour.", narration=False, generation=playback.generation)

    assert rendus["length_scale"] == pytest.approx(1 / 1.1)


def test_xtts_pose_la_rustine_isin_mps_friendly():
    """Sans elle, « from TTS.api import TTS » lève sur transformers 5.x.

    Coqui importe « isin_mps_friendly », retiré en 5.x. XTTS ne s'en sert
    pas, mais le module fautif est chargé au passage. Les arguments sont
    passés par mot-clé : la signature compte.
    """
    modules, pu = faux_xtts({})
    with mock.patch.dict(sys.modules, modules):
        XttsEngine({"dialogue": "a.wav", "narration": "b.wav"}, Vitesse(1.0))
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
            {"dialogue": "pnj.wav", "narration": "didascalie.wav"}, Vitesse(1.15)
        )
        moteur.speak(
            "Bienvenue ! Approche-toi.", narration=False, generation=playback.generation
        )
        moteur.speak(
            "se racle la gorge", narration=True, generation=playback.generation
        )

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
        moteur = XttsEngine({"dialogue": "a", "narration": "b"}, Vitesse(1.0))
        moteur.speak("...", narration=False, generation=playback.generation)

    assert rendus.get("appels", []) == []


def test_xtts_relit_la_vitesse_a_chaud():
    """Muter la Vitesse change le débit passé à « tts_to_file » à la suivante.

    XTTS lisait « self.speed » figé ; il lit désormais la vitesse partagée à
    chaque rendu. Le double « faux_xtts » capture le « speed » de chaque appel.
    """
    rendus = {}
    modules, _ = faux_xtts(rendus)
    vitesse = Vitesse(1.0)
    with mock.patch.dict(sys.modules, modules):
        moteur = XttsEngine({"dialogue": "a", "narration": "b"}, vitesse)
        moteur.speak("Bonjour.", narration=False, generation=playback.generation)
        vitesse.augmenter()  # 1.0 → 1.1
        moteur.speak("Rebonjour.", narration=False, generation=playback.generation)

    vitesses = [appel["speed"] for appel in rendus["appels"]]
    assert vitesses == [pytest.approx(1.0), pytest.approx(1.1)]


def faux_kokoro(rendus):
    """Double la bibliothèque « kokoro_onnx » et capture le « speed » de create."""
    import numpy

    class FauxKokoro:
        def __init__(self, modele, voix):
            pass

        def create(self, texte, voice, lang, speed):
            rendus.setdefault("speeds", []).append(speed)
            return numpy.zeros(1, dtype="float32"), 24000

    faux_module = types.ModuleType("kokoro_onnx")
    faux_module.Kokoro = FauxKokoro
    return faux_module


def test_kokoro_relit_la_vitesse_a_chaud():
    """Muter la Vitesse change le débit passé à « create » à la suivante.

    Kokoro lisait « self.speed » à chaque « speak » ; il lit désormais la
    vitesse partagée. On double « kokoro_onnx.Kokoro » et « play_wave ».
    """
    # KokoroEngine.speak importe soundfile pour écrire le WAV ; c'est un extra
    # optionnel ([kokoro]), absent du cœur installé en CI. On saute sans lui.
    pytest.importorskip("soundfile")
    from keraconte.engines.kokoro import KokoroEngine

    rendus = {}
    faux_module = faux_kokoro(rendus)
    vitesse = Vitesse(1.0)
    with mock.patch.dict(sys.modules, {"kokoro_onnx": faux_module}), mock.patch(
        "keraconte.engines.kokoro.play_wave"
    ):
        moteur = KokoroEngine(vitesse)
        moteur.speak("Bonjour.", narration=False, generation=playback.generation)
        vitesse.augmenter()  # 1.0 → 1.1
        moteur.speak("Rebonjour.", narration=False, generation=playback.generation)

    assert rendus["speeds"] == [pytest.approx(1.0), pytest.approx(1.1)]


def args_xtts(**extra):
    defauts = {"voice_sample": "Damien Black", "narration_sample": "Sofia Hellen"}
    return types.SimpleNamespace(**{**defauts, **extra})


def test_xtts_accepte_une_voix_du_modele():
    """Les voix intégrées se désignent par leur nom, pas par un fichier.

    Cloner un échantillon reste possible, mais donne un rendu inférieur
    quand la référence est elle-même synthétique.
    """
    # check_xtts exige torch (+ CUDA) : c'est l'extra [nvidia], hors du cœur
    # installé en CI. Sans torch, on saute — ce chemin ne concerne que XTTS.
    pytest.importorskip("torch")
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
        moteur = build_engine(args, Vitesse(args.speed))

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


def test_piper_ecrit_puis_rejoue_par_nom_un_fichier_existant():
    """Le WAV synthétisé existe et est plein quand « play_wave » le reçoit.

    Prouve que Piper route par « wav_temporaire » et que le cycle
    écrire-puis-rejouer-par-nom tient. Ne prouve PAS la sécurité Windows
    (réouverture par nom sans handle) : cela ne se vérifie qu'en CI Windows.
    """
    import os

    vus = []
    rendus = {}
    faux_module = faux_piper(rendus)
    with mock.patch.dict(sys.modules, {"piper": faux_module}), mock.patch(
        "keraconte.engines.piper.play_wave",
        side_effect=lambda path, gen: vus.append((path, os.path.getsize(path))),
    ):
        moteur = PiperEngine({"dialogue": "x", "narration": "y"}, Vitesse(1.0), 0)
        moteur.speak("Bonjour.", narration=False, generation=playback.generation)

    assert len(vus) == 1
    path, taille = vus[0]
    assert path.endswith(".wav")
    assert taille > 0  # le WAV a bien été écrit avant d'être joué


def test_xtts_prefetch_utilise_des_fichiers_distincts():
    """Deux phrases → deux chemins distincts, tous deux vivants en même temps.

    XTTS synthétise la phrase N+1 pendant que N se joue (pool d'un fil) : les
    fichiers doivent coexister. Un context manager mono-fichier composé dans
    l'ExitStack ne doit pas les faire pointer sur le même chemin.
    """
    rendus = {}
    modules, _pu = faux_xtts(rendus)
    with mock.patch.dict(sys.modules, modules), mock.patch(
        "keraconte.engines.xtts.play_wave"
    ):
        moteur = XttsEngine({"dialogue": "a", "narration": "b"}, Vitesse(1.0))
        moteur.speak(
            "Bonjour. Rebonjour.", narration=False, generation=playback.generation
        )

    chemins = [appel["file_path"] for appel in rendus["appels"]]
    assert len(chemins) == 2
    assert chemins[0] != chemins[1]  # fichiers distincts pour le prefetch


def test_aucun_moteur_ne_rouvre_un_named_temporary_file():
    """Garde structurelle : le pattern Windows-cassant ne doit pas revenir.

    « NamedTemporaryFile » rouvert par son nom lève PermissionError sous
    Windows. Aucun test Linux ne peut échouer sur la sémantique elle-même ;
    ce grash-source est le seul garde-fou local contre une régression.
    """
    import keraconte.engines.piper as piper_mod
    import keraconte.engines.kokoro as kokoro_mod
    import keraconte.engines.xtts as xtts_mod

    for module in (piper_mod, kokoro_mod, xtts_mod):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert "NamedTemporaryFile" not in source, (
            f"{module.__name__} réutilise NamedTemporaryFile : "
            "réouverture par nom cassée sous Windows, passer par wav_temporaire."
        )
