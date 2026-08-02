"""Genre du PNJ pour le choix de la voix (ADR-0001).

Quasi-feuille du DAG (n'importe que « text », feuille elle-même) : le Reader
décide ici, UNE fois par réplique, le canal de voix que le Speaker fera
suivre aux moteurs. L'abstention est le comportement par défaut : sans signal
sûr, le canal reste PNJ_MASCULIN et le programme sonne exactement comme avant
— une mauvaise voix est pire que pas d'adaptation.

Trois signaux implémentés, en cascade. Le signal 4 de l'ADR (OCR du
cartouche) reste HORS code tant que sa re-mesure sur le registre n'a pas
battu les ratios de l'abandon (0,11–0,24) :

1. lexique genré — auto-désignations dont le français porte le genre
   (« Je suis Klako, chasseur ») ;
2. accords en première personne (« je suis venue ») ;
3. empreinte de la réplique cherchée dans une table embarquée, générée hors
   ligne par « outils/generer_table_genre.py ». Sans table : inerte, et le
   runtime reste strictement hors ligne — la table est un fichier local.
"""

import enum
import json
import os
import re
import sys
import zlib

from keraconte.text import vocabulaire


class Canal(enum.Enum):
    """Canal de voix d'un segment : remplace le booléen « narration ».

    PNJ_MASCULIN est aussi le canal de l'inconnu : c'est la voix
    d'aujourd'hui, et l'abstention doit sonner à l'identique.
    """

    PNJ_MASCULIN = enum.auto()
    PNJ_FEMININ = enum.auto()
    NARRATION = enum.auto()


MASCULIN = "masculin"
FEMININ = "feminin"


def canal_pour(genre):
    """Traduit une décision de genre en canal de voix (inconnu → masculin)."""
    return Canal.PNJ_FEMININ if genre == FEMININ else Canal.PNJ_MASCULIN


# --- Signaux 1 et 2 : lexiques d'auto-désignation ---------------------------
# Un mot ne vote que s'il suit un « je suis » : un PNJ qui PARLE d'un chasseur
# ne dit rien de lui-même, et « tu es venue » accorde le joueur, pas le PNJ —
# le périmètre du vote est le segment d'auto-désignation, jamais la réplique
# entière. Paires finies, versionnées, auditables ; les épicènes
# (« forgemage », « alchimiste », « mercenaire », « capitaine ») n'y figurent
# pas : ils ne votent pas, par construction.
METIERS = [
    ("chasseur", "chasseuse"),
    ("gardien", "gardienne"),
    ("marchand", "marchande"),
    ("vendeur", "vendeuse"),
    ("aventurier", "aventurière"),
    ("guerrier", "guerrière"),
    ("magicien", "magicienne"),
    ("prêtre", "prêtresse"),
    ("roi", "reine"),
    ("prince", "princesse"),
    ("sorcier", "sorcière"),
    ("forgeron", "forgeronne"),
    ("éleveur", "éleveuse"),
    ("explorateur", "exploratrice"),
    ("directeur", "directrice"),
    ("patron", "patronne"),
    ("tavernier", "tavernière"),
    ("boucher", "bouchère"),
    ("boulanger", "boulangère"),
    ("pêcheur", "pêcheuse"),
    ("bûcheron", "bûcheronne"),
    ("paysan", "paysanne"),
    ("danseur", "danseuse"),
    ("chanteur", "chanteuse"),
    ("voleur", "voleuse"),
    ("serviteur", "servante"),
    ("seigneur", "dame"),
]

# Participes et adjectifs dont le féminin s'écrit — donc se lit à l'OCR.
ACCORDS = [
    ("venu", "venue"),
    ("arrivé", "arrivée"),
    ("allé", "allée"),
    ("né", "née"),
    ("prêt", "prête"),
    ("content", "contente"),
    ("désolé", "désolée"),
    ("ravi", "ravie"),
    ("honoré", "honorée"),
    ("sûr", "sûre"),
    ("certain", "certaine"),
    ("heureux", "heureuse"),
    ("curieux", "curieuse"),
    ("fier", "fière"),
    ("seul", "seule"),
    ("enchanté", "enchantée"),
    ("épuisé", "épuisée"),
    ("perdu", "perdue"),
    ("chargé", "chargée"),
]

_METIERS_M = {masculin for masculin, _ in METIERS}
_METIERS_F = {feminin for _, feminin in METIERS}
_ACCORDS_M = {masculin for masculin, _ in ACCORDS}
_ACCORDS_F = {feminin for _, feminin in ACCORDS}

# Segment d'auto-désignation : de « je suis » (ou « je me suis ») à la fin de
# la phrase. C'est le périmètre de vote des deux lexiques.
_AUTO_DESIGNATION = re.compile(r"\bje (?:suis|me suis)\b([^.!?…]*)", re.IGNORECASE)


def _mots(segment):
    return set(re.findall(r"[\w’'-]+", segment.lower()))


def _vote(texte, masculins, feminins):
    """Vote d'un lexique sur les segments d'auto-désignation, ou None.

    Deux genres votés — dans un même segment ou entre segments — c'est une
    contradiction : on s'abstient plutôt que de trancher.
    """
    votes = set()
    for segment in _AUTO_DESIGNATION.findall(texte):
        mots = _mots(segment)
        if mots & masculins:
            votes.add(MASCULIN)
        if mots & feminins:
            votes.add(FEMININ)
    return votes.pop() if len(votes) == 1 else None


def genre_par_lexique(texte):
    """Signal 1 — métier ou titre en auto-désignation, ou None."""
    return _vote(texte, _METIERS_M, _METIERS_F)


