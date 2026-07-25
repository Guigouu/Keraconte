# Overlay de contrôle de la lecture — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** ajouter une petite fenêtre flottante toujours au-dessus du jeu, avec trois boutons — pause (‖), stop (■), reprise (▶) — pour piloter la voix à la main.

**Architecture :** un objet `PlayerState` (à trois états `ACTIF` / `EN_PAUSE` / `ARRÊTÉ`) sert de point de découplage unique. L'overlay Qt **écrit** cet état ; le `Reader` et le lecteur audio le **lisent**. La lecture audio, réécrite pour lire le WAV **par tranches**, se fige en pause et s'abandonne au changement de génération. Les boucles d'événements sont **isolées** dans des threads : Qt sur le thread principal, la capture GLib dans un thread dédié, la synthèse dans son thread `Speaker` existant.

**Tech Stack :** Python 3.14, PySide6 (Qt, always-on-top), sounddevice (PortAudio, lecture audio pausable), stdlib `wave` + numpy (lecture du WAV), pytest.

Le design validé est dans `docs/plans/2026-07-25-overlay-controles-lecture-design.md`. Ce plan le met en œuvre.

## Global Constraints

- **Aucun cas en dur, aucun seuil en pixels absolu.** Contrainte de tout le projet ; ici elle vaut surtout pour l'overlay (tolérances relatives si besoin) — voir `[[quest-reader-seuils-pixels-absolus]]`.
- **Une seule dépendance audio nouvelle : `sounddevice`.** Pour lire le WAV, utiliser stdlib `wave` + numpy (déjà présents), **pas** `soundfile`.
- **Imports lourds/fragiles tardifs.** `import sounddevice` **dans une fonction/méthode**, jamais au niveau module : `import sounddevice` lève `OSError` à l'import quand PortAudio est absent, ce qui casserait toute la suite de tests et le mode `--test`. Même idiome que `xtts.py:44` (torch importé dans `__init__`). `import PySide6` de même dans `overlay.py` et `__main__.py`.
- **Le compteur de génération est conservé tel quel.** La pause est une notion **ajoutée par-dessus**, elle ne remplace pas le mécanisme de coupure/bascule (déjà validé en jeu).
- **Discipline de verrou dans `play()` : la boucle de tranches tourne SANS tenir `Playback.lock`.** `bump()` prend ce même verrou pour couper ; si la boucle le retenait, stop/bascule cesserait de fonctionner. L'attente de pause passe par une primitive de `PlayerState` (Condition/Event), jamais par `Playback.lock`.
- **Périmètre : Linux d'abord.** Le lecteur audio est écrit multiplateforme ; la capture (PipeWire) et le packaging Windows/Mac sont hors périmètre.
- **Langue : tout en français** (code, commentaires, tests, messages), avec accents corrects.

---

## Structure des fichiers

```
quest_reader/
├── state.py       # CRÉÉ — PlayerState (ACTIF / EN_PAUSE / ARRÊTÉ) + attente de pause. Feuille : aucun import du package.
├── playback.py    # RÉÉCRIT — Playback.play lit par tranches via sounddevice ; consulte génération + pause. Dépend de state.
├── overlay.py     # CRÉÉ — fenêtre Qt sans bordure, always-on-top, 3 boutons → écrivent dans state. Dépend de state.
├── reader.py      # MODIFIÉ — consulte state (ignore les images si ARRÊTÉ) ; run() scindé pour tourner hors du thread principal. Dépend de state.
├── speaker.py     # MODIFIÉ — say() force EN_PAUSE → ACTIF (un nouveau dialogue lève la pause).
├── __init__.py    # MODIFIÉ — ré-exporte PlayerState.
└── __main__.py    # MODIFIÉ — démarre Qt (principal) + Reader (thread) ; SIGINT et arrêt propre.
```

`state` est une feuille. `playback`, `overlay`, `reader` dépendent de `state`. Aucun cycle.

---

## Task 1 : `PlayerState` — l'état partagé

**Files:**
- Create: `quest_reader/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: rien (feuille).
- Produces :
  - `class Etat` (enum) avec `ACTIF`, `EN_PAUSE`, `ARRETE`.
  - `class PlayerState` :
    - `etat` → `Etat` courant (lecture atomique sous lock).
    - `pause()` : `ACTIF` → `EN_PAUSE`. Sans effet si `ARRETE`.
    - `stop()` : n'importe quel état → `ARRETE`.
    - `reprendre()` : `EN_PAUSE` → `ACTIF` **et** `ARRETE` → `ACTIF` (le bouton ▶ réarme dans les deux cas).
    - `reactiver()` : force `EN_PAUSE` → `ACTIF` **uniquement** (utilisé par `Speaker.say` : un nouveau dialogue lève la pause, mais ne doit pas réanimer un lecteur explicitement stoppé). Sans effet si `ARRETE`.
    - `en_pause` → `bool` : vrai ssi `EN_PAUSE`.
    - `arrete` → `bool` : vrai ssi `ARRETE`.
    - `attendre_reprise(timeout)` : bloque tant que `EN_PAUSE`, revient dès que l'état change (réveil via `threading.Condition`). Renvoie sans rien faire si pas en pause. `timeout` borne l'attente pour rester réactif au changement de génération.

- [ ] **Step 1 : Écrire les tests des transitions**

```python
"""Tests de l'état de lecture partagé (quest_reader.state)."""

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.state import Etat, PlayerState  # noqa: E402


