"""Tests de détection et de nettoyage, sur de vraies captures de Dofus.

Les cas négatifs sont fabriqués en masquant une partie d'une capture réelle
plutôt qu'à partir d'images inventées : les couleurs du jeu restent donc
présentes autour de la zone effacée.
"""

import pathlib
import sys
import types
from unittest import mock

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.detection import (  # noqa: E402
    drop_replies,
    find_dialog,
    keep_word,
    reads_like_dialogue,
)
from quest_reader.text import clean, same_dialog  # noqa: E402
from tests.helpers import (  # noqa: E402
    BRAKMAR,
    BWORKIDAIS,
    CLIQUETIS,
    ENROLEMENT,
    FIXTURES,
    HERCULE,
    HERCULE_PERMUTE,
    IDS,
    KLAKO,
    ROUKEROL,
    SAMPLES,
    THEME_BLEU,
    TOKAGEKO,
    ecran,
    erase,
    faux_xtts,
    load,
    mots_places,
    texte_de,
)


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
    for index in range(25):
        noisy = frame
        if index:
            noise = rng.integers(-3, 4, frame.shape, dtype=np.int16)
            noisy = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        text = find_dialog(noisy)
        if text:
            assert same_dialog(clean(text), sample["expected"])


# Les fragments d'icônes ne se reconnaissent plus par leur forme écrite mais
# au mot, avec la confiance de l'OCR. Les confiances ci-dessous sont celles
# relevées sur les fixtures via image_to_data ; les cas restent les mêmes,
# seul leur point d'entrée change.
@pytest.mark.parametrize(
    "texte, confiance",
    [
        ("E", 36),  # brakmar
        ("e", 43),  # brakmar
        (":", 50),  # brakmar
        ("x", 95),  # brakmar : bien noté, mais sans voyelle et isolé
        ("PE", 24),  # cliquetis
        ("A", 44),  # cliquetis
        ("R", 93),  # tokageko : bien noté, rejeté sur la structure
        ("SE", 30),  # paires de capitales laissées par les icônes
        ("2E", 40),  # chiffre et capitale collés
        ("3A", 40),
        ("A3", 40),  # vu en plein milieu de phrase, pas seulement aux bords
        ("»/", 30),
        ("SN", 30),
        ("dn", 30),
        ("2S", 30),
        ("Â", 30),
        ("Ë", 30),
        ("_", 30),
        ("CON", 30),
    ],
)
def test_keep_word_rejette_le_bruit_d_icone(texte, confiance):
    assert not keep_word(texte, confiance)


@pytest.mark.parametrize(
    "texte, confiance",
    [
        ("C'est", 92),  # élision : l'apostrophe rend le mot plausible
        ("t'enrôler", 41),  # vrai mot mal noté, sauvé par sa longueur
        ("lieux,", 53),
        ("Si", 83),  # vrais mots courts, tous bien notés
        ("tu", 83),
        ("as", 91),
        ("à", 96),
        ("Œuvre", 80),
        ("NORD.", 80),  # un vrai mot en capitales appartient à la phrase
        ("STOP.", 80),
        ("Pssst,", 91),  # onomatopée sans voyelle, mais longue et bien notée
        ("*Cliquetis*", 87),
    ],
)
def test_keep_word_garde_les_vrais_mots(texte, confiance):
    assert keep_word(texte, confiance)


@pytest.mark.parametrize("nombre", ["10", "5", "6", "20"])
def test_keep_word_garde_toujours_les_nombres(nombre):
    """Les nombres portent les quantités de quête : les taire prive le
    joueur de l'information. La garde passe avant le test de structure,
    qui les rejetterait faute de voyelle."""
    assert keep_word(nombre, 30)


def test_keep_word_laisse_passer_un_nombre_parasite():
    """Contrepartie assumée de la garde ci-dessus : un « 64 » venu d'une
    icône est indiscernable d'une quantité de quête. Le plan le classait
    comme du bruit à rejeter ; la contrainte sur les nombres l'emporte, un
    mot lu en trop coûtant moins qu'une quantité tue."""
    assert keep_word("64", 30)


