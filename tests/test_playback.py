"""Tests de la lecture des sons (quest_reader.playback).

Le lecteur lit le WAV par tranches et écrit chacune dans un flux sounddevice.
On double le flux (« FauxSortie ») et la lecture du WAV : on vérifie le
câblage — génération, pause, fermeture — sans vrai périphérique audio.
"""

import os
import pathlib
import sys
from unittest import mock

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.playback import TRANCHE_MS, Playback, wav_temporaire  # noqa: E402
from quest_reader.state import Etat, PlayerState  # noqa: E402, F401
from tests.helpers import FauxSortie  # noqa: E402


def test_wav_temporaire_donne_un_chemin_reouvrable_par_nom():
    """Le helper rend un CHEMIN écrivable/lisible par son nom, sans handle.

    C'est le contrat dont les moteurs dépendent : écrire le WAV puis le
    rejouer en le rouvrant par son nom. Le fichier existe pendant le bloc et
    disparaît à la sortie. (La sécurité Windows elle-même — pas de
    PermissionError sur réouverture — ne se vérifie qu'en CI Windows : sous
    Linux l'ouverture concurrente est permise inconditionnellement.)
    """
    with wav_temporaire() as path:
        assert os.path.exists(path)
        # Réouvrable par nom, en écriture puis en lecture.
        with open(path, "wb") as f:
            f.write(b"RIFFtest")
        with open(path, "rb") as f:
            assert f.read() == b"RIFFtest"
    # Nettoyé à la sortie du bloc.
    assert not os.path.exists(path)


def test_wav_temporaire_survit_a_un_fichier_deja_supprime():
    """L'« unlink » de sortie ne doit pas lever si le fichier a disparu.

    Sous Windows, un handle de lecture encore ouvert empêcherait la
    suppression : le helper avale l'OSError. On simule ici la disparition du
    fichier avant la sortie du bloc — la sortie doit rester silencieuse.
    """
    with wav_temporaire() as path:
        os.unlink(path)  # disparu avant la fin du bloc
    # Aucune exception propagée : le test passe s'il atteint cette ligne.
    assert not os.path.exists(path)


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


def test_sans_peripherique_audio_l_app_continue():
    """Pas de périphérique / sounddevice absent : « play » le signale et
    revient sans lever (le design veut que l'app continue de tourner)."""
    pb = _playback()
    gen = pb.begin()
    with mock.patch.object(
        pb, "_lire_wav", return_value=FAUX_WAV
    ), mock.patch.object(
        pb, "_ouvrir_sortie", side_effect=OSError("PortAudio absent")
    ):
        pb.play("/tmp/x.wav", gen)  # ne doit pas lever
    # Le flux n'a pas pu s'ouvrir : rien n'est resté accroché.
    assert pb.current is None


def test_bump_ne_ferme_pas_le_flux_lui_meme():
    """bump() n'incrémente QUE la génération, sans toucher au flux.

    Fermer un OutputStream depuis un autre thread pendant que le thread de
    lecture est dans « write() » corrompt le tas PortAudio (segfault vu en
    jeu). La coupure passe donc par la génération seule : c'est la boucle de
    « play » qui ferme le flux, dans son propre thread (voir
    « test_abandonne_en_cours_si_la_generation_change »).
    """
    pb = _playback()
    sortie = FauxSortie()
    pb.current = sortie
    gen_avant = pb.generation
    pb.bump()
    assert pb.generation == gen_avant + 1  # une nouvelle génération est ouverte
    assert not sortie.ferme  # mais le flux n'est PAS fermé depuis « bump »


class _FauxSounddevice:
    """Tient le rôle du module sounddevice pour « _choisir_peripherique »."""

    def __init__(self, peripheriques):
        self._peripheriques = peripheriques

    def query_devices(self):
        return self._peripheriques


def test_choisir_prefere_pipewire_au_defaut_alsa():
    """Sur un système PipeWire, on évite le « default » ALSA (EBADFD) et on
    prend « pipewire », qui route proprement."""
    pb = _playback()
    peripheriques = [
        {"name": "default", "max_output_channels": 128},
        {"name": "pulse", "max_output_channels": 32},
        {"name": "pipewire", "max_output_channels": 128},
    ]
    index = pb._choisir_peripherique(_FauxSounddevice(peripheriques))
    assert index == 2  # « pipewire » est préféré, même après « pulse »


def test_choisir_renvoie_none_sans_pipewire_ni_pulse():
    """Sans PipeWire ni pulse (autre OS, machine nue), on laisse le défaut de
    sounddevice (index None) : portabilité."""
    pb = _playback()
    peripheriques = [
        {"name": "default", "max_output_channels": 2},
        {"name": "hw:0,0", "max_output_channels": 2},
    ]
    index = pb._choisir_peripherique(_FauxSounddevice(peripheriques))
    assert index is None
