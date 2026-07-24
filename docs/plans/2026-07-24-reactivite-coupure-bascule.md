# Réactivité coupure/bascule — Plan d'implémentation

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Couper la voix sous 0,5 s à la fermeture du dialogue, et basculer immédiatement au dialogue suivant.

**Architecture:** Deux changements indépendants dans `quest_reader.py`. (A) La coupure repose déjà sur `find_bubbles` (couleur, sans OCR) ; on retire le compteur `CLOSED_AFTER` au profit d'un seuil de 2 images et on monte `--fps` à 4. (B) `Speaker` passe d'une file d'attente (`BACKLOG=4`) à une bascule immédiate : `say` purge la file et coupe le son, et un compteur de génération élimine la course sur le booléen `stopped`.

**Tech Stack:** Python 3.14, pytest, OpenCV, threading/queue, pytesseract. Venv en `.venv/`.

**Design de référence:** `docs/plans/2026-07-24-reactivite-coupure-bascule-design.md`

**Commande de test globale:** `.venv/bin/python -m pytest tests/ -q`

**Les deux volets sont indépendants** et peuvent être faits dans l'ordre du plan. Volet A (coupure) d'abord, Volet B (bascule) ensuite.

---

## VOLET A — Coupure rapide à la fermeture

### Task A1 : Retirer `CLOSED_AFTER`, couper après 2 images sans bulle

**Files:**
- Modify: `quest_reader.py` — classe `Reader` (`CLOSED_AFTER` l.939, `handle` l.1006-1015)
- Test: `tests/test_detection.py`

**Contexte.** Aujourd'hui `handle` compte `self.missing` et coupe quand
`self.missing == self.CLOSED_AFTER` (== 3). On remplace le constante de classe
par un seuil littéral de 2, en gardant l'égalité (déclenche une seule fois).

**Step 1 : Écrire les tests qui reflètent la nouvelle spec**

Dans `tests/test_detection.py`, **supprimer** les deux tests dont l'intention
est désormais inversée ou vide :
- `test_une_bulle_absente_une_seule_image_ne_coupe_pas` (l.513) — une image
  absente NE coupe pas : reste vrai avec seuil 2, mais réécrit ci-dessous pour
  être explicite plutôt que dépendre de `CLOSED_AFTER`.
- `test_une_bulle_qui_revient_annule_le_decompte` (l.584) — teste un décompte
  qui existe encore (seuil 2), à réécrire sans `CLOSED_AFTER`.

Remplacer **toutes** les occurrences de `Reader.CLOSED_AFTER` par le littéral
correspondant au nouveau seuil. Les sites (mesurés) :
- l.516 `[None] * (Reader.CLOSED_AFTER - 1)` → `[None] * 1`
- l.523 `[None] * Reader.CLOSED_AFTER` → `[None] * 2`
- l.540 `trou = [None] * Reader.CLOSED_AFTER` → `trou = [None] * 2`
- l.562 `[None] * Reader.CLOSED_AFTER` → `[None] * 2`
- l.573 `[None] * Reader.CLOSED_AFTER` → `[None] * 2`
- l.580 `[None] * (Reader.CLOSED_AFTER * 4)` → `[None] * 8`
- l.587 `manquantes = [None] * (Reader.CLOSED_AFTER - 1)` → `[None] * 1`

Réécrire les deux tests supprimés en versions explicites :

```python
def test_une_bulle_absente_une_seule_image_ne_coupe_pas():
    """Une image absente isolée ne coupe pas : le seuil est de deux."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None])
    reader.speaker.silence.assert_not_called()


def test_deux_images_absentes_coupent():
    """Le seuil de coupure est de deux images sans bulle."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None, None])
    reader.speaker.silence.assert_called_once()


def test_une_bulle_qui_revient_annule_le_decompte():
    """Une image sans bulle puis une avec : le décompte repart de zéro."""
    reader = lecteur_nu()
    images(reader, [None] + ["Me revoilà."] + [None])
    reader.speaker.silence.assert_not_called()
```

**Step 2 : Lancer les tests, vérifier qu'ils échouent franchement**

Run: `.venv/bin/python -m pytest tests/test_detection.py -q 2>&1 | tail -20`
Expected: FAIL. **Plusieurs** tests échouent, c'est normal : le code coupe
encore à 3 images alors que les tests attendent désormais 2. En particulier
`test_deux_images_absentes_coupent` (silence non appelé après 2 images) et
`test_la_bulle_fermee_coupe_la_dictee` (attend maintenant 2, le code fait 3).
Voir du rouge ici est le signe que la spec a bien bougé — continuer.

**Step 3 : Retirer le compteur, seuil littéral 2**

