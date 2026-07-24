"""Tests de la lecture des sons (quest_reader.playback)."""

import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.playback import Playback  # noqa: E402
from tests.helpers import FauxProcessus  # noqa: E402


def test_playback_ne_joue_pas_une_generation_perimee():
    """Un son commandé avant un changement de génération ne part pas.

    Garantie qui remplace « stopped » : couper puis reprendre pour un
    nouveau dialogue ne laisse pas jouer l'ancien.
    """
    playback = Playback()
    gen = playback.begin()          # génération de l'ancien dialogue
    playback.bump()                 # un nouveau dialogue survient
    with mock.patch("subprocess.Popen") as popen:
        playback.play("/tmp/x.wav", gen)   # son de l'ancien : périmé
    popen.assert_not_called()


def test_playback_joue_la_generation_courante():
    """Un son de la génération courante part bien."""
    playback = Playback()
    gen = playback.begin()
    with mock.patch("subprocess.Popen", return_value=FauxProcessus()) as popen:
        playback.play("/tmp/x.wav", gen)
    popen.assert_called_once()


def test_playback_coupe_le_son_en_cours():
    """bump() tue le processus en vol."""
    playback = Playback()
    processus = FauxProcessus()
    playback.current = processus
    playback.bump()
    assert processus.tue
