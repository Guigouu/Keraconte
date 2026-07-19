# Quest Reader

Lit à voix haute les dialogues de PNJ de Dofus, en français.

Le programme observe l'écran en continu, repère la bulle de dialogue,
en extrait le texte et le prononce. Aucune sélection manuelle : il suffit
de parler à un PNJ.

## Installation

Testé sur CachyOS / KDE Plasma en Wayland.

```bash
sudo pacman -S --needed tesseract tesseract-data-fra
python -m venv --system-site-packages .venv
.venv/bin/pip install numpy opencv-python-headless pytesseract piper-tts

mkdir -p ~/.local/share/piper-voices && cd ~/.local/share/piper-voices
python -m piper.download_voices fr_FR-tom-medium fr_FR-siwis-medium
```

Le `--system-site-packages` est nécessaire : la capture d'écran passe par
`python-gobject` et `gst-plugin-pipewire`, fournis par la distribution.

## Utilisation

```bash
.venv/bin/python quest_reader.py
```

Au premier lancement, KDE demande quel écran partager. L'autorisation est
mémorisée : les lancements suivants démarrent sans rien demander.

Options utiles :

| Option | Effet | Défaut |
|---|---|---|
| `--engine` | moteur de synthèse : `piper` ou `kokoro` | `piper` |
| `--voice` | voix du PNJ (piper) | `fr_FR-tom-medium` |
| `--narration-voice` | voix des didascalies (piper) | `fr_FR-siwis-medium` |
| `--speed` | durée de la parole : au-dessus de 1, plus lent | `1.05` |
| `--pause` | silence entre deux phrases, en ms (piper) | `320` |
| `--fps` | images analysées par seconde | `2` |
| `--repeat-after` | délai avant de relire un dialogue identique | `30` s |
| `--test IMAGE` | teste la détection sur une capture, sans lecture | — |

### Deux moteurs

Aucun des deux ne l'emporte partout : à essayer selon ce qu'on préfère
entendre.

| | Piper (défaut) | Kokoro |
|---|---|---|
| Voix | masculine | féminine — seule voix FR du modèle |
| Latence (CPU) | 0,26 s | 1,51 s |
| Modèle | 63 Mo | 310 Mo |
| Ponctuation | pauses ajoutées par le programme | respectée nativement |
| Timbre | plus naturel | un peu robotique |

```bash
.venv/bin/python quest_reader.py --engine kokoro
```

Kokoro tourne sur le processeur, à dessein : la carte graphique reste
disponible pour le jeu.

Installation, si l'on veut l'essayer :

```bash
.venv/bin/pip install kokoro-onnx soundfile
mkdir -p ~/.local/share/kokoro && cd ~/.local/share/kokoro
base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
curl -L -o kokoro.onnx $base/kokoro-v1.0.onnx
curl -L -o voices.bin $base/voices-v1.0.bin
```

### Deux voix

Les actions écrites entre astérisques — `* se racle la gorge *` — sont dites
autrement que la parole du PNJ : par une seconde voix avec Piper, et par un
débit ralenti avec Kokoro, qui n'a qu'une voix française.

### Onomatopées

Sans voyelle, les synthétiseurs épellent : « Pssst » sort en « p-s-s-s-t ».
Une table de réécriture corrige la prononciation avant la synthèse. Le texte
affiché, lui, reste celui du jeu.

## Fonctionnement

1. **Capture** — le portail `ScreenCast` ouvre un flux PipeWire. C'est la
   seule voie utilisable en continu sur Wayland : `spectacle` vole le focus
   à chaque appel, et l'API `KWin.ScreenShot2` refuse les scripts.
2. **Détection** — la bulle est un aplat gris neutre, alors que le décor du
   jeu est coloré. On la repère par l'écart entre canaux RVB.
3. **Validation** — un dialogue de PNJ est toujours suivi d'un bloc de
   réponses aligné juste en dessous. Sans cette paire, rien n'est lu : c'est
   ce qui écarte les menus, tooltips et fenêtres d'interface.
4. **Lecture** — OCR par Tesseract, puis synthèse vocale par pyttsx3 dans un
   fil séparé, pour ne pas bloquer la capture.

Seul le dialogue est lu. Les réponses proposées au joueur servent à
confirmer qu'il s'agit d'un dialogue, mais ne sont pas prononcées.

Un même dialogue n'est lu qu'une fois : l'OCR laisse des caractères
parasites variables autour du texte, donc la comparaison porte sur une
empreinte tolérante plutôt que sur le texte exact.

## Tests

```bash
.venv/bin/python -m pytest tests/
```

Les tests s'appuient sur de vraies captures du jeu (`tests/fixtures/`). Les
cas négatifs sont produits en masquant une zone d'une capture réelle, de
sorte que les couleurs du jeu restent autour.

## Limites connues

- Réglé sur le thème sombre par défaut de Dofus. Un thème clair changerait
  les seuils de `find_dialog`.
- Le nom du PNJ n'est pas lu (il est sur un parchemin doré, dont l'aspect
  varie selon le PNJ).
- La détection n'a été validée que sur deux captures. D'autres dispositions
  de dialogue peuvent demander des ajustements.
