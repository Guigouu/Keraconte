# Réorganisation de quest_reader.py en package

## Problème

Tout le programme vit dans un seul fichier `quest_reader.py` (1183 lignes) :
détection, nettoyage de texte, trois moteurs vocaux, orchestration, capture
d'écran, boucle principale. Conséquence concrète mesurée : impossible de mener
plusieurs chantiers en parallèle (bug de segmentation, seuils relatifs,
réactivité) sans que les agents s'écrasent, car ils touchent tous le même
fichier. La réorganisation débloque le reste.

## Décisions cadrées avec l'utilisateur

- **Package `quest_reader/`** — structure Python idiomatique, point d'entrée
  `python -m quest_reader`.
- **Sous-package `engines/` avec classe de base** — le contrat `speak(text,
  narration)`, aujourd'hui implicite, devient explicite (ABC). Ajouter un
  moteur = un fichier.
- **Refactor pur, comportement identique** — on déplace le code sans rien
  changer. Les vrais fixes viennent après, sur une base saine.
- **Tests découpés en miroir** des nouveaux modules.

## Arborescence cible

```
quest_reader/
├── __init__.py
├── __main__.py        # main(), point d'entrée
├── text.py            # clean, strip_choices, fingerprint, clearest,
│                      #   same_dialog, word_gap, speakable, split_narration,
│                      #   pronounce, split_sentences  (feuille)
├── playback.py        # Playback + instance globale playback + play_wave (feuille)
├── detection.py       # find_bubbles, find_dialog, reads_like_dialogue,
│                      #   read_words, keep_word, drop_replies, is_reply_block
│                      #   + constantes de détection  → dépend de text
├── engines/
│   ├── __init__.py    # Engine (ABC, contrat speak) + build_engine + check_xtts
│   ├── piper.py
│   ├── kokoro.py
│   └── xtts.py        # import torch reste DANS __init__ (paresseux)
├── speaker.py         # Speaker  → engines + text + playback
├── capture.py         # ScreenCast
└── reader.py          # Reader  → tout le reste
```

**Graphe de dépendances (DAG, aucun cycle) :** `text` et `playback` sont des
feuilles ; `detection→text` ; `engines→text,playback` ;
`speaker→engines,text,playback` ; `reader→tout`. Rien ne remonte.

**`playback` reste une instance globale de module** (choix « comportement
identique ») — on choisit seulement son domicile (`playback.py`), on ne la
transforme pas en injection de dépendances.

## Invariants du refactor pur

1. **Mêmes comptes de tests** : `pytest tests/ -q` reste **164 passed, 1
   xfailed**. Le `git diff` ne contient que des déplacements + lignes d'import.
2. **xfail roukerol reste `strict`** : s'il devient une *erreur* (import cassé)
   ou un *pass*, c'est une régression, pas une victoire.
3. **Paresse de torch préservée** : `import torch` reste dans
   `XttsEngine.__init__`, jamais au niveau module. Le test `faux_xtts` (venv
   sans torch) est la preuve : s'il reste vert, la paresse tient.

## Ordre d'exécution — bas-en-haut, un commit par module

**Étape préalable côté tests :** extraire les helpers partagés vers
`tests/conftest.py` (`load`, `erase`, `ecran`, `images`, `lecteur_nu`,
`FauxProcessus`, `mots_places`, `texte_de`, `faux_xtts`, et les dicts
d'échantillons BRAKMAR…ROUKEROL). Sans ça, le découpage en miroir dupliquerait
ce socle — c'est là le vrai risque du split.

Puis, module par module (déplacer le code, mettre à jour ses imports **et** ceux
du test miroir, suite verte, commit) :

`text`, `playback` → `detection` → `engines` (base, puis les trois moteurs) →
`speaker` → `capture` → `reader` → `__main__`.

Un pas cassé = un seul `git revert`.

## Note de suivi

Le plan de réactivité déjà committé
(`docs/plans/2026-07-24-reactivite-coupure-bascule.md`) référence
`quest_reader.py:539-575`, le bloc `Speaker`, les moteurs, et greppe
`playback.stopped`. Après ce refactor, tous ces chemins/lignes seront périmés :
une tâche du plan re-ciblera ce plan sur les nouveaux modules.

## Hors périmètre

- Corriger le bug de segmentation roukerol (chantier suivant, après base saine).
- Rendre les seuils relatifs à la résolution.
- Toute injection de dépendances ou découplage « tant qu'on y est ».