def test_des_lignes_permutees_restent_le_meme_dialogue():
    """L'OCR intervertit les lignes d'une image à l'autre.

    Le ratio de séquence tombe alors à 0,74 et la réplique repartait en
    lecture ; le vocabulaire, lui, ne change pas.
    """
    assert same_dialog(clean(HERCULE), clean(HERCULE_PERMUTE))


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (
            [("SE", 30), ("x", 49), ("L'élevage", 90), ("des", 90),
             ("dragodindes,", 90), ("c'est", 90), ("ma", 90), ("grande", 90),
             ("passion.", 90)],
            "L'élevage des dragodindes, c'est ma grande passion.",
        ),
        (
            [("E", 36), ("x", 49), ("On", 90), ("me", 90), ("considère", 90),
             ("comme", 90), ("le", 90), ("meilleur", 90), ("éleveur.", 90)],
            "On me considère comme le meilleur éleveur.",
        ),
    ],
)
def test_retire_les_paires_de_capitales(mots, attendu):
    """Les icônes sortent aussi en paires de capitales : « SE x »."""
    assert filtre(mots) == attendu


def filtre(mots):
    """Applique « keep_word » à une suite de (mot, confiance), comme le
    fait « read_words » sur la sortie d'image_to_data."""
    return clean(" ".join(mot for mot, conf in mots if keep_word(mot, conf)))


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (
            [("2E", 40), ("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90),
             ("chaud", 90), ("ici…", 90)],
            "Qu'est-ce qu'il fait chaud ici…",
        ),
        (
            [("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90), ("chaud", 90),
             ("ici…", 90), ("x.", 40)],
            "Qu'est-ce qu'il fait chaud ici…",
        ),
        (
            [("3A", 40), ("Bonjour", 90), ("aventurier.", 90)],
            "Bonjour aventurier.",
        ),
        (
            [("Bonjour", 90), ("aventurier.", 90), ("e", 43)],
            "Bonjour aventurier.",
        ),
    ],
)
def test_retire_le_bruit_colle_et_minuscule(mots, attendu):
    """Le bruit d'icônes colle chiffres et capitales (« 2E »), ou traîne
    une minuscule isolée en queue (« x. »)."""
    assert filtre(mots) == attendu