def test_depart_actif():
    assert PlayerState().etat is Etat.ACTIF


def test_pause_puis_reprise():
    state = PlayerState()
    state.pause()
    assert state.etat is Etat.EN_PAUSE
    assert state.en_pause
    state.reprendre()
    assert state.etat is Etat.ACTIF
    assert not state.en_pause


def test_stop_puis_reprise_reactive():
    """▶ réarme un lecteur arrêté (ARRETE → ACTIF)."""
    state = PlayerState()
    state.stop()
    assert state.arrete
    state.reprendre()
    assert state.etat is Etat.ACTIF


def test_reactiver_leve_la_pause_mais_pas_le_stop():
    """Un nouveau dialogue lève la pause, mais ne ressuscite pas un stop.

    « reactiver » sert à « Speaker.say » : une bascule vers un nouveau
    dialogue doit défiger la voix. Mais si l'utilisateur a stoppé le lecteur,
    aucun dialogue ne doit le relancer — seul ▶ le fait.
    """
    state = PlayerState()
    state.pause()
    state.reactiver()
    assert state.etat is Etat.ACTIF

    state.stop()
    state.reactiver()
    assert state.arrete  # inchangé


def test_pause_sans_effet_si_arrete():
    state = PlayerState()
    state.stop()
    state.pause()
    assert state.arrete


def test_attendre_reprise_debloque_a_la_reprise():
    """L'attente de pause revient dès qu'un autre fil reprend."""
    state = PlayerState()
    state.pause()
    reveille = threading.Event()

    def attendre():
        state.attendre_reprise(timeout=1.0)
        reveille.set()

    fil = threading.Thread(target=attendre)
    fil.start()
    assert not reveille.wait(timeout=0.1)  # bloqué tant qu'en pause
    state.reprendre()
    assert reveille.wait(timeout=1.0)      # débloqué
    fil.join()


def test_attendre_reprise_ne_bloque_pas_si_actif():
    state = PlayerState()
    state.attendre_reprise(timeout=1.0)  # revient tout de suite
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `.venv/bin/pytest tests/test_state.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'quest_reader.state'`

- [ ] **Step 3 : Écrire `quest_reader/state.py`**

```python
"""État de lecture partagé entre l'overlay, le Reader et le lecteur audio.

Feuille du DAG : aucun import du package. L'overlay ÉCRIT cet état ; le
« Reader » et « playback » le LISENT. C'est le seul point de découplage entre
l'interface, la capture et l'audio — les boutons ne touchent jamais
directement ni la capture ni le son.
"""

import enum
import threading


class Etat(enum.Enum):
    ACTIF = enum.auto()      # lecture normale
    EN_PAUSE = enum.auto()   # voix figée au milieu de la réplique
    ARRETE = enum.auto()     # analyse débrayée, plus rien n'est lu


class PlayerState:
    """Porte l'état de lecture, protégé par un « Condition ».

    Le « Condition » (plutôt qu'un simple lock) sert l'attente de pause :
    « attendre_reprise » dort dessus, et chaque transition le notifie. La
    pause du lecteur audio ne consomme donc pas de CPU en attente active, et
    reprend sans latence.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._etat = Etat.ACTIF

    @property
    def etat(self):
        with self._condition:
            return self._etat

    @property
    def en_pause(self):
        with self._condition:
            return self._etat is Etat.EN_PAUSE

    @property
    def arrete(self):
        with self._condition:
            return self._etat is Etat.ARRETE

    def _transition(self, cible):
        with self._condition:
            self._etat = cible
            self._condition.notify_all()

    def pause(self):
        """‖ : fige la voix. Sans effet si le lecteur est arrêté."""
        with self._condition:
            if self._etat is Etat.ACTIF:
                self._etat = Etat.EN_PAUSE
                self._condition.notify_all()

    def stop(self):
        """■ : débraye l'analyse et coupe la voix."""
        self._transition(Etat.ARRETE)

    def reprendre(self):
        """▶ : réarme depuis une pause OU depuis un arrêt."""
        self._transition(Etat.ACTIF)

    def reactiver(self):
        """Lève la pause SANS ressusciter un arrêt.

        Appelé par « Speaker.say » : une bascule vers un nouveau dialogue
        défige la voix. Mais un lecteur explicitement stoppé ne doit repartir
        que sur ▶ — jamais sur l'apparition d'un dialogue.
        """
        with self._condition:
            if self._etat is Etat.EN_PAUSE:
                self._etat = Etat.ACTIF
                self._condition.notify_all()

    def attendre_reprise(self, timeout):
        """Bloque tant qu'on est en pause, borné par « timeout ».

        Revient immédiatement si l'on n'est pas en pause. Le « timeout » borne
        chaque attente pour que le lecteur audio reste réactif au changement
        de génération (coupure/bascule) même figé en pause.
        """
        with self._condition:
            if self._etat is Etat.EN_PAUSE:
                self._condition.wait(timeout)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run : `.venv/bin/pytest tests/test_state.py -v`
Expected : PASS (7 tests)

- [ ] **Step 5 : Commit**

```bash
git add quest_reader/state.py tests/test_state.py
git commit -m "feat: état de lecture partagé (actif/pause/arrêt)"
```

---

## Task 2 : Lecteur audio pausable (réécriture de `playback.py`)

**Files:**
- Modify: `quest_reader/playback.py` (réécriture complète)
- Modify: `tests/helpers.py:115-125` (remplacer `FauxProcessus`)
- Modify: `tests/test_playback.py` (réécriture complète)
- Modify: `quest_reader/__init__.py:20` (ré-export inchangé — `Playback` garde son nom)

**Interfaces:**
- Consumes: `PlayerState` (Task 1) — mais **injecté**, voir ci-dessous.
- Produces :
  - `class Playback` — mêmes `begin()`, `bump()`, `generation`, `current`, `lock` qu'aujourd'hui (le compteur de génération est inchangé). `play(path, generation)` lit désormais **par tranches**.
  - `playback` : instance unique (inchangée).
  - `player_state` : instance unique de `PlayerState`, exposée par `playback.py` pour que l'overlay, le Reader et le lecteur partagent le même objet.
  - `play_wave(path, generation)` : signature inchangée (les moteurs `piper`/`kokoro`/`xtts` l'appellent tels quels, **aucune modification des moteurs**).

**Note d'architecture :** l'instance `player_state` vit dans `playback.py` à côté de `playback`, par le même motif d'instance unique. `Playback.play` la lit directement (comme `speaker.py:42` lit `playback.generation`). Cela évite de fil-de-fer l'état à travers `play_wave` et les trois moteurs.

**Point délicat — discipline de verrou :** la boucle de tranches tourne **hors** de `self.lock`. Chaque tour lit `self.generation` **sans** verrou (exactement comme `speaker.py:42` et `piper.py:35` le font déjà) et abandonne s'il a changé. L'attente de pause passe par `player_state.attendre_reprise`, **jamais** par `self.lock`. Tenir le lock dans la boucle bloquerait `bump()` → stop/bascule cesserait de marcher.

- [ ] **Step 1 : Remplacer `FauxProcessus` par `FauxSortie` dans `tests/helpers.py`**

Repérer le bloc `class FauxProcessus` (`tests/helpers.py:115-125`) et le remplacer par :

```python
class FauxSortie:
    """Tient le rôle du flux sounddevice : enregistre les tranches écrites.

    « paplay » jouait un fichier d'un bloc ; on lit désormais par tranches et
    on écrit chacune dans un « OutputStream ». On veut savoir combien de
    tranches sont parties (donc si la lecture s'est bien abandonnée à un
    changement de génération) et si le flux a été fermé proprement.
    """

    def __init__(self):
        self.tranches = 0
        self.ferme = False

    def start(self):
        pass

    def write(self, tranche):
        self.tranches += 1

    def stop(self):
        pass

    def close(self):
        self.ferme = True
