"""Tests de la décision de genre (keraconte.genre, ADR-0001).

L'invariant transversal : dans le doute, l'abstention — et l'abstention doit
rendre le canal masculin, c'est-à-dire la voix d'avant, à l'identique.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte.genre import (  # noqa: E402
    Canal,
    FEMININ,
    MASCULIN,
    canal_pour,
    chercher_replique,
    decider_genre,
    genre_par_accords,
    genre_par_lexique,
    jetons,
)
from tests.helpers import images, lecteur_nu  # noqa: E402


# --- Signal 1 : lexique genré ------------------------------------------------


def test_lexique_metier_masculin_en_auto_designation():
    """« Je suis Klako, chasseur » — le métier porte le genre (cas relevé
    dans le plan d'origine, où il servait de contre-exemple aux accords)."""
    assert genre_par_lexique("Je suis Klako, chasseur de dragodindes.") == MASCULIN


def test_lexique_titre_feminin_en_auto_designation():
    assert genre_par_lexique("Je suis la gardienne de ces lieux.") == FEMININ


def test_lexique_ne_vote_pas_hors_auto_designation():
    """Un PNJ qui PARLE d'un chasseur ne dit rien de lui-même."""
    assert genre_par_lexique("Va voir le chasseur du village.") is None


def test_lexique_contradictoire_s_abstient():
    """Deux genres votés = contradiction : on s'abstient, on ne tranche pas."""
    texte = "Je suis chasseur le jour. Je suis la gardienne la nuit."
    assert genre_par_lexique(texte) is None


def test_lexique_epicene_ne_vote_pas():
    """« forgemage » ne porte pas le genre : il n'est pas dans le lexique."""
    assert genre_par_lexique("Je suis le plus doué des forgemages.") is None


# --- Signal 2 : accords en première personne --------------------------------


def test_accord_feminin():
    assert genre_par_accords("Je suis venue de loin pour te voir.") == FEMININ


def test_accord_masculin():
    assert genre_par_accords("Je suis venu de loin pour te voir.") == MASCULIN


def test_accord_du_joueur_ne_vote_pas():
    """« Tu es venue » accorde le JOUEUR, pas le PNJ : le piège documenté
    dans le plan d'origine. Seules les formes en « je » comptent."""
    assert genre_par_accords("Tu es venue jusqu'ici pour rien.") is None


# --- Signal 3 : table par empreinte ------------------------------------------


def _table(*entrees):
    return {"entrees": [dict(entree) for entree in entrees]}


REPLIQUE = "Va chercher cinq peaux de bouftou dans la plaine des Cania."
AUTRE = "L'hôtel des ventes ferme ses portes à la tombée de la nuit."


def test_table_reconnait_une_replique_malgre_le_bruit_ocr():
    """Quelques lettres tordues par l'OCR ne décrochent pas le rapprochement.

    C'est la mesure du dépôt qui le garantit : deux lectures d'un même texte
    s'écartent de 0,00 à 0,31, deux textes distincts de 1,86 à 4,11 — le
    seuil (0,6) tient au milieu de la bande vide.
    """
    table = _table(
        {"jetons": sorted(jetons(REPLIQUE)), "genre": FEMININ},
        {"jetons": sorted(jetons(AUTRE)), "genre": MASCULIN},
    )
    bruitee = REPLIQUE.replace("bouftou", "boufteu").replace("peaux", "peaux,")
    assert chercher_replique(bruitee, table) == FEMININ


def test_table_replique_inconnue_s_abstient():
    table = _table({"jetons": sorted(jetons(REPLIQUE)), "genre": FEMININ})
    assert chercher_replique("Rien à voir avec le contenu chargé.", table) is None


def test_table_replique_ambigue_s_abstient():
    """Une réplique partagée par des PNJ des deux genres est marquée par la
    GÉNÉRATION : le runtime s'abstient dessus, par construction."""
    table = _table({"jetons": sorted(jetons(REPLIQUE)), "genre": "ambigu"})
    assert chercher_replique(REPLIQUE, table) is None


def test_table_sans_marge_s_abstient():
    """Deux entrées presque identiques : rien ne départage, on s'abstient.

    La marge exige que le deuxième candidat soit repoussé au-delà de la bande
    des variantes OCR — un concurrent proche n'est pas une identification.
    """
    proche = REPLIQUE.replace("cinq", "six")
    table = _table(
        {"jetons": sorted(jetons(REPLIQUE)), "genre": FEMININ},
        {"jetons": sorted(jetons(proche)), "genre": MASCULIN},
    )
    assert chercher_replique(REPLIQUE, table) is None


def test_jetons_stables_d_une_execution_a_l_autre():
    """crc32, pas hash() : le hachage de Python est salé par processus, une
    table écrite hier doit se relire aujourd'hui. Valeur figée en dur : si
    elle bouge, toutes les tables déjà générées sont mortes — c'est une
    rupture de format, pas un détail d'implémentation."""
    assert jetons("bouftou") == {3328887306}


# --- Cascade ------------------------------------------------------------------


def test_cascade_lexique_prime_puis_accords_puis_table():
    table = _table({"jetons": sorted(jetons(REPLIQUE)), "genre": FEMININ})
    assert decider_genre("Je suis Klako, chasseur.", table)[0] == MASCULIN
    assert decider_genre("Je suis venue te voir.", table)[0] == FEMININ
    assert decider_genre(REPLIQUE, table) == (FEMININ, "table")


def test_cascade_conflit_lexique_accords_s_abstient():
    """Lexique masculin ET accord féminin : personne n'a raison, abstention."""
    texte = "Je suis chasseur. Je suis venue hier."
    genre, source = decider_genre(texte, table={})
    assert genre is None
    assert "conflit" in source


def test_cascade_sans_signal_s_abstient():
    genre, source = decider_genre("Bonjour, belle journée.", table={})
    assert genre is None
    assert source == "abstention"


def test_canal_pour_l_inconnu_est_le_masculin():
    """L'abstention doit sonner exactement comme avant l'ADR-0001."""
    assert canal_pour(None) is Canal.PNJ_MASCULIN
    assert canal_pour(MASCULIN) is Canal.PNJ_MASCULIN
    assert canal_pour(FEMININ) is Canal.PNJ_FEMININ


# --- Intégration Reader -------------------------------------------------------


def test_le_reader_route_une_replique_feminine_vers_le_canal_feminin():
    """Du texte OCRisé au canal : la décision est prise à « _dire », une fois.

    Même mécanique de stabilisation que la production (deux images avant de
    parler) : la voix qui part est celle du canal décidé, pas le défaut.
    """
    reader = lecteur_nu()
    texte = "Je suis la gardienne de ces lieux. Approche donc."
    images(reader, [texte, texte])

    appels = reader.speaker.say.call_args_list
    assert len(appels) == 1
    assert appels[0].args[1] is Canal.PNJ_FEMININ


def test_le_reader_route_l_inconnu_vers_le_canal_masculin():
    reader = lecteur_nu()
    texte = "Belle journée pour pêcher, non ?"
    images(reader, [texte, texte])

    appels = reader.speaker.say.call_args_list
    assert len(appels) == 1
    assert appels[0].args[1] is Canal.PNJ_MASCULIN