def test_deux_lectures_bruitees_restent_un_seul_dialogue():
    """Le bruit ne doit pas faire relire : c'est ce qui doublait la lecture."""
    phrase = [("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90), ("chaud", 90),
              ("ici…", 90)]
    assert same_dialog(
        filtre([("2E", 40)] + phrase),
        filtre(phrase + [("x.", 40)]),
    )


@pytest.mark.parametrize(
    "sample", [CLIQUETIS, ENROLEMENT], ids=["cliquetis", "enrolement"]
)
def test_lit_les_bulles_collees_aux_reponses(sample):
    """Bulle et réponses se touchent : la morphologie les fond en un bloc.

    Ces deux captures n'étaient pas détectées du tout, faute de trouver la
    paire dialogue/réponses que la détection exigeait.
    """
    assert clean(find_dialog(load(sample))) == sample["expected"]


@pytest.mark.parametrize(
    "bruit",
    [
        [],
        [(115, "x _")],
        [(115, "Â 3 Ë x")],
    ],
)
def test_drop_replies_retire_les_reponses_du_joueur(bruit):
    """Bloc fusionné : les choix du joueur suivent le dialogue à l'OCR.

    Ils ne se reconnaissent plus à leur infinitif — ce critère effaçait de
    vraies phrases — mais au large blanc qui les sépare du dialogue. Les
    fragments d'icônes restés sur la dernière ligne du dialogue ne doivent
    pas empêcher la coupure.
    """
    mots = mots_places(
        [(95, "Je te conseille de t'enrôler.")]
        + bruit
        + [(211, "Prendre le temps d'y réfléchir."),
           (251, "L'interroger à propos de l'édit.")]
    )
    assert texte_de(drop_replies(mots)) == "Je te conseille de t'enrôler."


@pytest.mark.parametrize(
    "bruit, article",
    [
        ([], "L'"),
        ([(115, "x _")], "L'"),
        ([(115, "Â 3 Ë x")], ""),
        ([(115, "Â 3 Ë x")], "L'"),
    ],
)
def test_drop_replies_tolere_le_bruit_et_la_capitale_perdue(bruit, article):
    """Vu en jeu : fragments accentués avant le choix, article amputé.

    L'OCR lit « L'interroger » sans son article. Le critère grammatical
    exigeait une capitale initiale et laissait alors passer le choix ; la
    géométrie, elle, ne dépend pas de la façon dont le choix est écrit.
    """
    mots = mots_places(
        [(95, "Elles serviront à entraîner les bras cassés.")]
        + bruit
        + [(211, "Prendre le temps d'y réfléchir."),
           (251, f"{article}interroger à propos de l'édit."),
           (303, "p")]
    )
    assert texte_de(drop_replies(mots)) == "Elles serviront à entraîner les bras cassés."


@pytest.mark.parametrize(
    "fichier", ["interface_hdv.png", "interface_hdv_liste.png"]
)
def test_ignore_les_panneaux_d_interface(fichier):
    """L'hôtel des ventes ne doit pas être lu.

    Accepter un bloc sans réponses appariées, pour rattraper les bulles
    soudées à leurs choix, laissait aussi passer les panneaux d'interface :
    « Rechercher », « Toutes catégories » étaient énoncés. Une bulle reste
    plus large que haute ; un panneau s'étire vers le bas.
    """
    frame = cv2.imread(str(FIXTURES / fichier))
    assert frame is not None, f"fixture illisible : {fichier}"
    assert find_dialog(frame) is None


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (["Bonjour", "à", "toi,", "aventurier."], True),
        (["FILTRES", "ÉTABLE", "ENCLOS", "ACCOUPLEMENT"], False),
        (["Rechercher", "Niveau", "Toutes", "catégories"], False),
        ([], False),
    ],
)
def test_distingue_un_dialogue_d_un_panneau(mots, attendu):
    """Un panneau aligne des étiquettes, un dialogue enchaîne des phrases.

    La géométrie ne les séparait pas : le panneau des enclos affiche le
    même rapport largeur/hauteur qu'une bulle soudée à ses réponses.
    """
    assert reads_like_dialogue([{"text": mot} for mot in mots]) is attendu


def test_garde_l_exclamation_finale():
    """« Bienvenue ! » était amputé de sa dernière phrase.

    Le français détache « ! » du mot : l'OCR le rend comme un mot à part,
    que le filtre de bruit écartait faute de voyelle. La phrase n'étant
    alors plus close, le nettoyage de queue emportait « Bienvenue » avec.
    """
    assert clean(find_dialog(load(KLAKO))) == KLAKO["expected"]


@pytest.mark.parametrize("signe", ["!", "?", "…", "!!"])
def test_la_ponctuation_forte_survit_au_filtre(signe):
    """Elle porte l'intonation : c'est l'objet même de la lecture."""
    assert keep_word(signe, 90) is True


def test_lit_un_dialogue_fondu_a_ses_reponses():
    """Bulle et réponses soudées en un contour : le dialogue doit rester lu.

    Relevé en jeu chez Roukerol de Nerouz : le dialogue n'était pas lu du tout.
    La fermeture morphologique soudait la bulle au bloc de réponses en un seul
    contour, et l'appariement ne trouvait plus sa paire. « splits_into_pair »
    re-segmente le bloc à partir du masque d'avant fermeture pour retrouver la
    paire, sans toucher au texte lu par l'OCR.
    """
    assert clean(find_dialog(load(ROUKEROL))) == ROUKEROL["expected"]


def test_lit_un_dialogue_court_apparie_a_ses_reponses():
    """Une réplique courte, appariée à ses réponses, doit rester lue.

    Relevé en jeu chez Gobriel et un Bwork : « Zog Zog à toâ. » ou « Toâ
    promis aider moâ. » n'étaient pas lus. La bulle était pourtant trouvée et
    le bloc de réponses apparié : c'est le plancher « MIN_CHARS » qui, en bout
    de course, écartait ces textes trop brefs. Or l'appariement — le signal
    relationnel — a déjà prouvé que c'est un dialogue : le plancher long n'a
    plus lieu d'être sur ce chemin.
    """
    assert clean(find_dialog(load(BWORKIDAIS))) == BWORKIDAIS["expected"]