```

- [ ] **Step 2 : Écrire les tests de `playback.py`**

Réécrire tout `tests/test_playback.py` :

```python
"""Tests de la lecture des sons (quest_reader.playback).

Le lecteur lit le WAV par tranches et écrit chacune dans un flux sounddevice.
On double le flux (« FauxSortie ») et la lecture du WAV : on vérifie le
câblage — génération, pause, fermeture — sans vrai périphérique audio.
"""

import pathlib
import sys
from unittest import mock

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.playback import Playback  # noqa: E402
from quest_reader.state import Etat, PlayerState  # noqa: E402
from tests.helpers import FauxSortie  # noqa: E402


# Un faux WAV : dix tranches d'un échantillon chacune. « _lire_wav » est le
# seul point qui touche le disque — on le double pour ne pas écrire de fichier.
FAUX_WAV = (np.zeros((10, 1), dtype=np.int16), 22050)


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


def test_bump_coupe_le_flux_en_cours():
    """bump() ferme le flux courant, comme il tuait le processus avant."""
    pb = _playback()
    sortie = FauxSortie()
    pb.current = sortie
    pb.bump()
    assert sortie.ferme
```

- [ ] **Step 3 : Lancer les tests, vérifier l'échec**

Run : `.venv/bin/pytest tests/test_playback.py -v`
Expected : FAIL — `Playback()` prend maintenant un argument, `_ouvrir_sortie`/`_lire_wav` n'existent pas.

- [ ] **Step 4 : Réécrire `quest_reader/playback.py`**

```python
"""Lecture des sons synthétisés, par tranches, interruptible et pausable.

Réécrit paplay (qui jouait un fichier d'un bloc, sans pause) par une lecture
tranche par tranche via sounddevice (PortAudio, multiplateforme). Entre deux
tranches, on consulte la génération (coupure/bascule, mécanisme conservé) et
l'état de pause. Dépend de « state » ; expose les instances uniques
« playback » et « player_state » que les moteurs, l'overlay et la capture
partagent.
"""

import threading
import wave

import numpy as np

from quest_reader.state import PlayerState


TRANCHE_MS = 20  # durée d'une tranche : compromis latence de pause / surcoût.


