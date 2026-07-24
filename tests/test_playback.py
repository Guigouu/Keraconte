"""Tests de la lecture des sons (quest_reader.playback)."""

import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.playback import Playback  # noqa: E402
from tests.helpers import FauxProcessus  # noqa: E402


def test_playback_refuse_de_jouer_apres_un_arret():
    """Une fois le dialogue fermé, plus aucun son ne doit sortir.

    Les phrases déjà synthétisées attendent leur tour : sans ce refus, elles
    partiraient l'une après l'autre alors que la bulle a disparu.
    """
    playback = Playback()
    playback.stop()
    with mock.patch("subprocess.Popen") as popen:
        playback.play("/tmp/inexistant.wav")
    popen.assert_not_called()


def test_playback_coupe_le_son_en_cours():
    """L'ordre vient du fil de capture pendant que le son joue."""
    playback = Playback()
    processus = FauxProcessus()
    with mock.patch("subprocess.Popen", return_value=processus):
        playback.play("/tmp/quelconque.wav")
    # Le son est allé au bout ici ; on coupe celui d'après, en vol.
    playback.current = processus
    playback.stop()
    assert processus.tue


def test_playback_rouvre_a_la_reprise():
    """Un nouveau dialogue doit lever l'interdiction, sinon plus rien ne parle."""
    playback = Playback()
    playback.stop()
    playback.resume()
    with mock.patch("subprocess.Popen", return_value=FauxProcessus()) as popen:
        playback.play("/tmp/quelconque.wav")
    popen.assert_called_once()
