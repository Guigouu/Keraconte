"""Tests de détection et de nettoyage, sur de vraies captures de Dofus.

Les cas négatifs sont fabriqués en masquant une partie d'une capture réelle
plutôt qu'à partir d'images inventées : les couleurs du jeu restent donc
présentes autour de la zone effacée.
"""

import pathlib
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader import clean, find_dialog, fingerprint  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Position des blocs dans chaque capture, relevée à la main.
BRAKMAR = {
    "file": "dialogue_brakmar.png",
    "dialogue": (1110, 490, 690, 270),
    "replies": (1110, 735, 690, 110),
    "expected": "C'est moi le plus grand, le plus magique, le plus doué des "
    "forgemages du monde. Mes armes sont surpuissantes et chacune est une "
    "pièce unique.",
}
TOKAGEKO = {
    "file": "dialogue_tokageko.png",
    "dialogue": (20, 40, 660, 140),
    "replies": (20, 180, 660, 220),
    "expected": "Pssst, approche-toi. Si tu as des badges d'expédition, j'ai "
    "quelques marchandises exclusives pour toi.",
}
SAMPLES = [BRAKMAR, TOKAGEKO]
IDS = ["brakmar", "tokageko"]


def load(sample):
    frame = cv2.imread(str(FIXTURES / sample["file"]))
    assert frame is not None, f"fixture illisible : {sample['file']}"
    return frame


def erase(frame, box):
    """Recouvre une zone d'une couleur de décor, pour simuler son absence."""
    x, y, w, h = box
    frame = frame.copy()
    frame[y : y + h, x : x + w] = (90, 160, 90)
    return frame


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_lit_le_dialogue(sample):
    assert clean(find_dialog(load(sample))) == sample["expected"]


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_ignore_sans_bulle(sample):
    frame = erase(load(sample), sample["dialogue"])
    assert find_dialog(frame) is None


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_ignore_sans_bloc_de_reponses(sample):
    """Sans réponses en dessous, ce n'est pas un dialogue de PNJ."""
    frame = erase(load(sample), sample["replies"])
    assert find_dialog(frame) is None


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_empreinte_stable_malgre_le_bruit(sample):
    """Le même dialogue ne doit être lu qu'une fois.

    L'OCR laisse des fragments parasites variables autour du texte ; c'est
    ce qui provoquait une relecture en boucle.
    """
    frame = load(sample)
    rng = np.random.default_rng(0)
    empreintes = set()
    for index in range(25):
        noisy = frame
        if index:
            noise = rng.integers(-3, 4, frame.shape, dtype=np.int16)
            noisy = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        text = find_dialog(noisy)
        if text:
            empreintes.add(fingerprint(clean(text)))
    assert len(empreintes) == 1, f"{len(empreintes)} empreintes au lieu d'une"


def test_clean_retire_les_parasites_de_bordure():
    brut = "E x C'est moi le plus grand. Mes armes sont uniques. \\ ; ."
    assert clean(brut) == "C'est moi le plus grand. Mes armes sont uniques."


def test_clean_recolle_les_lignes():
    assert clean("Bonjour toi,\nque veux-tu ?") == "Bonjour toi, que veux-tu ?"


def test_empreinte_ignore_les_bords_bruites():
    base = "Pssst, approche-toi. Si tu as des badges, j'ai des marchandises."
    assert fingerprint(base) == fingerprint(base + " —…")