class Playback:
    """Joue les sons par tranches, sait les couper et les figer.

    Le compteur de génération est INCHANGÉ : couper puis reprendre pour un
    nouveau dialogue incrémente la génération, et un son périmé ne part pas.
    La pause est une couche ajoutée : entre deux tranches, si l'état est
    EN_PAUSE, la boucle attend sur « player_state » sans tenir « self.lock »
    (sinon « bump » — qui prend ce lock — ne pourrait plus couper).
    """

    def __init__(self, state):
        self.lock = threading.Lock()
        self.current = None  # flux sounddevice en cours, ou None
        self.generation = 0
        self.state = state

    def begin(self):
        with self.lock:
            return self.generation

    def bump(self):
        """Ouvre une nouvelle génération et coupe le son en cours."""
        with self.lock:
            self.generation += 1
            if self.current is not None:
                self.current.close()
            return self.generation

    def _lire_wav(self, path):
        """Lit un WAV en tableau (frames, canaux) int16 + fréquence.

        Isolé pour être doublé en test — seul point qui touche le disque.
        """
        with wave.open(path, "rb") as fichier:
            frequence = fichier.getframerate()
            canaux = fichier.getnchannels()
            brut = fichier.readframes(fichier.getnframes())
        echantillons = np.frombuffer(brut, dtype=np.int16).reshape(-1, canaux)
        return echantillons, frequence

    def _ouvrir_sortie(self, frequence, canaux):
        """Ouvre un flux sounddevice. Import tardif : PortAudio peut manquer.

        « import sounddevice » lève OSError à l'import quand PortAudio est
        absent — d'où l'import ici et non au niveau module, sur le modèle de
        torch dans xtts.py. Renvoie un OutputStream déjà démarré.
        """
        import sounddevice

        flux = sounddevice.OutputStream(
            samplerate=frequence, channels=canaux, dtype="int16"
        )
        flux.start()
        return flux

    def play(self, path, generation):
        try:
            echantillons, frequence = self._lire_wav(path)
        except Exception as erreur:
            print(f"lecture audio impossible : {erreur}")
            return
        canaux = echantillons.shape[1]
        taille = max(1, int(frequence * TRANCHE_MS / 1000))

        # Ouverture du flux sous lock (comme le Popen d'avant), pour que
        # « bump » puisse le fermer. La BOUCLE, elle, tourne hors lock.
        with self.lock:
            if generation != self.generation:
                return
            flux = self._ouvrir_sortie(frequence, canaux)
            self.current = flux
        try:
            for debut in range(0, len(echantillons), taille):
                # Lecture non verrouillée de la génération, comme
                # speaker.py:42 : un nouveau dialogue abandonne la lecture.
                if generation != self.generation:
                    break
                # Pause : on attend, borné, pour rester réactif à une coupure.
                while self.state.en_pause and generation == self.generation:
                    self.state.attendre_reprise(timeout=0.1)
                if generation != self.generation:
                    break
                flux.write(echantillons[debut : debut + taille])
        finally:
            flux.close()
            with self.lock:
                if self.current is flux:
                    self.current = None


# Instances uniques partagées : les moteurs jouent, la capture coupe, l'overlay
# écrit l'état.
player_state = PlayerState()
playback = Playback(player_state)


def play_wave(path, generation):
    playback.play(path, generation)
```

- [ ] **Step 5 : Lancer les tests, vérifier le succès**

Run : `.venv/bin/pytest tests/test_playback.py -v`
Expected : PASS (5 tests)

- [ ] **Step 6 : Vérifier la non-régression complète**

Run : `.venv/bin/pytest -q`
Expected : tout vert (le ré-export `Playback` de `__init__.py:20` reste valide, `Playback` gardant son nom ; `FauxProcessus` n'est plus importé nulle part).

Si un test importe encore `FauxProcessus`, corriger l'import (`grep -rn FauxProcessus tests/`).

- [ ] **Step 7 : Commit**

```bash
git add quest_reader/playback.py tests/test_playback.py tests/helpers.py
git commit -m "feat: lecture audio par tranches, pausable (sounddevice)"
```

---

## Task 3 : `Speaker.say` lève la pause à la bascule

**Files:**
- Modify: `quest_reader/speaker.py:54-62`
- Modify: `tests/test_speaker.py` (ajout d'un test) — vérifier d'abord son existence : `ls tests/test_speaker.py`. S'il n'existe pas, créer le fichier avec l'en-tête habituel.

**Interfaces:**
- Consumes: `player_state` (Task 2), `PlayerState.reactiver()` (Task 1).
- Produces : rien de nouveau — modifie le comportement de `say`.

**Point précis (advisor) :** la levée de pause à la bascule se fait dans **exactement un endroit**, `Speaker.say` (un nouveau dialogue), **pas** dans `bump()` — car `silence()` appelle aussi `bump()`, et fermer un dialogue pendant une pause ne doit pas défiger silencieusement la voix. On utilise `reactiver()` (et non `reprendre()`) pour ne jamais ressusciter un lecteur stoppé.

- [ ] **Step 1 : Écrire le test**

Ajouter dans `tests/test_speaker.py` :

```python
def test_un_nouveau_dialogue_leve_la_pause():
    """Une bascule vers un nouveau dialogue défige la voix (design : la
    pause « saute » quand un nouveau dialogue reprend le dessus)."""
    from quest_reader.playback import player_state
    from quest_reader.speaker import Speaker

    player_state.pause()
    speaker = Speaker.__new__(Speaker)
    speaker.queue = __import__("queue").Queue(maxsize=1)
    speaker.say("Un nouveau dialogue.")
    assert not player_state.en_pause


