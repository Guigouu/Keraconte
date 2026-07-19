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
.venv/bin/pip install numpy opencv-python-headless pytesseract pyttsx3
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
| `--rate` | vitesse de lecture | `165` |
| `--voice` | voix espeak-ng | `roa/fr` |
| `--fps` | images analysées par seconde | `2` |
| `--repeat-after` | délai avant de relire un dialogue identique | `30` s |
| `--test IMAGE` | teste la détection sur une capture, sans lecture | — |

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
