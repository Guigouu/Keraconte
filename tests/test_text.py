"""Tests du nettoyage et de la comparaison de texte (keraconte.text)."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte.text import (  # noqa: E402
    clean,
    pronounce,
    same_dialog,
    speakable,
    split_narration,
    split_sentences,
    strip_choices,
)


def test_clean_retire_la_ponctuation_isolee_en_queue():
    brut = "C'est moi le plus grand. Mes armes sont uniques. \\ ; ."
    assert clean(brut) == "C'est moi le plus grand. Mes armes sont uniques."


def test_clean_recolle_les_lignes():
    assert clean("Bonjour toi,\nque veux-tu ?") == "Bonjour toi, que veux-tu ?"


def test_empreinte_ignore_les_bords_bruites():
    base = "Pssst, approche-toi. Si tu as des badges, j'ai des marchandises."
    assert same_dialog(base, base + " —…")


def test_clean_garde_les_didascalies():
    """Les astérisques marquent les actions : ils doivent survivre."""
    brut = "* il sourit * Salut. Comment vas-tu ? \\ ; ."
    assert clean(brut) == "* il sourit * Salut. Comment vas-tu ?"


def test_clean_garde_une_didascalie_finale():
    assert clean("Bonjour toi. * il part *") == "Bonjour toi. * il part *"


def test_clean_accepte_l_espace_avant_la_ponctuation():
    """En français, « ? » et « ! » sont précédés d'une espace."""
    assert clean("Salut ! Ca va ? \\ ; .") == "Salut ! Ca va ?"


@pytest.mark.parametrize(
    "texte, attendu",
    [
        (
            "* se racle la gorge * Bonjour à toi.",
            [(True, "se racle la gorge"), (False, "Bonjour à toi.")],
        ),
        (
            "Bonjour. * il part *",
            [(False, "Bonjour."), (True, "il part")],
        ),
        (
            "Salut à toi, voyageur.",
            [(False, "Salut à toi, voyageur.")],
        ),
    ],
)
def test_separe_narration_et_dialogue(texte, attendu):
    assert split_narration(texte) == attendu


@pytest.mark.parametrize("ecrit", ["Pssst", "Psst", "Pst", "PSSST"])
def test_onomatopee_recoit_une_voyelle(ecrit):
    """Sans voyelle, les moteurs épellent l'onomatopée lettre à lettre."""
    assert pronounce(f"{ecrit}, approche-toi.") == "Pssit, approche-toi."


@pytest.mark.parametrize("mot", ["Post", "Pas", "Peste", "poste"])
def test_prononciation_ne_touche_pas_les_vrais_mots(mot):
    assert pronounce(f"Le {mot} est là.") == f"Le {mot} est là."


def test_decoupe_en_phrases():
    texte = "Bonjour. Comment vas-tu ? Très bien !"
    assert split_sentences(texte) == [
        "Bonjour.",
        "Comment vas-tu ?",
        "Très bien !",
    ]


def test_decoupe_garde_les_points_de_suspension():
    assert split_sentences("Attends… J'arrive.") == ["Attends…", "J'arrive."]


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("Cliquetis", True),
        ("10", True),
        ("-", False),
        ("...", False),
        ("", False),
        (" * ", False),
    ],
)
def test_segment_sans_contenu_prononcable_est_rejete(texte, attendu):
    """Un segment sans lettre ni chiffre fait planter les moteurs.

    Kokoro ne produit aucun phonème pour de la ponctuation seule, puis
    concatène une liste vide : « need at least one array to concatenate ».
    """
    assert speakable(texte) is attendu


def test_didascalies_collees_ne_laissent_pas_de_segment_vide():
    """Vu en jeu sur « * *Cliquetis*-*Cliquecliquetis* ».

    Entre deux didascalies accolées, le texte hors astérisques se réduit au
    trait d'union : un segment que la synthèse ne peut pas prononcer.
    """
    segments = split_narration("* *Cliquetis*-*Cliquecliquetis*")
    # L'astérisque isolée en tête décale les segments : leur étiquetage
    # narration/dialogue est ici peu fiable, seul le contenu importe.
    assert [contenu for _, contenu in segments] == ["Cliquetis", "Cliquecliquetis"]


@pytest.mark.parametrize(
    "texte",
    [
        "Tu es blessé, aventurier.",
        "Ah ! Te voilà enfin.",
        "Hé ! Attends un peu.",
        "Non ! Pas question.",
        "STOP. Ne bouge plus.",
        "Je suis GERARD, le forgemage.",
        "ATTENTION ! Le donjon est dangereux.",
        "Œuvre de mes mains, regarde.",
    ],
)
def test_clean_garde_le_premier_mot(texte):
    """Un début à mot court ou suivi de « ! » ne doit pas être amputé.

    Le bruit d'icônes se reconnaît aux lettres isolées, pas à la longueur
    du premier mot : « Tu es » et « STOP. » sont du vrai texte.
    """
    assert clean(texte) == texte


def test_empreinte_tolere_une_lettre_ocr_instable():
    """Une lettre qui flippe d'une image à l'autre ne doit pas relancer la lecture."""
    base = "C'est moi le plus grand, le plus doué des forgemages du monde."
    assert same_dialog(base, base.replace("doué", "doub"))
    assert same_dialog(base, base.replace("grand", "grancl"))


def test_empreinte_distingue_deux_dialogues():
    """Deux répliques différentes doivent bien être lues toutes les deux."""
    assert not same_dialog(
        "C'est moi le plus grand des forgemages du monde.",
        "Reviens me voir quand tu auras trouvé les ressources.",
    )