def genre_par_accords(texte):
    """Signal 2 — accord en première personne (« je suis venue »), ou None."""
    return _vote(texte, _ACCORDS_M, _ACCORDS_F)


# --- Signal 3 : table par empreinte de réplique -----------------------------

# Seuils adossés aux mesures de « text.py » : deux lectures OCR d'un même
# texte s'écartent de 0,00 à 0,31, deux textes distincts de 1,86 à 4,11.
# L'acceptation reprend SAME_WORDS_GAP (0,6, même bande vide) ; la marge
# exige que le deuxième candidat soit repoussé au-delà de la bande des
# variantes — un concurrent à moins d'un point n'est pas départagé, on
# s'abstient.
SEUIL_TABLE = 0.6
MARGE_TABLE = 1.0

# Nombre de candidats réellement scorés, pris par jetons partagés décroissants.
# Les jetons fréquents (« bonjour ») ramènent beaucoup d'entrées ; le vrai
# match partage forcément le plus de jetons, donc il est dans cette tête de
# liste — on ne score pas la queue.
MAX_CANDIDATS = 50


def jetons(texte):
    """Empreinte d'une réplique : vocabulaire haché, non réversible.

    « zlib.crc32 » et non « hash() » : le hachage de Python est salé par
    processus — une table écrite hier ne se relirait pas aujourd'hui. La même
    fonction sert au script de génération : c'est le contrat build/runtime.
    """
    return {zlib.crc32(mot.encode("utf-8")) for mot in vocabulaire(texte)}


def _ecart(gauche, droite):
    """Écart de vocabulaire entre deux ensembles de jetons (cf. word_gap)."""
    if not gauche or not droite:
        return 0.0 if gauche == droite else float("inf")
    return len(gauche ^ droite) / min(len(gauche), len(droite))


def chercher_replique(texte, table):
    """Signal 3 — genre porté par la réplique dans la table, ou None.

    Index inversé jeton → entrées, construit une fois et posé sur l'objet
    table. Une entrée « ambigu » (réplique partagée par des PNJ des deux
    genres) s'abstient par construction — c'est la table qui le sait, pas le
    runtime.
    """
    entrees = table.get("entrees") or []
    if not entrees:
        return None
    index = table.get("_index")
    if index is None:
        index = {}
        for rang, entree in enumerate(entrees):
            for jeton in entree["jetons"]:
                index.setdefault(jeton, []).append(rang)
        table["_index"] = index

    lus = jetons(texte)
    if not lus:
        return None
    partages = {}
    for jeton in lus:
        for rang in index.get(jeton, ()):
            partages[rang] = partages.get(rang, 0) + 1
    if not partages:
        return None
    candidats = sorted(partages, key=partages.get, reverse=True)[:MAX_CANDIDATS]
    scores = sorted(
        (_ecart(lus, set(entrees[rang]["jetons"])), rang) for rang in candidats
    )
    meilleur, rang = scores[0]
    if meilleur > SEUIL_TABLE:
        return None
    if len(scores) > 1 and scores[1][0] - meilleur < MARGE_TABLE:
        return None
    genre = entrees[rang].get("genre")
    return genre if genre in (MASCULIN, FEMININ) else None


# Sentinelle : la table ne se cherche sur le disque qu'une fois, absente
# comprise — le chemin ne change pas en cours d'exécution.
_NON_CHARGEE = object()
_TABLE = _NON_CHARGEE


def _chemin_table():
    """Où trouver la table, du plus explicite au plus standard.

    « QR_TABLE_GENRE » (échappatoire, comme QR_TESSERACT), puis le bundle
    figé (« sys._MEIPASS », posé par la spec le jour où la table embarque),
    puis l'emplacement utilisateur — celui où « generer_table_genre.py »
    écrit par défaut.
    """
    force = os.environ.get("QR_TABLE_GENRE")
    if force:
        return force
    racine_figee = getattr(sys, "_MEIPASS", None)
    if racine_figee:
        candidat = os.path.join(racine_figee, "table-genre.json")
        if os.path.isfile(candidat):
            return candidat
    import platformdirs

    return os.path.join(
        platformdirs.user_data_dir(appname=False), "keraconte", "table-genre.json"
    )


def charger_table():
    """Charge la table locale une seule fois ; None si absente ou illisible.

    Une table illisible se signale (une fois) mais ne casse rien : le
    programme retombe sur les signaux lexicaux — l'abstention, pas la panne.
    """
    global _TABLE
    if _TABLE is not _NON_CHARGEE:
        return _TABLE
    chemin = _chemin_table()
    try:
        with open(chemin, encoding="utf-8") as fichier:
            _TABLE = json.load(fichier)
    except FileNotFoundError:
        _TABLE = None
    except (OSError, ValueError) as erreur:
        print(f"table de genre illisible ({chemin}) : {erreur}", file=sys.stderr)
        _TABLE = None
    return _TABLE


def decider_genre(texte, table=None):
    """Cascade ADR-0001 : renvoie (genre ou None, source pour la trace).

    Les signaux lexicaux qui se CONTREDISENT valent abstention — même
    discipline que partout : une erreur se corrige en s'abstenant. « table »
    est injectable pour les tests ; laissé à None, la table locale est
    chargée (une fois) si elle existe.
    """
    lexique = genre_par_lexique(texte)
    accords = genre_par_accords(texte)
    if lexique and accords and lexique != accords:
        return None, "conflit lexique/accords"
    if lexique:
        return lexique, "lexique"
    if accords:
        return accords, "accords"
    if table is None:
        table = charger_table()
    if table:
        trouve = chercher_replique(texte, table)
        if trouve:
            return trouve, "table"
    return None, "abstention"