def test_fermer_le_dialogue_ne_leve_pas_la_pause():
    """silence() coupe la voix mais ne défige pas : fermer une fenêtre
    pendant une pause ne doit pas relancer une lecture."""
    from quest_reader.playback import player_state
    from quest_reader.speaker import Speaker

    player_state.pause()
    speaker = Speaker.__new__(Speaker)
    speaker.queue = __import__("queue").Queue(maxsize=1)
    speaker.silence()
    assert player_state.en_pause
```

> Note : `player_state` est une instance unique de module — remettre l'état à `ACTIF` en fin de test si d'autres tests du fichier en dépendent (`player_state.reprendre()`), ou construire un `Speaker` avec un état injecté si le fichier grandit. Pour deux tests, un `reprendre()` en fin suffit ; ajouter une fixture si besoin.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `.venv/bin/pytest tests/test_speaker.py -v -k pause`
Expected : `test_un_nouveau_dialogue_leve_la_pause` FAIL (la pause reste).

- [ ] **Step 3 : Modifier `Speaker.say`**

Dans `quest_reader/speaker.py`, ajouter l'import et l'appel :

```python
from quest_reader.playback import playback, player_state
```

et au début de `say` :

```python
    def say(self, text):
        # Un nouveau dialogue lève une éventuelle pause (le design veut que
        # la pause « saute » à la bascule) — mais pas un arrêt explicite :
        # « reactiver » ne touche que EN_PAUSE, jamais ARRETE.
        player_state.reactiver()
        # Un nouveau dialogue coupe l'actuel et ouvre sa propre génération.
        generation = playback.bump()
        ...
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `.venv/bin/pytest tests/test_speaker.py -v`
Expected : PASS

- [ ] **Step 5 : Commit**

```bash
git add quest_reader/speaker.py tests/test_speaker.py
git commit -m "feat: un nouveau dialogue lève la pause (bascule)"
```

---

## Task 4 : le `Reader` consulte l'état (débrayage sur ARRÊTÉ)