@pytest.mark.parametrize(
    "premier, second",
    [
        ("Va chercher 5 peaux de bouftou.", "Va chercher 6 peaux de bouftou."),
        ("Il m'en faut 10.", "Il m'en faut 20."),
    ],
)
def test_empreinte_distingue_les_quantites(premier, second):
    """Deux quêtes ne différant que par un nombre restent deux dialogues.

    Les confondre tairait la seconde : une relecture gêne, un dialogue
    manquant prive le joueur de l'information.
    """
    assert not same_dialog(premier, second)


@pytest.mark.parametrize(
    "texte",
    [
        "SES armes sont surpuissantes et uniques.",
        "TU es le bienvenu ici, aventurier.",
    ],
)
def test_clean_garde_les_vrais_mots_en_capitales(texte):
    """Un mot en capitales suivi d'un vrai mot n'est pas du bruit."""
    assert clean(texte) == texte


@pytest.mark.parametrize(
    "brut, attendu",
    [
        (
            "Tu te fourres le doigt dans l'œil. .",
            "Tu te fourres le doigt dans l'œil.",
        ),
        ("Reviens me voir plus tard.", "Reviens me voir plus tard."),
        ("Salut !", "Salut !"),
    ],
)
def test_clean_retire_les_capitales_parasites_en_queue(brut, attendu):
    """Les icônes de fin sortent en capitales suivies d'un point.

    Le parasite lui-même (« CON », « SE x ») est écarté au mot, par
    « keep_word » ; il reste à « clean » à ne pas ancrer la coupure sur la
    ponctuation qu'il laisse derrière lui.
    """
    assert clean(brut) == attendu


@pytest.mark.parametrize(
    "texte",
    [
        "Direction le NORD.",
        "Attention au BOSS !",
        "Je m'appelle GERARD.",
        "Cherche la ZAAP.",
    ],
)
def test_clean_garde_un_vrai_mot_final_en_capitales(texte):
    """Un mot en capitales dans la phrase n'est pas un parasite."""
    assert clean(texte) == texte


@pytest.mark.parametrize(
    "texte",
    [
        "Je dois partir. Rester ici serait dangereux.",
        "Bonjour à toi. Réfléchir avant d'agir, voilà mon conseil.",
    ],
)
def test_clean_seul_ne_retire_jamais_de_phrase(texte):
    """Hors bloc fusionné, un infinitif en tête de phrase est du dialogue.

    « clean » s'applique à toutes les captures : y glisser le retrait des
    choix ferait disparaître ces phrases sans trace.
    """
    assert clean(texte) == texte


@pytest.mark.parametrize(
    "texte",
    [
        "Bonjour. Rester ici serait dangereux.",
        "Je dois partir. Rester ici serait dangereux.",
        "Bonjour à toi. Réfléchir avant d'agir, voilà mon conseil.",
    ],
)
def test_une_phrase_ouvrant_sur_un_infinitif_survit(texte):
    """La perte que cette refonte devait fermer.

    Reconnaître un choix à son verbe à l'infinitif effaçait toute phrase de
    PNJ construite ainsi : « Rester ici serait dangereux. » disparaissait
    sans trace. Le retrait ne se fait plus qu'à la géométrie.
    """
    assert strip_choices(clean(texte)) == texte


@pytest.mark.parametrize(
    "texte",
    [
        "Je vais te le donner. Tu dois partir.",
        "Il faut y aller. Je peux t'aider.",
    ],
)
def test_clean_garde_une_phrase_finissant_par_un_infinitif(texte):
    """Un infinitif en fin de phrase n'est pas forcément un choix."""
    assert clean(texte) == texte


def test_un_chiffre_invente_par_l_ocr_ne_relance_pas_la_lecture():
    """Vu en jeu : « t'en 1 occuper » puis « t'en —Loccuper ».

    Exiger l'égalité stricte des nombres protège les quantités de quête,
    mais l'OCR invente parfois un chiffre d'une image à l'autre. Quand un
    seul des deux textes en porte, c'est du bruit, pas une quantité.
    """
    base = (
        "Dyaul est paché pendant ton abchenche et a dit que tu devais "
        "t'en 1 occuper."
    )
    variante = base.replace("t'en 1 occuper.", "t'en —Loccuper.")
    assert same_dialog(base, variante)


def test_un_chiffre_isole_dans_une_longue_replique_ne_relance_pas_la_lecture():
    """Les deux captures réelles du dialogue de Brâkmar, relu en entier.

    Chacune porte un chiffre inventé par l'OCR, à un endroit différent : un
    « 4 » dans « celui qui oserait » à une image, un « 2 » en tête à la
    suivante. Compter les nombres ne suffit pas à les départager — il y en a
    un de chaque côté — alors que le reste concorde à 0,99.
    """
    premier = (
        "L'avantage quand on dirige une cité comme celle de Brâkmar, c'est "
        "que personne ne s'étonne que certains individus disparaissent "
        "subitement. Quel plaisir de pouvoir laisser libre cours à ses "
        "pulsions sans avoir à se justifier ! De toute façon, celui qui 4 "
        "oserait me tenir tête finirait tout droit au cœur du volcan."
    )
    second = (
        "2 L'avantage quand on dirige une cité comme celle de Brâkmar, c'est "
        "que personne ne s'étonne que certains individus disparaissent "
        "subitement. Quel plaisir de pouvoir laisser libre cours A à ses "
        "pulsions sans avoir à se justifier ! De toute façon, celui qui "
        "oserait me tenir tête finirait tout droit au cœur du volcan."
    )
    assert same_dialog(clean(premier), clean(second))


def test_deux_quantites_restent_deux_dialogues():
    """La tolérance ci-dessus ne doit pas rouvrir la confusion des quêtes."""
    assert not same_dialog(
        "Rapporte-moi 5 peaux de bouftou maintenant.",
        "Rapporte-moi 6 peaux de bouftou maintenant.",
    )