Dans `quest_reader.py`, classe `Reader` : **supprimer** la constante
`CLOSED_AFTER = 3` et son commentaire (l.936-939).

Dans `handle`, remplacer le bloc l.1006-1007 :

```python
            self.missing += 1
            if self.missing == self.CLOSED_AFTER:
```

par (le commentaire ci-dessous remplace celui de la constante retirée) :

```python
            # Deux images sans bulle avant de couper. À --fps 4 cela fait une
            # demi-seconde : assez pour absorber un raté de détection isolé
            # (find_bubbles peut manquer une image sous bruit fort), assez
            # court pour suivre le geste de fermeture. L'égalité fait couper
            # une seule fois, pas à chaque image absente au-delà.
            self.missing += 1
            if self.missing == CLOSED_AFTER:
```

Ajouter la constante au niveau module, près des autres seuils (chercher un
groupe de constantes en haut de fichier, p. ex. après `MIN_CHARS`) :

```python
CLOSED_AFTER = 2  # images sans bulle avant de couper la voix
```

**Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `.venv/bin/python -m pytest tests/test_detection.py -q 2>&1 | tail -10`
Expected: PASS (tous verts).

**Step 5 : Vérifier qu'aucun `Reader.CLOSED_AFTER` ne subsiste**

Run: `grep -rn "Reader.CLOSED_AFTER\|self.CLOSED_AFTER" quest_reader.py tests/`
Expected: aucune sortie (référence de classe/instance éliminée).

**Step 6 : Commit**

```bash
git add quest_reader.py tests/test_detection.py
git commit -m "feat: couper la voix après 2 images sans bulle"
```

---

### Task A2 : Passer `--fps` par défaut à 4

**Files:**
- Modify: `quest_reader.py:1156` (argument `--fps`), commentaires de `Reader`

**Step 1 : Modifier le défaut**

Ligne 1156, remplacer :

```python
    parser.add_argument("--fps", type=int, default=2, help="images analysées par seconde")
```

par :

```python
    parser.add_argument("--fps", type=int, default=4, help="images analysées par seconde")
```

**Step 2 : Vérifier qu'aucun test ne fixe `repeat_after`/`fps` en dur sur 2**

