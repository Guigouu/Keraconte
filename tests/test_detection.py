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
    drop_top_chrome,
    find_dialog,
    keep_word,
    reads_like_dialogue,
)
from quest_reader.text import clean, same_dialog  # noqa: E402
from tests.helpers import (  # noqa: E402
    BRAKMAR,
    BWORKIDAIS,
    BWORKNROLL,
    CLIQUETIS,
    ENROLEMENT,
    EXPLORANCIENNE_100,
    FIXTURES,
    HERCULE,
    HERCULE_PERMUTE,
    IDS,
    KLAKO,
    ROUKEROL,
    SAMPLES,
    THEME_BLEU,
    THEME_GARDIEN,
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


def test_lit_le_dialogue_sans_le_bandeau_d_icones():
    """Bworknroll : le ⋮ et le ✕ du haut de bulle se collaient en « ë - » en
    tête de chaque réplique. Le texte lu ne doit plus les porter."""
    texte = clean(find_dialog(load(BWORKNROLL)))
    assert texte == BWORKNROLL["expected"]
    assert "ë" not in texte


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


@pytest.mark.parametrize(
    "nombre",
    [
        "10",
        "5",
        "6",
        "20",
        "24,",  # « ouverte 24 heures sur 24, si vous... » : la virgule
        "24.",  # collée au nombre le rendait invisible à isdigit(), et il
        "10)",  # était jeté comme bruit — la phrase était lue amputée.
    ],
)
def test_keep_word_garde_toujours_les_nombres(nombre):
    """Les nombres portent les quantités de quête : les taire prive le
    joueur de l'information. La garde passe avant le test de structure,
    qui les rejetterait faute de voyelle. Un nombre PONCTUÉ (« 24, ») compte
    aussi : le français colle la virgule au chiffre, et « 24,».isdigit() est
    faux — d'où « 24 heures sur 24, » lu « 24 heures sur »."""
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


def test_drop_top_chrome_retire_le_bandeau_d_icones():
    """Vu chez Bworknroll : le ⋮ et le ✕ du haut de bulle sortent en « ë - »
    AU-DESSUS de la première ligne de texte, avec une confiance qui les fait
    passer keep_word. On les retire par géométrie : ils sont séparés du texte
    par un écart bien plus large qu'un interligne (48 px mesurés, contre ~25
    entre deux lignes), et ne pèsent que 2 mots sur 40 — minoritaires."""
    mots = mots_places(
        [(0, "-"), (13, "ë"),
         (61, "Pour commencer : des canines de Gobelin, des cheveux de"),
         (86, "Sadida et des os de Trooll. Voilà un scalpel qui te"),
         (111, "permettra de désosser un Trooll. Il y en a dans le donjon"),
         (135, "d'à côté ou dans la fosse.")]
    )
    garde = drop_top_chrome(mots)
    assert "ë" not in {mot["text"] for mot in garde}
    assert garde[0]["text"] == "Pour"


def test_drop_top_chrome_epargne_un_dialogue_propre():
    """Un dialogue sans bandeau a des interlignes réguliers : aucun écart ne
    tranche sur les autres, on ne retire rien. Sinon on amputerait la première
    ligne de tout dialogue."""
    mots = mots_places(
        [(20, "Tiens donc, une âme neutre en ces lieux."),
         (40, "Je te conseille de t'enrôler pour Brâkmar."),
         (60, "Le mal est toujours plus amusant."),
         (80, "Si ça t'intéresse, ramène-moi 10 dagues.")]
    )
    assert drop_top_chrome(mots) == mots


def test_drop_top_chrome_ne_touche_pas_les_bulles_courtes():
    """Sous 4 groupes de lignes, la médiane des écarts n'a pas de sens : on ne
    peut pas distinguer un bandeau d'un vrai interligne. On préfère laisser
    passer le bruit que risquer d'amputer un dialogue court (« perdre un
    dialogue est pire qu'en relire un »)."""
    mots = mots_places(
        [(0, "ë"),
         (61, "Bonjour aventurier."),
         (86, "Que puis-je pour toi ?")]
    )
    assert drop_top_chrome(mots) == mots


def test_drop_top_chrome_epargne_une_tete_majoritaire():
    """Garde de proportion : si le bloc au-dessus du plus grand écart porte
    l'essentiel des mots, c'est du vrai texte (un saut de paragraphe), pas un
    bandeau d'icônes — on ne retire rien même si un écart tranche."""
    mots = mots_places(
        [(20, "Voici une première phrase assez longue pour peser."),
         (40, "Elle continue sur une deuxième ligne bien remplie."),
         (60, "Et même une troisième pour faire le poids du haut."),
         (140, "brève.")]  # gros écart avant une ligne minuscule
    )
    assert drop_top_chrome(mots) == mots


@pytest.mark.parametrize(
    "fichier", ["dialogues/interface_hdv.png", "dialogues/interface_hdv_liste.png"]
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


@pytest.mark.ocr_fixture
def test_lit_un_dialogue_narratif_peu_ponctue_re_segmente():
    """Un dialogue peu ponctué, fondu à ses réponses, doit rester lu.

    Relevé en jeu chez L'Explorancienne à l'échelle d'interface 100 %. Comme
    chez Roukerol, la fermeture morphologique soude la bulle au bloc de
    réponses : le bloc n'est admis que par « splits_into_pair », donc sur le
    chemin non-apparié. Ce texte narratif est peu ponctué (ratio 0,07, sous
    MIN_PUNCTUATION_RATIO) : « reads_like_dialogue » le rejetait, alors que la
    re-segmentation avait retrouvé une paire — une preuve relationnelle, de même
    nature qu'un appariement d'emblée. Le correctif ne soumet ce test qu'aux
    blocs admis sur leur SEULE hauteur, où rien n'a prouvé le dialogue.
    """
    assert clean(find_dialog(load(EXPLORANCIENNE_100))) == EXPLORANCIENNE_100["expected"]


@pytest.mark.ocr_fixture
@pytest.mark.parametrize("fichier", THEME_GARDIEN["files"])
def test_lit_un_dialogue_quel_que_soit_le_theme(fichier):
    """Le même dialogue doit être lu sous tous les thèmes du jeu.

    Capturé en fenêtré 2710×1539 sous trois thèmes de palettes distinctes. À
    cette résolution, le bloc de réponses (~43800 px²) passait sous un seuil
    d'aire alors rapporté à l'aire de l'image (48000 px²) : écarté, plus
    d'appariement, le dialogue passait inaperçu — et ce dans les DIX thèmes, le
    seuil ne dépendant que de la géométrie, pas de la couleur. Le seuil d'aire
    est désormais absolu (MIN_AREA), une bulle ne grandissant pas avec l'aire
    de l'écran. Le texte attendu est identique aux trois thèmes, ce qui vérifie
    au passage que la couleur du thème n'influe pas sur l'OCR.
    """
    frame = cv2.imread(str(FIXTURES / fichier))
    assert frame is not None, f"fixture illisible : {fichier}"
    assert clean(find_dialog(frame)) == THEME_GARDIEN["expected"]


@pytest.mark.ocr_fixture
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

