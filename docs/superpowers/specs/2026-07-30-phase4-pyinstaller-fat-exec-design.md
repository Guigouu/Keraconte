# Phase 4 — Packaging PyInstaller : exécutables Windows + Linux

Date : 2026-07-30
Branche : `feat/portabilite-multiplateforme`
Statut : design validé, avant implémentation.

## Contexte

Les phases 1–3 ont rendu quest-reader importable et fonctionnel hors Linux
(découplage import, backend `mss`, résolution portable de tesseract/voix). La
CI est verte sur les 3 OS. La **frontière du port** est `Reader.handle(frame)` ;
tout l'aval est agnostique. Il reste à **livrer un exécutable packagé** par OS.

Le code résout déjà ses ressources depuis la racine du bundle figé
(`sys._MEIPASS`) EN PRIORITÉ :
- `detection.configurer_tesseract()` cherche `_MEIPASS/tesseract[.exe]` puis
  `_MEIPASS/tessdata/`.
- `engines._racine_donnees()` cherche `_MEIPASS/piper-voices/`.

**La Phase 4 ne change donc pas la résolution — elle produit le layout que
cette résolution attend, et pose le peu de plomberie d'environnement que le
code ne peut pas faire (chemins de libs natives).**

## Décisions actées (utilisateur)

