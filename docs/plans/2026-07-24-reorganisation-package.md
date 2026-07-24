# Réorganisation en package — Plan d'implémentation

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Découper le monolithe `quest_reader.py` (1183 lignes) en package `quest_reader/`, à comportement strictement identique.

**Architecture:** Refactor pur — déplacer le code, jamais le changer. Découpage en DAG : `text` et `playback` (feuilles) → `detection` → `engines/` (ABC + 3 moteurs) → `speaker` → `capture` → `reader` → `__main__`. Extraction bas-en-haut, un commit par module, tests verts à chaque étape.

**Tech Stack:** Python 3.14, pytest, OpenCV, pytesseract, PyGObject (Gst), dbus. Venv en `.venv/`.

**Design de référence :** `docs/plans/2026-07-24-reorganisation-package-design.md`

**Commande de test globale :** `.venv/bin/python -m pytest tests/ -q`

## Invariants NON NÉGOCIABLES (vérifier à CHAQUE commit)

1. **Comptes de tests identiques** : la suite affiche toujours **`164 passed, 1 xfailed`**. Jamais un test en moins, jamais le xfail qui passe ou qui erreur.
2. **`git diff` = déplacements + imports uniquement.** Si tu changes une ligne de logique, tu es hors périmètre — arrête et reviens en arrière.
3. **Paresse de torch** : `import torch` et `import transformers` restent DANS `XttsEngine.__init__`, jamais au niveau module. Preuve : le test `faux_xtts` reste vert dans le venv sans torch.
4. **xfail roukerol reste `strict`** : ne touche pas au marqueur.

Si un pas casse un invariant : `git revert` ce pas, ne l'empile pas.

---

## Task 0 : Créer le squelette du package

**Files:**
- Create: `quest_reader/__init__.py`, `quest_reader/_legacy.py` (le monolithe déplacé)

**⚠️ Collision de noms.** `quest_reader.py` (fichier) et `quest_reader/`
(dossier) ne peuvent pas coexister comme modules importables. **Stratégie :**
déplacer le monolithe DANS le package sous le nom `_legacy.py`, créer
`__init__.py` qui ré-exporte tout depuis `._legacy` pour que les tests passent
inchangés, puis vider `_legacy` module par module. À la fin, `_legacy.py` est
supprimé.

`_legacy.py` vit **dans** le package (`quest_reader/_legacy.py`), pas à la
racine : pas de nom top-level qui fuit, robuste à l'exécution depuis n'importe
où.

**Step 1 : Déplacer le monolithe dans le package**

```bash
mkdir quest_reader
git mv quest_reader.py quest_reader/_legacy.py
```

Créer `quest_reader/__init__.py` qui ré-exporte l'API publique utilisée par les
tests. **Ce fichier est écrit UNE SEULE FOIS ici** — on n'y retouche plus
jusqu'à la Task 8. Au fur et à mesure que les symboles quittent `_legacy`,
c'est `_legacy` qui les ré-importe depuis leur nouveau module, donc son espace
de noms les expose toujours et cet `__init__` reste valide sans modification.

```python
"""Package quest_reader — réorganisation en cours depuis _legacy."""

from quest_reader._legacy import (  # noqa: F401
    Playback,
    Reader,
    Speaker,
    clean,
    drop_replies,
    find_dialog,
    keep_word,
    pronounce,
    reads_like_dialogue,
    same_dialog,
    speakable,
    split_narration,
    strip_choices,
    split_sentences,
)
```

> Le `from quest_reader import (...)` des tests continue de fonctionner via ce
> ré-export. La chaîne `__init__ → _legacy → quest_reader.text` (etc.) ne
> boucle pas car `text`/`playback` sont de vraies feuilles : elles n'importent
> jamais de `_legacy` ni du root du package.

