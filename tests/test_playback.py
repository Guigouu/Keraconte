"""Tests de la lecture des sons (quest_reader.playback).

Le lecteur lit le WAV par tranches et écrit chacune dans un flux sounddevice.
On double le flux (« FauxSortie ») et la lecture du WAV : on vérifie le
câblage — génération, pause, fermeture — sans vrai périphérique audio.
"""

import pathlib
import sys
from unittest import mock

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.playback import TRANCHE_MS, Playback  # noqa: E402
from quest_reader.state import Etat, PlayerState  # noqa: E402, F401
from tests.helpers import FauxSortie  # noqa: E402


# Un faux WAV : dix tranches pleines. La taille d'une tranche se déduit de
# TRANCHE_MS, pour que le test suive le découpage réel du lecteur (sinon une
# seule tranche partirait, la boucle regroupant tout un WAV minuscule).
# « _lire_wav » est le seul point qui touche le disque — on le double pour ne
# pas écrire de fichier.
FREQUENCE = 22050
TAILLE = int(FREQUENCE * TRANCHE_MS / 1000)
FAUX_WAV = (np.zeros((10 * TAILLE, 1), dtype=np.int16), FREQUENCE)


def _playback(state=None):
    pb = Playback(state or PlayerState())
    return pb


def test_ne_joue_pas_une_generation_perimee():
    """Un son commandé avant un changement de génération ne part pas."""
    pb = _playback()
    gen = pb.begin()
    pb.bump()  # un nouveau dialogue survient
    sortie = FauxSortie()
    with mock.patch.object(pb, "_ouvrir_sortie", return_value=sortie), mock.patch.object(
        pb, "_lire_wav", return_value=FAUX_WAV
    ):
        pb.play("/tmp/x.wav", gen)  # périmé
    assert sortie.tranches == 0


def test_joue_toutes_les_tranches_de_la_generation_courante():
    """Un son de la génération courante joue jusqu'au bout."""
    pb = _playback()
    gen = pb.begin()
    sortie = FauxSortie()
    with mock.patch.object(pb, "_ouvrir_sortie", return_value=sortie), mock.patch.object(
        pb, "_lire_wav", return_value=FAUX_WAV
    ):
        pb.play("/tmp/x.wav", gen)
    assert sortie.tranches == 10
    assert sortie.ferme  # flux fermé proprement


def test_abandonne_en_cours_si_la_generation_change():
    """bump() en plein milieu coupe la lecture à la tranche suivante."""
    pb = _playback()
    gen = pb.begin()
    sortie = FauxSortie()

    # Après trois tranches, un nouveau dialogue survient : la boucle doit
    # sortir au tour suivant.
    vraie_write = sortie.write

    def write_puis_bump(tranche):
        vraie_write(tranche)
        if sortie.tranches == 3:
            pb.bump()

    sortie.write = write_puis_bump
    with mock.patch.object(pb, "_ouvrir_sortie", return_value=sortie), mock.patch.object(
        pb, "_lire_wav", return_value=FAUX_WAV
    ):
        pb.play("/tmp/x.wav", gen)
    assert sortie.tranches == 3  # pas 10 : abandonné
    assert sortie.ferme


def test_la_pause_bloque_avant_la_tranche_suivante():
    """En pause, la boucle attend ; la reprise fait repartir la lecture."""
    state = PlayerState()
    pb = _playback(state)
    gen = pb.begin()
    sortie = FauxSortie()

    vraie_write = sortie.write

    def write_puis_pause(tranche):
        vraie_write(tranche)
        if sortie.tranches == 2:
            state.pause()  # on se met en pause après deux tranches
            # Programme la reprise depuis un autre fil, sinon on bloque.
            import threading

            threading.Timer(0.05, state.reprendre).start()

    sortie.write = write_puis_pause
    with mock.patch.object(pb, "_ouvrir_sortie", return_value=sortie), mock.patch.object(
        pb, "_lire_wav", return_value=FAUX_WAV
    ):
        pb.play("/tmp/x.wav", gen)
    # La pause n'a pas fait perdre de tranche : on reprend là où on en était.
    assert sortie.tranches == 10


def test_bump_coupe_le_flux_en_cours():
    """bump() ferme le flux courant, comme il tuait le processus avant."""
    pb = _playback()
    sortie = FauxSortie()
    pb.current = sortie
    pb.bump()
    assert sortie.ferme