**Files:**
- Modify: `quest_reader/reader.py:86-118` (début de `handle`)
- Modify: `tests/test_reader.py` (ajout de tests)
- Modify: `tests/helpers.py:62-76` (`lecteur_nu` — injecter/reset l'état)

**Interfaces:**
- Consumes: `player_state` (Task 2), `PlayerState.arrete` (Task 1).
- Produces : rien de nouveau.

**Comportement (design) :**
- `ARRETE` : `handle` ignore l'image d'entrée (n'analyse pas). La voix a déjà été coupée par le bouton stop (Task 5 branche `stop` → `silence`).
- `EN_PAUSE` : `handle` **continue** de tourner normalement (pour détecter un nouveau dialogue qui reprendra le dessus). La pause n'agit que sur l'audio, pas sur l'analyse.

- [ ] **Step 1 : Écrire les tests**

Ajouter dans `tests/test_reader.py` :

```python
def test_arrete_ignore_les_images():
    """Stoppé, le lecteur n'analyse plus : aucun dialogue n'est dit."""
    from quest_reader.playback import player_state

    reader = lecteur_nu()
    player_state.stop()
    try:
        lus = images(reader, ["Un dialogue qui ne doit pas être lu."] * 3)
        assert lus == []
    finally:
        player_state.reprendre()


def test_en_pause_continue_d_analyser():
    """En pause, l'analyse tourne : un nouveau dialogue est bien détecté
    (c'est lui qui, via Speaker.say, lèvera la pause)."""
    from quest_reader.playback import player_state

    reader = lecteur_nu()
    player_state.pause()
    try:
        lus = images(reader, ["Nouveau dialogue à l'écran."] * 3)
        assert lus == ["Nouveau dialogue à l'écran."]
    finally:
        player_state.reprendre()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `.venv/bin/pytest tests/test_reader.py -v -k "arrete or pause"`
Expected : `test_arrete_ignore_les_images` FAIL (le dialogue est lu).

- [ ] **Step 3 : Modifier `Reader.handle`**

Ajouter l'import dans `quest_reader/reader.py` (au bloc des imports du package) :

```python
from quest_reader.playback import player_state  # noqa: E402
```

et tout en tête de `handle` :

```python
    def handle(self, frame):
        # Stoppé : on débraye l'analyse. La voix a déjà été coupée par le
        # bouton ■ (state.stop() + silence()). En pause, au contraire, on
        # continue : l'analyse doit repérer un nouveau dialogue, qui reprendra
        # le dessus et lèvera la pause.
        if player_state.arrete:
            return
        text, box = find_dialog_box(frame)
        ...
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `.venv/bin/pytest tests/test_reader.py -v`
Expected : PASS (tous, y compris les anciens)

- [ ] **Step 5 : S'assurer que `lecteur_nu` laisse l'état propre**

Vérifier que les tests reader existants ne cassent pas parce qu'un test précédent a laissé `player_state` en pause/arrêt. Les nouveaux tests remettent `ACTIF` dans leur `finally`. Aucune modif de `lecteur_nu` n'est nécessaire si l'ordre des tests reste sain ; si un flottement apparaît, ajouter au début de `lecteur_nu` :

```python
    from quest_reader.playback import player_state
    player_state.reprendre()  # part d'un état ACTIF connu
```

- [ ] **Step 6 : Commit**

```bash
git add quest_reader/reader.py tests/test_reader.py tests/helpers.py
git commit -m "feat: le lecteur débraye l'analyse quand il est arrêté"
```

---

## Task 5 : l'overlay Qt (‖ ■ ▶)

**Files:**
- Create: `quest_reader/overlay.py`
- Test: `tests/test_overlay.py`
- Modify: `.venv` — installer PySide6 (voir Step 0)

**Interfaces:**
- Consumes: `player_state` (Task 2), un callback `couper` (fourni par `__main__`, Task 6) pour couper la voix au stop (`Speaker.silence`).
- Produces :
  - `class Overlay(QWidget)` : fenêtre sans bordure, always-on-top, déplaçable, trois boutons.
    - `__init__(self, state, couper)` : `state` = `PlayerState`, `couper` = callable sans argument (coupe la voix).
    - `on_pause()` : `state.pause()`.
    - `on_stop()` : `state.stop()` **puis** `couper()`.
    - `on_reprise()` : `state.reprendre()`.
    - `_rafraichir()` : grise le bouton correspondant à l'état courant.

**Point sur les tests :** Qt se teste sans affichage réel avec `QApplication([])` et la plateforme `offscreen` (`QT_QPA_PLATFORM=offscreen`). On ne teste **pas** le rendu ni l'always-on-top (vérif manuelle, Task 7) — seulement qu'un clic écrit la bonne transition.

- [ ] **Step 0 : Installer PySide6 et sounddevice dans le venv**

Run :
```bash
.venv/bin/pip install PySide6 sounddevice
```
Expected : installation réussie. (sounddevice était requis par Task 2 ; l'installer ici au plus tard, avant le premier lancement réel.)

Vérifier l'import :
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import PySide6.QtWidgets; print('ok')"
```

- [ ] **Step 1 : Écrire les tests**

```python
"""Tests de l'overlay Qt (quest_reader.overlay).

Qt tourne « offscreen » : on ne teste pas le rendu ni l'always-on-top
(vérif manuelle en jeu), seulement qu'un clic écrit la bonne transition dans
PlayerState et que le stop coupe la voix.
"""

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from quest_reader.state import Etat, PlayerState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def test_pause_ecrit_en_pause(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    overlay = Overlay(state, couper=lambda: None)
    overlay.on_pause()
    assert state.etat is Etat.EN_PAUSE


def test_stop_ecrit_arrete_et_coupe_la_voix(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    coupures = []
    overlay = Overlay(state, couper=lambda: coupures.append(True))
    overlay.on_stop()
    assert state.etat is Etat.ARRETE
    assert coupures == [True]  # la voix a bien été coupée


def test_reprise_ecrit_actif(app):
    from quest_reader.overlay import Overlay

    state = PlayerState()
    state.pause()
    overlay = Overlay(state, couper=lambda: None)
    overlay.on_reprise()
    assert state.etat is Etat.ACTIF
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_overlay.py -v`
Expected : FAIL — `No module named 'quest_reader.overlay'`

- [ ] **Step 3 : Écrire `quest_reader/overlay.py`**

```python
"""Overlay de contrôle : petite fenêtre flottante, always-on-top, 3 boutons.

Dépend de « state » : un clic écrit une transition dans PlayerState, rien de
plus (l'overlay ne touche jamais directement la capture ni l'audio). Le stop
appelle en plus un callback « couper » pour arrêter la voix en cours.

PySide6 est importé tardivement (dans les méthodes / à la construction) : le
module doit rester importable pour les tests même hors contexte Qt, et Qt est
une dépendance lourde qu'on ne charge qu'au lancement de l'interface.
"""

from quest_reader.state import Etat


def _construire_widget():
    """Importe Qt et renvoie la classe de base, tardivement."""
    from PySide6.QtWidgets import QWidget

    return QWidget


class Overlay:
    """Trois boutons — ‖ ■ ▶ — qui pilotent l'état de lecture.

    N'hérite pas de QWidget au niveau module (Qt importé tardivement) : la
    vraie fenêtre est construite dans « __init__ ». Les méthodes on_* sont
    testables sans affichage réel.
    """

    def __init__(self, state, couper):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

        self.state = state
        self.couper = couper

        self.widget = QWidget()
        self.widget.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        disposition = QHBoxLayout(self.widget)

        self.bouton_pause = QPushButton("‖")
        self.bouton_stop = QPushButton("■")
        self.bouton_reprise = QPushButton("▶")
        self.bouton_pause.clicked.connect(self.on_pause)
        self.bouton_stop.clicked.connect(self.on_stop)
        self.bouton_reprise.clicked.connect(self.on_reprise)
        for bouton in (self.bouton_pause, self.bouton_stop, self.bouton_reprise):
            disposition.addWidget(bouton)

        self._rafraichir()

    def on_pause(self):
        self.state.pause()
        self._rafraichir()

    def on_stop(self):
        # Ordre voulu : d'abord débrayer l'analyse, puis couper la voix.
        self.state.stop()
        self.couper()
        self._rafraichir()

    def on_reprise(self):
        self.state.reprendre()
        self._rafraichir()

    def _rafraichir(self):
        """Grise le bouton correspondant à l'état courant."""
        etat = self.state.etat
        self.bouton_pause.setEnabled(etat is not Etat.EN_PAUSE)
        self.bouton_stop.setEnabled(etat is not Etat.ARRETE)
        self.bouton_reprise.setEnabled(etat is not Etat.ACTIF)

    def show(self):
        self.widget.show()
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_overlay.py -v`
Expected : PASS (3 tests)

- [ ] **Step 5 : Commit**

```bash
git add quest_reader/overlay.py tests/test_overlay.py
git commit -m "feat: overlay Qt de contrôle (pause/stop/reprise)"
```

---

## Task 6 : orchestration — Qt principal + Reader en thread

**Files:**
- Modify: `quest_reader/reader.py:157-168` (scinder `run`)
- Modify: `quest_reader/__main__.py:80-85` (lancement)
- Modify: `quest_reader/__init__.py` (ré-export `PlayerState`)

**Interfaces:**
- Consumes: `Overlay` (Task 5), `player_state` (Task 2), `Reader` (Task 4).
- Produces : point d'entrée qui fait tourner Qt sur le thread principal et le `Reader` dans un thread dédié.

**Points délicats (advisor) — à respecter à la lettre :**

1. **`signal.signal()` ne marche que sur le thread principal.** Aujourd'hui `reader.py:162` installe SIGINT ; si `run()` descend dans un thread, il lève `ValueError`. → Le SIGINT reste dans `__main__` (thread principal, celui de Qt). On scinde `Reader.run()` : la partie thread ne fait **pas** `signal.signal`.

2. **Qt et SIGINT** : Qt ne rend pas la main à l'interpréteur pour ses handlers Python. Un `QTimer` no-op périodique (~200 ms) force l'interpréteur à tourner, pour que Ctrl+C soit vu.

3. **`GLib.MainLoop()` dans un thread non-principal est LE risque.** `GLib.MainLoop()` sans argument + `DBusGMainLoop(set_as_default=True)` s'accrochent au contexte par défaut, dont l'exécution hors thread principal peut ne jamais recevoir la réponse du portail (→ `on_node` jamais appelé, capture jamais démarrée). Ce risque **n'est visible qu'au lancement réel** (Task 7), aucun test unitaire ne le couvre — même angle mort que le crop `THEME_BLEU` qui a masqué le bug de stop, cf. `[[quest-reader-coupure-per-box]]`.
   - **Plan A (essayer d'abord)** : contexte par défaut, `Reader` dans un thread. Si la capture démarre et lit un dialogue → OK.
   - **Plan B (repli si le portail ne rappelle jamais)** : rester **mono-thread** — piloter GLib depuis le thread Qt via un `QTimer` qui appelle `GLib.MainContext.default().iteration(False)` à chaque tick. Tout reste sur le thread principal, plus de souci de contexte. Documenté ici pour que l'agent ne reste pas bloqué.

- [ ] **Step 1 : Scinder `Reader.run`**

Dans `quest_reader/reader.py`, remplacer `run` (`157-168`) par :

```python
    def demarrer_capture(self):
        """Lance la capture et rend la boucle GLib prête à tourner.

        SIGINT n'est PAS installé ici : « signal.signal » ne fonctionne que
        sur le thread principal, et cette méthode tourne dans un thread dédié
        (l'overlay Qt tient le thread principal). L'arrêt vient de l'extérieur
        via « self.loop.quit() » (voir __main__).
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.cast = ScreenCast(self.on_node)
        self.cast.start()
        self.loop = GLib.MainLoop()

    def boucler(self):
        """Corps du thread de capture : fait tourner la boucle GLib."""
        try:
            self.loop.run()
        finally:
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
            self.speaker.stop()

    def arreter(self):
        """Demande l'arrêt de la boucle GLib (appelé depuis un autre thread)."""
        if getattr(self, "loop", None) is not None:
            self.loop.quit()

    def run(self):
        """Lancement autonome (sans overlay), pour compat/débogage.

        Installe SIGINT ici car on est alors sur le thread principal.
        """
        self.demarrer_capture()
        signal.signal(signal.SIGINT, lambda *_: self.loop.quit())
        self.boucler()
```

Ajouter `self.cast = None` et `self.loop = None` dans `__init__` (à côté de `self.pipeline = None`).

- [ ] **Step 2 : Réécrire `main()` dans `__main__.py`**

Remplacer le bloc final (`80-85`, après le `check_xtts`) par :

```python
    # Avant de lancer la capture : une fois le fil parti, plus aucun
    # message d'erreur du moteur n'atteindrait l'utilisateur.
    if args.engine == "xtts":
        check_xtts(args)

    lancer_avec_overlay(args)


def lancer_avec_overlay(args):
    """Qt sur le thread principal, la capture dans un thread dédié.

    On n'unifie pas les boucles d'événements : on les isole. Qt tient le
    thread principal (l'overlay), et la boucle GLib de capture descend dans un
    thread. Ils ne communiquent qu'à travers PlayerState et le Speaker.
    """
    import signal
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from quest_reader.overlay import Overlay
    from quest_reader.playback import player_state
    from quest_reader.reader import Reader

    app = QApplication(sys.argv)

    reader = Reader(args)
    reader.demarrer_capture()

    # Le stop de l'overlay coupe la voix en cours.
    overlay = Overlay(player_state, couper=reader.speaker.silence)
    overlay.show()

    fil_capture = threading.Thread(target=reader.boucler, daemon=True)
    fil_capture.start()

    # Ctrl+C : Qt ne rend pas la main aux handlers Python sans un réveil
    # périodique de l'interpréteur.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    reveil = QTimer()
    reveil.start(200)
    reveil.timeout.connect(lambda: None)

    # Arrêt propre : à la fermeture de Qt, on arrête la boucle GLib et on
    # attend la fin du thread de capture (qui met le pipeline à NULL et stoppe
    # le Speaker dans son finally).
    def au_depart():
        reader.arreter()
        fil_capture.join(timeout=5)

    app.aboutToQuit.connect(au_depart)

    app.exec()
```

- [ ] **Step 3 : Ré-exporter `PlayerState`**

Dans `quest_reader/__init__.py`, ajouter après l'import de `Playback` :

```python
from quest_reader.state import Etat, PlayerState  # noqa: F401
```

- [ ] **Step 4 : Vérifier que la suite reste verte**

Run : `.venv/bin/pytest -q`
Expected : tout vert. (Les tests ne lancent pas Qt réellement ni la capture ; `main` n'est pas testé unitairement — c'est la Task 7 qui le couvre manuellement.)

- [ ] **Step 5 : Commit**

```bash
git add quest_reader/reader.py quest_reader/__main__.py quest_reader/__init__.py
git commit -m "feat: orchestration Qt (principal) + capture (thread)"
```

---

## Task 7 : vérification manuelle en jeu (le test que le code ne couvre pas)

**Files:** aucun (vérification manuelle).

**Pourquoi une tâche à part :** les tests des tâches 1 à 6 vérifient chacun un câblage isolé. Ils sont **aveugles par construction** à deux choses qui ne se voient qu'en conditions réelles — la boucle GLib dans un thread (Plan A/B, Task 6) et le rendu always-on-top de l'overlay. C'est exactement la forme d'angle mort qui avait laissé passer le bug de stop pendant des semaines (crop `THEME_BLEU`, cf. `[[quest-reader-coupure-per-box]]`). On matérialise donc la vérif comme un livrable.

- [ ] **Step 1 : Lancer l'application avec le jeu ouvert**

Run :
```bash
.venv/bin/python -m quest_reader --engine piper
```
Choisir la fenêtre de jeu dans le sélecteur du portail.

**À observer :**
- L'overlay apparaît et reste **au-dessus** de la fenêtre de jeu.
- Un dialogue de PNJ est **lu** (⇒ la capture a bien démarré depuis le thread : **Plan A OK**).

- [ ] **Step 2 : Si aucun dialogue n'est lu et que « Lecture active » ne s'affiche pas → Plan B**

Le portail ne rappelle pas depuis le thread. Basculer en mono-thread : dans `lancer_avec_overlay`, **supprimer** le `threading.Thread` et piloter GLib depuis Qt :

```python
    from gi.repository import GLib

    contexte = GLib.MainContext.default()
    pompe = QTimer()
    pompe.start(10)
    pompe.timeout.connect(lambda: contexte.iteration(False))
```

et à `au_depart`, appeler `reader.arreter()` sans `join` (plus de thread). Re-tester le Step 1.

- [ ] **Step 3 : Tester les trois boutons**

- **‖** pendant une réplique : la voix se **fige** au milieu.
- **▶** : la voix **reprend** là où elle en était (au milieu du mot).
- Un **nouveau dialogue** pendant une pause : il **reprend le dessus** (la pause saute).
- **■** : la voix se **coupe** et plus rien n'est lu.
- **▶** après ■ : le lecteur **réanalyse** l'écran.

- [ ] **Step 4 : Fermer proprement**

Fermer l'overlay (ou Ctrl+C dans le terminal) : l'app quitte sans traîner de processus, sans erreur `libespeak-ng` en boucle (⇒ `Speaker.stop` a bien été appelé via le `finally` de `boucler`).

- [ ] **Step 5 : Si Plan B a été retenu, committer le repli**

```bash
git add quest_reader/__main__.py
git commit -m "fix: piloter GLib depuis Qt (le portail ne rappelle pas hors thread principal)"
```

---

## Auto-revue (couverture du design)

| Section du design | Tâche |
|---|---|
| État partagé `PlayerState` (ACTIF/EN_PAUSE/ARRÊTÉ) | Task 1 |
| Stop débraye l'analyse | Task 4 |
| Pause agit sur l'audio sans débrayer | Task 2 (audio) + Task 4 (analyse continue) |
| Lecture par tranches, génération conservée, pause | Task 2 |
| Reprise repart à la tranche suivante | Task 2 (`test_la_pause_bloque_avant_la_tranche_suivante`) |
| Pause → nouveau dialogue reprend le dessus (bascule) | Task 3 |
| Overlay Qt, 3 boutons, boutons grisés selon l'état | Task 5 |
| Articulation des boucles (Qt principal, capture thread, Speaker) | Task 6 |
| Erreur : pas de périphérique / sounddevice absent | Task 2 (`play` capture l'exception + import tardif) |
| Fermeture propre de l'app | Task 6 (`aboutToQuit`) + Task 7 (vérif) |
| Tests state / playback / overlay / reader | Tasks 1, 2, 4, 5 |
| Vérif manuelle (rendu, always-on-top, latence) | Task 7 |

**Points hors périmètre (design) non traités, volontairement :** portage capture Windows/Mac, packaging, réglages fins d'apparence.