**Step 2 : Vérifier la suite inchangée**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3`
Expected: **164 passed, 1 xfailed**.

**Step 3 : Commit**

```bash
git add -A
git commit -m "refactor: amorcer le package quest_reader (ré-export depuis _legacy)"
```

---

## Task 1 : Extraire les helpers de test vers helpers.py

> Fait AVANT tout découpage de test : le split en miroir dupliquerait ces
> helpers autrement.

**Files:**
- Create: `tests/helpers.py`
- Modify: `tests/test_detection.py`

**Step 1 : Repérer les helpers et fixtures partagés**

Run: `grep -nE "^def (load|erase|ecran|images|lecteur_nu|mots_places|texte_de|faux_xtts)|^class FauxProcessus|^(BRAKMAR|TOKAGEKO|THEME_BLEU|CLIQUETIS|ENROLEMENT|KLAKO|ROUKEROL|SAMPLES|IDS|FIXTURES) =" tests/test_detection.py`

**Step 2 : Déplacer vers `tests/helpers.py`**

Créer `tests/helpers.py`. Y déplacer (couper depuis `test_detection.py`) :
`FIXTURES`, les dicts d'échantillons (`BRAKMAR`, `TOKAGEKO`, `THEME_BLEU`,
`SAMPLES`, `IDS`, `CLIQUETIS`, `ENROLEMENT`, `KLAKO`, `ROUKEROL`), et les
fonctions/classe `load`, `erase`, `ecran`, `images`, `lecteur_nu`,
`FauxProcessus`, `mots_places`, `texte_de`, `faux_xtts`.

Ces symboles sont utilisés **par nom** dans les tests (pas via fixtures
pytest) : un module `helpers.py` importé explicitement est plus prévisible
qu'un `conftest.py` (dont la mise sur le `sys.path` dépend de la config
rootdir). En tête de `test_detection.py`, ajouter
`from tests.helpers import (...)` ou `from helpers import (...)` selon ce que le
`sys.path` des tests permet (le fichier insère déjà la racine du dépôt, donc
`from tests.helpers import ...` fonctionne). Vérifier lequel passe.

> `helpers.py` importe ce dont il a besoin de `quest_reader` (ex : `faux_xtts`
> et `lecteur_nu` référencent `Reader`, `Speaker`) — via `from quest_reader
> import Reader, Speaker`. À ce stade tout passe encore par le ré-export
> `_legacy`, donc ces imports marchent.

**Step 3 : Suite verte**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3`
Expected: **164 passed, 1 xfailed**.

**Step 4 : Commit**

```bash
git add -A
git commit -m "test: extraire les helpers partagés vers helpers.py"
```

---

## Task 2 : Extraire `text.py` (feuille)

**Files:**
- Create: `quest_reader/text.py`
- Create: `tests/test_text.py`
- Modify: `_legacy.py`, `quest_reader/__init__.py`, `tests/test_detection.py`

**Fonctions à déplacer** (depuis `_legacy.py`) : `clean`, `strip_choices`,
`fingerprint`, `clearest`, `word_gap`, `same_dialog`, `speakable`,
`split_narration`, `pronounce`, `split_sentences`.
**Constantes associées** : `PRONUNCIATION`, et toute constante utilisée
uniquement par ces fonctions (chercher `SAME_DIALOG`, `NOISE_SLACK`,
`fingerprint`-related). `import re`, `import difflib` vont avec.

**Step 1 : Déplacer le code dans `quest_reader/text.py`**

Couper les fonctions ci-dessus de `_legacy.py`, les coller dans
`quest_reader/text.py` avec leurs imports (`re`, `difflib`) et constantes.

**Step 2 : Ré-exporter et re-câbler `_legacy.py`**

