#!/usr/bin/env python3
"""Génère la table locale « empreintes de répliques → genre » (ADR-0001).

À lancer À LA MAIN, hors ligne du point de vue du jeu : jamais en CI, jamais
au runtime — le programme en jeu ne fait AUCUNE requête réseau, il ne lit que
le fichier produit ici. Source canonique unique : l'API communautaire DofusDB
(vérifiée le 2026-08-03 : /npcs porte nom, champ « gender » et paires d'ids
de dialogue ; /npc-messages résout ces ids en texte français).

Ce qui sort — et ce qui ne sort PAS :
- des JETONS HACHÉS (crc32, via keraconte.genre.jetons : LA même fonction
  que le runtime, c'est le contrat) et des noms associés à un genre, avec la
  provenance (source, date, nombre de PNJ). Les textes du jeu eux-mêmes ne
  sont PAS écrits : la table est un index de faits, pas une copie de contenu.
- une réplique partagée par des PNJ des deux genres est marquée « ambigu » :
  le runtime s'abstient dessus, par construction.

Tenue : cadence polie (pause entre requêtes, User-Agent identifiant le
projet), reprise simple sur erreur. La table se périme à chaque mise à jour
du jeu : la régénérer alors, la date affichée dans le fichier fait foi.

Usage :
    python outils/generer_table_genre.py [--sortie CHEMIN] [--limite N]

Par défaut la sortie va là où le runtime la cherche
(keraconte.genre._chemin_table) ; « --limite » borne le nombre de PNJ pour
un essai rapide.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from keraconte.genre import FEMININ, MASCULIN, jetons, _chemin_table  # noqa: E402

API = "https://api.dofusdb.fr"
PAGE = 50  # taille de page Feathers ($limit)
PAUSE = 0.25  # politesse : quatre requêtes par seconde au plus
ENTETES = {"User-Agent": "keraconte/generer-table-genre (outil hors ligne)"}

# Encodage du champ « gender » relevé sur l'API (Hazel Ementaire : 1 ;
# Uk'Not'Allag' : 0). Toute autre valeur vaut abstention : le PNJ n'entre
# pas dans la table plutôt que d'y entrer faux.
GENRES = {0: MASCULIN, 1: FEMININ}


def _requete(chemin, parametres):
    url = f"{API}{chemin}?{urllib.parse.urlencode(parametres, doseq=True)}"
    demande = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(demande, timeout=30) as reponse:
        return json.load(reponse)
    # (urllib lève sur HTTP != 2xx ; l'appelant décide de retenter ou non.)


def _pages(chemin, parametres):
    """Itère les enregistrements d'un service Feathers, page par page."""
    saut = 0
    while True:
        page = dict(parametres)
        page.update({"$limit": PAGE, "$skip": saut})
        temps = time.monotonic()
        try:
            resultat = _requete(chemin, page)
        except OSError as erreur:
            # Reprise simple : une page ratée se retente une fois, puis se dit.
            print(f"page {saut} : {erreur}, nouvelle tentative", file=sys.stderr)
            time.sleep(2)
            resultat = _requete(chemin, page)
        donnees = resultat.get("data") or []
        yield from donnees
        saut += len(donnees)
        if not donnees or saut >= int(resultat.get("total") or 0):
            return
        time.sleep(max(0.0, PAUSE - (time.monotonic() - temps)))


def _ids_messages(npc):
    """Aplati les paires d'ids de dialogMessages d'un PNJ.

    Les paires observées ([30730, 750413]) mêlent deux espaces d'ids ; on
    collecte LES DEUX membres — la résolution par lot (champ « id ») ne
    retiendra que ceux que /npc-messages connaît. Doublons filtrés à la fin.
    """
    ids = set()
    for paire in npc.get("dialogMessages") or []:
        for membre in paire if isinstance(paire, list) else [paire]:
            if isinstance(membre, int):
                ids.add(membre)
    return ids