Run: `grep -rn "fps" tests/test_detection.py`
Expected: aucun test ne dépend du défaut de `--fps` (les tests pilotent
`handle` image par image, pas l'horloge). Si un test apparaît, l'inspecter.

**Step 3 : Lancer toute la suite**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5`
Expected: PASS (164+ tests, aucun lié au défaut de fps).

**Step 4 : Commit**

```bash
git add quest_reader.py
git commit -m "feat: analyser 4 images par seconde par défaut"
```

---

## VOLET B — Bascule immédiate au dialogue suivant

### Task B1 : Bascule immédiate (Playback + Speaker + moteurs, atomique)

> **Une seule tâche, un seul commit.** Le compteur de génération remplace le
> couple `stopped`/`resume`/`stop` partagé par `Playback`, `Speaker` et les
> trois moteurs. Ils forment un seul contrat : le scinder laisserait un arbre
> rouge entre deux commits (`Speaker.say` appellerait un `playback.resume()`
> supprimé). On réécrit tout, on ne commet qu'une fois vert.

**Files:**
- Modify: `quest_reader.py` — `Playback` (l.539-575), `play_wave` (l.582),
  `PiperEngine.speak` (l.603-615), `KokoroEngine.speak` (l.637-652),
  `XttsEngine.speak` (l.719-757), `Speaker` (l.760-836)
- Test: `tests/test_detection.py`

**Contexte.** La course : `silence()` pose `stopped=True`, puis `say()` →
`resume()` pose `stopped=False` avant que le `Speaker` ait vu l'arrêt →
l'ancien dialogue reprend. Et `say()` empile derrière la file (`BACKLOG=4`) au
lieu de couper. On remplace le booléen par un **compteur de génération** :
chaque énoncé porte sa génération ; le son ne part que si la génération n'a pas
changé depuis le début de l'énoncé. `BACKLOG` tombe à 1.

**Contrat des trois moteurs (vérifié en lisant le code) :** chacun a
exactement un point de lecture `play_wave(path)`. Piper (l.609) et XTTS (l.743)
ont en plus une garde `if playback.stopped:` en cours de boucle ; Kokoro n'en a
pas (une seule phrase par appel). La révision : signature `speak(self, text,
narration, generation)`, garde `if generation != playback.generation:` là où
il y avait `playback.stopped`, et `play_wave(path)` → `play_wave(path,
generation)`.

**Step 1 : Écrire les tests (course + bascille + Playback)**

Ajouter/réécrire dans `tests/test_detection.py`. **Réécrire** les deux tests
Playback existants (`test_playback_refuse_de_jouer_apres_un_arret` l.375 et
`test_playback_coupe_le_son_en_cours` l.388) qui utilisent l'ancienne API :

```python
def test_playback_ne_joue_pas_une_generation_perimee():
    """Un son commandé avant un changement de génération ne part pas.

    Garantie qui remplace « stopped » : couper puis reprendre pour un
    nouveau dialogue ne laisse pas jouer l'ancien.
    """
    playback = Playback()
    gen = playback.begin()          # génération de l'ancien dialogue
    playback.bump()                 # un nouveau dialogue survient
    with mock.patch("subprocess.Popen") as popen:
        playback.play("/tmp/x.wav", gen)   # son de l'ancien : périmé
    popen.assert_not_called()


def test_playback_joue_la_generation_courante():
    """Un son de la génération courante part bien."""
    playback = Playback()
    gen = playback.begin()
    with mock.patch("subprocess.Popen", return_value=FauxProcessus()) as popen:
        playback.play("/tmp/x.wav", gen)
    popen.assert_called_once()


def test_playback_coupe_le_son_en_cours():
    """bump() tue le processus en vol."""
    playback = Playback()
    processus = FauxProcessus()
    playback.current = processus
    playback.bump()
    assert processus.tue


def test_un_nouveau_dialogue_coupe_le_precedent():
    """say(B) pendant la lecture de A coupe A et n'empile pas.

    On n'a pas besoin de démarrer le thread : on éprouve l'effet de say sur
    la file et la génération de l'instance module « playback ».
    """
    class MoteurFactice:
        def speak(self, texte, narration, generation):
            pass

    speaker = Speaker(MoteurFactice)
    g0 = playback.generation
    speaker.say("Dialogue A.")
    speaker.say("Dialogue B.")
    assert speaker.queue.qsize() <= 1     # BACKLOG = 1, pas d'empilement
    assert playback.generation > g0       # chaque say ouvre une génération
```

> Note : `playback` est l'instance module unique importée par les tests. Ces
> tests la mutent (génération) ; c'est déjà le cas des tests Playback
> existants, sans isolation particulière.

**Step 2 : Lancer, vérifier l'échec franc**

Run: `.venv/bin/python -m pytest tests/test_detection.py -q 2>&1 | tail -20`
Expected: FAIL. `Playback` n'a ni `begin` ni `bump`, `play` ne prend pas de
génération, `say` n'ouvre pas de génération et `BACKLOG` vaut 4. Plusieurs
tests rouges — normal.

**Step 3 : Réécrire `Playback`**

Remplacer la classe `Playback` (l.539-575) par :

```python
class Playback:
    """Joue les sons, et sait les interrompre depuis un autre fil.

    « paplay » bloque jusqu'à la fin du fichier : pour couper la voix quand
    le joueur ferme le dialogue ou passe au suivant, il faut tuer le
    processus. Un compteur de génération, plutôt qu'un booléen, évite une
    course : couper puis reprendre pour un nouveau dialogue incrémente la
    génération, et un son d'une génération périmée ne part pas — même si le
    fil « Speaker » n'a pas encore vu le changement.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.generation = 0

    def begin(self):
        """Génération courante, relevée au début d'un énoncé."""
        with self.lock:
            return self.generation

    def bump(self):
        """Ouvre une nouvelle génération et coupe le son en cours.

        Renvoie le nouveau numéro : « say » l'attache à l'énoncé qu'il enfile.
        """
        with self.lock:
            self.generation += 1
            if self.current is not None:
                self.current.terminate()
            return self.generation

    def play(self, path, generation):
        with self.lock:
            if generation != self.generation:
                return
            self.current = subprocess.Popen(
                ["paplay", path], stderr=subprocess.DEVNULL
            )
        self.current.wait()
        with self.lock:
            self.current = None
```

`stop`/`resume`/`stopped` disparaissent.

**Step 4 : Adapter `play_wave` et les trois moteurs**

`play_wave` (l.582) prend la génération :

```python
def play_wave(path, generation):
    playback.play(path, generation)
```

Pour chaque moteur, ajouter `generation` à la signature de `speak`, remplacer
la garde `if playback.stopped:` par `if generation != playback.generation:`,
et passer `generation` à `play_wave` :
- `PiperEngine.speak` (l.603) : signature ; garde l.609 ; `play_wave` l.614.
- `KokoroEngine.speak` (l.637) : signature ; pas de garde `stopped` à
  remplacer ; `play_wave` l.652.
- `XttsEngine.speak` (l.719) : signature ; garde l.743 ; `play_wave` l.757.

**Step 5 : Réécrire `Speaker`**

- `BACKLOG = 4` → `BACKLOG = 1` (adapter le commentaire l.769-775 : la file ne
  garde qu'un énoncé, un nouveau dialogue coupe et remplace au lieu d'empiler).
- `run`, `silence`, `say`, plus un `_drain` privé :

```python
    BACKLOG = 1  # un seul énoncé : un nouveau dialogue coupe, il n'empile pas.

    def run(self):
        engine = self.build_engine()
        while True:
            item = self.queue.get()
            if item is None:
                return
            generation, segments = item
            for narration, part in segments:
                # Un nouveau dialogue a pu survenir : ne pas entamer la suite
                # d'un énoncé périmé.
                if generation != playback.generation:
                    break
                try:
                    engine.speak(part, narration, generation)
                except Exception as error:
                    print(f"synthèse impossible : {error}", file=sys.stderr)

    def silence(self):
        """Coupe la voix et jette ce qui restait à dire."""
        playback.bump()
        self._drain()

    def say(self, text):
        # Un nouveau dialogue coupe l'actuel et ouvre sa propre génération.
        generation = playback.bump()
        self._drain()
        try:
            self.queue.put_nowait((generation, split_narration(text)))
        except queue.Full:
            # Jamais bloquer ici : cet appel vient du fil de capture.
            print("lecture en retard : dialogue ignoré", file=sys.stderr)

    def _drain(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
```

`stop(self, timeout=5)` (l.821) purge déjà la file ; remplacer sa boucle de
purge par `self._drain()` et garder le `put(None)` + `join(timeout)`.

**Step 6 : Adapter les moteurs factices des tests**

Toute classe de test avec `def speak(self, texte, narration)` doit prendre
`generation`. Les repérer :

Run: `grep -n "def speak" tests/test_detection.py`
Expected: ajouter `, generation` à chaque signature de moteur factice
(y compris celui de `test_le_ctrl_c_purge_la_file`/`Speaker.stop` autour de
l.304).

**Step 7 : Lancer toute la suite**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -15`
Expected: PASS. Points de vigilance :
- `test_deux_repliques_successives_sont_toutes_deux_lues` (l.449) reste vert :
  A et B toutes deux lues via `handle` ; la bascule ne perd que le reliquat de A.
- `test_la_file_du_speaker_ne_grossit_pas_sans_fin` (l.592) : l'attendu
  `qsize() <= Speaker.BACKLOG` reste juste (BACKLOG vaut 1 maintenant).
- `test_say_ne_bloque_pas_le_fil_de_capture` (l.609) : `say` purge et enfile
  sans attendre — toujours non bloquant.
- Le test `Speaker.stop` (l.304-316) : le `MoteurFactice` a la nouvelle
  signature ; l'arrêt reste immédiat.

**Step 8 : Vérifier qu'aucune trace de l'ancienne API ne subsiste**

Run: `grep -rn "playback.stopped\|\.resume()\|\.stop()" quest_reader.py`
Expected: aucun `playback.stopped`, aucun `.resume()`. (`Speaker.stop()` et
`pipeline`/`Gst` stops peuvent rester — vérifier qu'aucun ne vise `playback`.)

**Step 9 : Commit**

```bash
git add quest_reader.py tests/test_detection.py
git commit -m "feat: bascule immédiate au dialogue suivant via compteur de génération"
```

---

## Vérification finale

### Task V1 : Suite complète + revue manuelle

**Step 1 : Toute la suite**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -10`
Expected: PASS, 0 échec.

**Step 2 : Aucune référence morte**

Run: `grep -rn "CLOSED_AFTER\|playback.stopped\|\.resume()\|BACKLOG = 4" quest_reader.py`
Expected: `CLOSED_AFTER` uniquement comme constante module (=2) et son usage
dans `handle` ; aucun `playback.stopped`, aucun `.resume()`, aucun
`BACKLOG = 4`. (`play_wave` subsiste, mais avec la signature `(path,
generation)` — vérifier qu'aucun appel ne l'invoque sans génération.)

**Step 3 : Vérification en jeu (manuelle, hors CI)**

Lancer le lecteur sur une vraie session :
- Fermer une fenêtre de dialogue → la voix se coupe en ~0,5 s.
- Ouvrir un menu par-dessus un dialogue → la voix se coupe, et au retour le
  dialogue **n'est pas relu**.
- Passer d'un PNJ à un autre (ou avancer dans un échange) → le nouveau dialogue
  coupe l'ancien sans attendre la fin de la lecture en cours.

Confirmer sur deux PNJ connus (Oto Mustam, Mak Gahan).

## Hors périmètre

- Reformulation du commentaire « écriture progressive » (cosmétique, note dans
  le design).
- Voie de sondage `find_bubbles` séparée de l'OCR (repli si CPU insuffisant).