Dans `_legacy.py`, remplacer les définitions retirées par :
`from quest_reader.text import (clean, strip_choices, fingerprint, clearest, word_gap, same_dialog, speakable, split_narration, pronounce, split_sentences)`.
(Le reste de `_legacy` — détection, engines — appelle ces noms ; l'import les
rétablit dans son espace de noms. Et comme `__init__` importe depuis `_legacy`,
l'API publique reste exposée sans toucher `__init__`.)

> `quest_reader/__init__.py` n'est PAS modifié ici — c'est tout l'intérêt du
> hub `_legacy`. On n'y touche qu'à la Task 8.

**Step 3 : Créer `tests/test_text.py` (miroir)**

Déplacer depuis `test_detection.py` vers `test_text.py` les tests qui portent
sur ces fonctions (nettoyage, `same_dialog`, `clearest`, `split_narration`,
`pronounce`, `strip_choices`, ponctuation forte…). Importer depuis
`quest_reader.text` et depuis `tests/helpers.py` pour les fixtures partagées.

> Repérer les tests concernés :
> Run: `grep -nE "def test.*(clean|strip_choices|clearest|same_dialog|narration|pronounce|split_sentences|empreinte|infinitif|ponctuation)" tests/test_detection.py`

**Step 4 : Suite verte, comptes identiques**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3`
Expected: **164 passed, 1 xfailed** (les tests ont changé de fichier, pas de
nombre).

**Step 5 : Commit**

```bash
git add -A
git commit -m "refactor: extraire quest_reader/text.py"
```

---

## Task 3 : Extraire `playback.py` (feuille)

**Files:**
- Create: `quest_reader/playback.py`
- Modify: `_legacy.py`, `quest_reader/__init__.py`, tests concernés

**À déplacer** : classe `Playback`, l'instance globale `playback = Playback()`,
et `play_wave`. `import subprocess`, `import threading` accompagnent si plus
utilisés ailleurs dans `_legacy` (sinon les garder aussi là-bas — les imports
stdlib peuvent être dupliqués sans risque).

**Step 1 : Déplacer dans `quest_reader/playback.py`.**
**Step 2 : Dans `_legacy.py`**, remplacer par
`from quest_reader.playback import Playback, playback, play_wave`.
(Les moteurs et `Speaker`, encore dans `_legacy`, utilisent `playback` et
`play_wave` — l'import les rétablit. `__init__` n'est pas touché : il tire
`Playback` de `_legacy`, qui le ré-exporte.)
**Step 3 : Tests Playback** → `tests/test_playback.py` (les tests
`test_playback_*` et ceux sur `Speaker`/silence qui touchent la lecture ; garder
`Speaker` avec `speaker` plus tard — ici seulement ce qui teste `Playback` seul).

Run pour les repérer: `grep -n "def test_playback\|def test_le_ctrl_c\|Playback(" tests/test_detection.py`

**Step 4 : Suite verte.**
Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3` → **164 passed, 1 xfailed**.
**Step 5 : Commit** `refactor: extraire quest_reader/playback.py`

---

## Task 4 : Extraire `detection.py`

**Files:**
- Create: `quest_reader/detection.py`
- Create: `tests/test_detection_core.py` (ou garder `test_detection.py` pour ça)
- Modify: `_legacy.py`, `quest_reader/__init__.py`

**À déplacer** : `find_bubbles`, `find_dialog`, `reads_like_dialogue`,
`read_words`, `keep_word`, `drop_replies`, `is_reply_block` et TOUTES les
constantes de détection (l.53-121 environ : `MAX_CHANNEL_SPREAD`, `VALUE_MIN`,
`VALUE_MAX`, `BLUE_*`, `OPEN_KERNEL`, `CLOSE_KERNEL`, `MERGED_MIN_HEIGHT`,
`MIN_PUNCTUATION_RATIO`, `MIN_AREA`, `MIN_WIDTH`, `MIN_CHARS`, `MIN_WHITE_RATIO`,
`MAX_WHITE_RATIO`, `MAX_REPLY_GAP`, `MAX_REPLY_OVERLAP`, `ALIGN_TOLERANCE`,
`MARGIN`, `MIN_WORD_CONFIDENCE`, `MAX_NOISE_LENGTH`, `MIN_REPLY_LINE_GAP`,
`LINE_TOLERANCE`, `PLAUSIBLE`). Imports : `cv2`, `numpy as np`, `pytesseract`,
`from PIL import Image`, `re`.

`detection` importe de `text` si besoin (`clean` est utilisé par `find_dialog` :
`from quest_reader.text import clean`).

**Step 1 : Déplacer.** **Step 2 : `_legacy`** ré-importe
`from quest_reader.detection import find_dialog, find_bubbles, reads_like_dialogue, read_words, keep_word, drop_replies, is_reply_block`.
(`__init__` non touché — il tire ces noms de `_legacy`.)
**Step 3 : Tests de détection** — le gros de `test_detection.py` reste ici mais
importe désormais `from quest_reader.detection import ...`. Le xfail roukerol
et les tests de fixtures y restent.

**Step 4 : Suite verte** → **164 passed, 1 xfailed** (⚠️ vérifier explicitement
que le xfail est toujours là et strict).
**Step 5 : Commit** `refactor: extraire quest_reader/detection.py`

---

## Task 5 : Extraire `engines/` (ABC + 3 moteurs)

**Files:**
- Create: `quest_reader/engines/__init__.py`, `piper.py`, `kokoro.py`, `xtts.py`
- Create/Modify: `tests/test_engines.py`
- Modify: `_legacy.py`, `quest_reader/__init__.py`

**Contrat de base.** Dans `engines/__init__.py`, définir la classe abstraite :

```python
import abc


class Engine(abc.ABC):
    @abc.abstractmethod
    def speak(self, text, narration):
        """Synthétise et joue le texte. narration=True pour une didascalie."""
```

Y placer aussi `build_engine` et `check_xtts` (ils choisissent le moteur
concret) et les constantes de voix (`XTTS_VOICE`, `XTTS_NARRATION`, `VOICES`,
`KOKORO_*`).

**Moteurs** : `PiperEngine` → `piper.py`, `KokoroEngine` → `kokoro.py`,
`XttsEngine` + `voice_argument` → `xtts.py`. Chaque classe hérite de `Engine`.
Chacun importe `from quest_reader.playback import play_wave, playback` et
`from quest_reader.text import pronounce, speakable, split_sentences`.

**⚠️ Paresse de torch.** Dans `xtts.py`, `import torch` et
`import transformers.pytorch_utils` restent DANS `XttsEngine.__init__`. Au
niveau module `xtts.py` : seulement `import os`, `contextlib`, `tempfile`,
`concurrent.futures`. AUCUN import torch au sommet.

**Step 1 : Créer l'ABC et déplacer les moteurs.**
**Step 2 : `_legacy`** ré-importe
`from quest_reader.engines import build_engine, check_xtts` +
`from quest_reader.engines.piper import PiperEngine` (etc. si `_legacy` les nomme encore).
(`__init__` non touché.)
**Step 3 : `tests/test_engines.py`** — déplacer les tests moteurs
(`faux_xtts`, `voice_argument`, câblage XTTS/Piper/Kokoro). Importer depuis
`quest_reader.engines.*` et `tests/helpers.py`.

Run pour les repérer: `grep -nE "def test.*(xtts|piper|kokoro|engine|voice|narration|speak)" tests/test_detection.py tests/test_playback.py`

**Step 4 : Suite verte** → **164 passed, 1 xfailed**. Vérifier que
`faux_xtts` passe (preuve de la paresse torch).
**Step 5 : Commit** `refactor: extraire quest_reader/engines/`

---

## Task 6 : Extraire `speaker.py`

**Files:**
- Create: `quest_reader/speaker.py`
- Modify: `_legacy.py`, tests Speaker

**À déplacer** : classe `Speaker`. Imports : `queue`, `threading`, `sys`,
`from quest_reader.playback import playback`,
`from quest_reader.text import split_narration`,
`from quest_reader.engines import build_engine` si `Speaker` le prend en
paramètre (vérifier — il reçoit `build_engine` en argument, donc pas d'import
direct nécessaire).

**Step 1 : Déplacer.** **Step 2 : `_legacy`** ré-importe
`from quest_reader.speaker import Speaker`. (`__init__` non touché.)
**Step 3 : tests Speaker** → `tests/test_speaker.py`.

Run: `grep -n "def test.*[Ss]peaker\|Speaker(" tests/test_detection.py tests/test_playback.py`

**Step 4 : Suite verte** → **164 passed, 1 xfailed**.
**Step 5 : Commit** `refactor: extraire quest_reader/speaker.py`

---

## Task 7 : Extraire `capture.py` et `reader.py`

**Files:**
- Create: `quest_reader/capture.py`, `quest_reader/reader.py`
- Modify: `_legacy.py`, tests Reader

**`capture.py`** : classe `ScreenCast`. Imports :
`import dbus`, `import dbus.mainloop.glib`, et les constantes `TOKEN_FILE`.
**`reader.py`** : classe `Reader`. Imports : `import gi;
gi.require_version("Gst", "1.0"); from gi.repository import Gst, GLib`,
`import numpy as np`, `import time`, et
`from quest_reader.detection import find_dialog, find_bubbles`,
`from quest_reader.text import clean, same_dialog, clearest`,
`from quest_reader.speaker import Speaker`,
`from quest_reader.engines import build_engine`,
`from quest_reader.capture import ScreenCast`.

> `gi.require_version` doit précéder `from gi.repository import Gst`. Garder ces
> deux lignes ensemble au sommet de `reader.py` (et de `capture.py` si elle
> utilise Gst — vérifier ; sinon dbus seul).

**Step 1 : Déplacer ScreenCast puis Reader.**
**Step 2 : `_legacy`** ré-importe les deux. (`__init__` non touché.)
**Step 3 : tests Reader** → `tests/test_reader.py` (les tests `handle`,
coupure, `lecteur_nu`, missing…).

Run: `grep -n "def test.*(handle\|bulle\|coupe\|dictee\|reader\|Reader)\|lecteur_nu(" tests/test_detection.py`

**Step 4 : Suite verte** → **164 passed, 1 xfailed**.
**Step 5 : Commit** `refactor: extraire quest_reader/capture.py et reader.py`

---

## Task 8 : Extraire `__main__.py` et supprimer `_legacy.py`

**Files:**
- Create: `quest_reader/__main__.py`
- Delete: `quest_reader/_legacy.py`
- Modify: `quest_reader/__init__.py`

À ce stade, `quest_reader/_legacy.py` ne doit plus contenir que `main`,
`check_xtts` (si pas déjà dans engines), `build_engine` (idem), et des
ré-exports. Vérifier :

Run: `grep -nE "^def |^class |^[A-Z_]+ =" quest_reader/_legacy.py`

**Step 1 : Déplacer `main` (+ `argparse`, `signal`) dans
`quest_reader/__main__.py`.** Ajuster ses imports pour tirer de
`quest_reader.reader`, `quest_reader.engines`, etc.

**Step 2 : Vérifier que `quest_reader/_legacy.py` est vide de définitions
propres** (ne contient plus que des imports). Le supprimer :

```bash
git rm quest_reader/_legacy.py
```

Réécrire `quest_reader/__init__.py` : c'est ICI, et seulement ici, qu'on
repointe les 14 ré-exports vers les vrais modules
(`from quest_reader.text import clean, …`,
`from quest_reader.detection import find_dialog, …`,
`from quest_reader.playback import Playback`,
`from quest_reader.speaker import Speaker`,
`from quest_reader.reader import Reader`), plus aucune référence à `_legacy`.

**Step 3 : Vérifier le point d'entrée**

Run: `.venv/bin/python -m quest_reader --help 2>&1 | head -20`
Expected: l'aide argparse s'affiche (les arguments `--fps`, `--engine`, etc.),
aucune ImportError.

> Vérifie aussi qu'aucun import résiduel ne référence `_legacy` :
> Run: `grep -rn "_legacy" quest_reader/ tests/`
> Expected: aucune sortie.

**Step 4 : Suite verte finale + diff propre**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3`
Expected: **164 passed, 1 xfailed**.

Run: `grep -rn "import torch" quest_reader/`
Expected: uniquement dans `xtts.py`, à l'intérieur de `__init__` (pas au niveau
module).

**Step 5 : Commit**

```bash
git add -A
git commit -m "refactor: point d'entrée __main__ et suppression de _legacy"
```

---

## Task 9 : Re-cibler le plan de réactivité

**Files:**
- Modify: `docs/plans/2026-07-24-reactivite-coupure-bascule.md`

Le plan de réactivité référence `quest_reader.py:539-575`, `Speaker`, les
moteurs, et greppe `playback.stopped` dans `quest_reader.py`. Ces chemins sont
désormais périmés.

**Step 1 : Mettre à jour les références de fichier** dans ce plan :
- `Playback` → `quest_reader/playback.py`
- `Speaker` → `quest_reader/speaker.py`
- moteurs → `quest_reader/engines/{piper,kokoro,xtts}.py`
- `Reader` → `quest_reader/reader.py`
- les `grep quest_reader.py` → `grep -rn quest_reader/`

Remplacer les numéros de ligne absolus par des références symboliques (nom de
fonction/classe) quand c'est possible — plus robustes au déplacement.

**Step 2 : Commit**

```bash
git add docs/plans/2026-07-24-reactivite-coupure-bascule.md
git commit -m "docs: re-cibler le plan de réactivité sur le package"
```

---

## Vérification finale

- `.venv/bin/python -m pytest tests/ -q` → **164 passed, 1 xfailed**
- `.venv/bin/python -m quest_reader --help` → aide affichée, aucune erreur
- `grep -rn "import torch" quest_reader/` → uniquement dans `xtts.py`, dans `__init__`
- `grep -rn "_legacy" .` → aucune sortie
- Structure : `quest_reader/{__init__,__main__,text,playback,detection,speaker,capture,reader}.py` + `quest_reader/engines/{__init__,piper,kokoro,xtts}.py`
- `git log --oneline` montre un commit par module, chacun avec suite verte

## Hors périmètre (rappel)

- Bug de segmentation roukerol (chantier suivant).
- Seuils relatifs à la résolution.
- Toute modification de comportement ou injection de dépendances.