def _textes_messages(ids):
    """Résout des ids de message en textes français, par lots.

    Interroge /npc-messages avec « id[$in][]=… » ; les ids inconnus (l'autre
    membre de la paire) tombent simplement dans le vide. Renvoie {id: texte}.
    """
    textes = {}
    liste = sorted(ids)
    for debut in range(0, len(liste), PAGE):
        lot = liste[debut : debut + PAGE]
        parametres = [("id[$in][]", identifiant) for identifiant in lot]
        parametres += [("$limit", PAGE)]
        temps = time.monotonic()
        try:
            resultat = _requete("/npc-messages", parametres)
        except OSError as erreur:
            print(f"messages {lot[0]}… : {erreur}, lot sauté", file=sys.stderr)
            continue
        for enregistrement in resultat.get("data") or []:
            texte = (enregistrement.get("message") or {}).get("fr")
            identifiant = enregistrement.get("id")
            if texte and identifiant is not None:
                textes[identifiant] = texte
        time.sleep(max(0.0, PAUSE - (time.monotonic() - temps)))
    return textes


def _neutraliser(texte):
    """Efface les placeholders #N que le jeu remplit à l'affichage."""
    import re

    return re.sub(r"#\d+", " ", texte)


def generer(limite=None):
    """Construit la table : entrées de répliques + noms, genres, ambiguïtés."""
    empreintes = {}  # frozenset(jetons) -> ensemble des genres vus
    noms = {}  # nom minuscule -> ensemble des genres vus
    pnj_vus = 0
    ids_par_genre = []  # (ids de messages, genre) par PNJ, résolus après

    for npc in _pages("/npcs", {}):
        genre = GENRES.get(npc.get("gender"))
        if genre is None:
            continue
        pnj_vus += 1
        nom = ((npc.get("name") or {}).get("fr") or "").strip().lower()
        if nom:
            noms.setdefault(nom, set()).add(genre)
        ids = _ids_messages(npc)
        if ids:
            ids_par_genre.append((ids, genre))
        if limite and pnj_vus >= limite:
            break
        if pnj_vus % 200 == 0:
            print(f"{pnj_vus} PNJ parcourus…", file=sys.stderr)

    tous_ids = set().union(*(ids for ids, _ in ids_par_genre)) if ids_par_genre else set()
    print(f"{pnj_vus} PNJ genrés, {len(tous_ids)} ids de message à résoudre",
          file=sys.stderr)
    textes = _textes_messages(tous_ids)
    print(f"{len(textes)} textes résolus", file=sys.stderr)

    for ids, genre in ids_par_genre:
        for identifiant in ids:
            texte = textes.get(identifiant)
            if not texte:
                continue
            empreinte = frozenset(jetons(_neutraliser(texte)))
            if empreinte:
                empreintes.setdefault(empreinte, set()).add(genre)

    entrees = [
        {
            "jetons": sorted(empreinte),
            "genre": genres.pop() if len(genres) == 1 else "ambigu",
        }
        for empreinte, genres in empreintes.items()
    ]
    table_noms = {
        nom: genres.pop() for nom, genres in noms.items() if len(genres) == 1
    }
    return {
        "version": 1,
        "source": API,
        "date": datetime.date.today().isoformat(),
        "pnj": pnj_vus,
        "entrees": entrees,
        "noms": table_noms,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sortie",
        default=_chemin_table(),
        help="fichier JSON à écrire (défaut : là où le runtime le cherche)",
    )
    parser.add_argument(
        "--limite", type=int, help="borner le nombre de PNJ (essai rapide)"
    )
    args = parser.parse_args()

    table = generer(args.limite)
    os.makedirs(os.path.dirname(args.sortie) or ".", exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fichier:
        json.dump(table, fichier, ensure_ascii=False)
    ambigues = sum(1 for e in table["entrees"] if e["genre"] == "ambigu")
    print(
        f"Table écrite : {args.sortie} — {table['pnj']} PNJ, "
        f"{len(table['entrees'])} répliques ({ambigues} ambiguës), "
        f"{len(table['noms'])} noms."
    )


if __name__ == "__main__":
    main()