| Sujet | Décision |
|---|---|
| Cibles ship | **Windows + Linux** (macOS hors ship, compat code préservée) |
| Tesseract | Fourni par le **runner CI** (apt/choco), copié dans le bundle |
| Voix Piper | **Voix FR par défaut** seulement (voir §« Le défaut, c'est DEUX voix ») |
| Déclencheur build | **CI sur tag `v*`** → GitHub Release (+ `workflow_dispatch`) |
| Mode PyInstaller | **onedir** (pas onefile) |
| Pile GStreamer Linux | **Prérequis système** (non embarquée) |
| Libs tesseract | **Bundle complet** + runtime-hook `LD_LIBRARY_PATH` |

## Faits vérifiés qui contraignent le design

1. **`tesseract` n'est pas mono-fichier** : `ldd` montre leptonica, libpng,
   libjpeg, libtiff, libwebp. Copier le seul binaire produit un exe qui meurt
   sur une machine sans ces libs → il faut embarquer les `.so` ET pointer
   `LD_LIBRARY_PATH` vers la racine du bundle (le process tesseract est
   externe, PyInstaller ne le patche pas).
2. **La pile GStreamer/gi existe côté distro** (typelibs `Gst-*`,
   `libgstpipewire.so`, `gst-plugin-scanner`) — le freeze complet serait
   possible mais fragile. Décision : **prérequis système**, on ne la fige pas.
   Conséquence : l'exe **Linux n'est pas totalement autonome** (suppose
   gi/GStreamer/PipeWire installés — paquets distro déjà requis aujourd'hui).
   L'exe **Windows est pleinement autonome** (mss pur-Python, aucune pile
   système).
3. **onefile ré-extrait ~0,5–1 Go à chaque lancement** → démarrage lent.
   **onedir** rend `sys._MEIPASS` = le dossier `dist/` lui-même : démarrage
   instantané, code de résolution inchangé.
4. **`_racine_donnees()` verrouille les voix sur le bundle** : dès que
   `_MEIPASS/piper-voices/` existe (toujours le cas dans l'exe), il retourne
   la racine du bundle et **ne consulte JAMAIS `user_data_dir`**. Donc dans
   l'exe figé, **déposer une voix dans `~/.local/share` (ou `%LOCALAPPDATA%`)
   n'a aucun effet** — pour une voix externe il faut un chemin absolu explicite
   `--voice /chemin/voix.onnx`. À documenter côté utilisateur (limite connue,
   pas un bug).

## Le défaut, c'est DEUX voix (piège)

Le comportement par défaut utilise **deux** voix, chacune avec son `.onnx` ET
son `.onnx.json` (config obligatoire de Piper) :
- `--voice` (PNJ) : `fr_FR-tom-medium.onnx`
- `--narrator` (actions entre `*astérisques*`) : `fr_FR-siwis-medium.onnx`

« Embarquer la voix FR par défaut » = embarquer **ces deux voix (4 fichiers)**.
Omettre `siwis` laisserait le narrateur muet dès la 1re réplique contenant un
`*geste*` — même forme que les bugs `_MEIPASS`/tempfile : démarre bien, casse à
un usage particulier. La spec liste donc explicitement tom + siwis (+ leurs
`.json`).

## Architecture du packaging

### Layout `_MEIPASS` (contrat, déjà attendu par le code)
À la racine du bundle, la spec DOIT poser :
```
<bundle>/
  quest-reader[.exe]         # exécutable
  tesseract[.exe]            # binaire OCR
  tessdata/fra.traineddata   # données de langue FR
  piper-voices/
    fr_FR-tom-medium.onnx    + .json
    fr_FR-siwis-medium.onnx  + .json
  <libs natives de tesseract> (leptonica, png, jpeg, tiff, webp, …)
```
Sans ce layout : l'exe démarre mais reste sans OCR / sans voix.

### Fichiers à créer
- **`packaging/quest-reader.spec`** — spec PyInstaller unique, paramétrée par
  `sys.platform` (une seule source, comportement par OS à l'intérieur).
  - `datas` : `tessdata/`, `piper-voices/` (les 4 fichiers), à la racine.
  - `binaries` : `tesseract[.exe]` + ses `.so`/`.dll` (résolues via `ldd` sur
    Linux, via le dossier d'install choco sur Windows).
  - `mode onedir`, nom `quest-reader`.
- **`packaging/hook-tesseract-libs.py`** — **runtime-hook** (exécuté AVANT le
  code applicatif) : pose `LD_LIBRARY_PATH` (Linux) / `PATH` (Windows) vers
  `sys._MEIPASS` pour que le process tesseract externe trouve ses libs.
  N'a rien à faire pour gi/gst (prérequis système).
- **`.github/workflows/build-release.yml`** — déclencheur `push: tags: v*`
  **+ `workflow_dispatch`**. Matrice ubuntu + windows. Chaque job : installe
  tesseract+fra (comme le workflow de tests), installe la voix FR par défaut,
  `pip install -e ".[build]"`, `pyinstaller packaging/quest-reader.spec`,
  vérifie le bundle sous env scrubbé, uploade l'artefact, l'attache à la
  Release (sur tag).

## Séquence d'implémentation (contrainte : PyInstaller tourne sur l'OS cible)

**Linux d'abord, en local, itératif** (build en secondes, OS le plus dur) ;
Windows ensuite via CI (feedback lent 3–4 min).

1. **Spec Linux minimale** → build → run `--test` sur une vraie capture sous
   env scrubbé → corriger (surtout : tesseract trouve ses libs + fra ; Piper
   charge les 2 voix). Itérer jusqu'au vert.
2. **Généraliser la spec** aux deux OS (branches `sys.platform`) une fois la
   structure Linux éprouvée — pas avant (ce que Linux force reshape la
   structure commune).
3. **Workflow build-release** avec la matrice, testé via `workflow_dispatch`
   (pas besoin de tag pour itérer).
4. **Validation utilisateur** : exe Linux sur machine sans dev ; exe Windows
   en jeu.

## Vérification (mappe les critères du plan)

1. **Suite complète verte** après tout changement de code de résolution (mais
   la Phase 4 touche surtout des fichiers de packaging, peu de code Python).
2. **Bundle sous env scrubbé** : `env -i ./dist/quest-reader/quest-reader
   --test <capture réelle>` — même esprit que le proxy `sitecustomize` qui a
   attrapé le couplage gi/dbus : seul signal LOCAL que le bundle n'emprunte pas
   les libs de la machine de dev. Le chemin `--test` exerce tesseract+tessdata
   sans lancer le jeu.
3. **CI build** verte sur les 2 OS (`workflow_dispatch`).
4. **En jeu** : exe Windows lit un dialogue (capture mss) ; exe Linux lit un
   dialogue (portail, prérequis système présents).

## Hors périmètre (ce lot)

- **Exe macOS** (bloqueurs TCC/signature/notarisation ; compat code préservée).
- **Freeze de la pile GStreamer/gi Linux** (prérequis système assumé).
- **Signature/notarisation Windows** (usage perso, non requise).
- **Embarquer toutes les voix** (une voix FR par défaut ; externes via chemin
  absolu, cf. limite `_racine_donnees`).

## Limites connues à documenter côté utilisateur

- Exe Linux : suppose gi/GStreamer/PipeWire système (paquets distro).
- Voix externe dans l'exe : uniquement via `--voice /chemin/absolu.onnx`
  (déposer dans `user_data_dir` est ignoré une fois figé).
- Windows mono-écran : bouton ⟳ (re-sélection) inerte (dégradation Phase 3).
