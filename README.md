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
| `--engine` | moteur de synthèse : `piper`, `kokoro` ou `xtts` | `piper` |
| `--voice` | voix du PNJ (piper) | `fr_FR-tom-medium` |
| `--narration-voice` | voix des didascalies (piper) | `fr_FR-siwis-medium` |
| `--voice-sample` | extrait WAV de la voix du PNJ à cloner (xtts) | — |
| `--narration-sample` | extrait WAV de la voix des didascalies (xtts) | — |
| `--speed` | débit de la parole : au-dessus de 1, plus rapide | `1.22` |
| `--pause` | silence entre deux phrases, en ms (piper) | `320` |
| `--fps` | images analysées par seconde | `2` |
| `--repeat-after` | délai avant de relire un dialogue identique | `30` s |
| `--test IMAGE` | teste la détection sur une capture, sans lecture | — |

### Trois moteurs

Aucun ne l'emporte partout : à essayer selon ce qu'on préfère entendre.

| | Piper (défaut) | Kokoro | XTTS-v2 |
|---|---|---|---|
| Voix | masculine | féminine — seule voix FR du modèle | clonées, au choix |
| Matériel | processeur | processeur | carte graphique |
| Latence | 0,26 s | 1,51 s | 0,26 s (1re phrase) |
| Modèle | 63 Mo | 310 Mo | ~1,8 Go |
| Ponctuation | pauses ajoutées par le programme | respectée nativement | respectée nativement |
| Timbre | plus naturel | un peu robotique | le plus naturel |

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

### XTTS-v2 : voix clonées

XTTS reproduit la voix d'un extrait WAV qu'on lui fournit — quelques
secondes de parole claire suffisent. Deux extraits sont exigés : l'un pour
le PNJ, l'autre pour les didascalies.

```bash
.venv/bin/python quest_reader.py --engine xtts \
  --voice-sample ~/voix/pnj.wav --narration-sample ~/voix/didascalies.wav
```

Mesuré sur RTX 3070 Ti, Dofus lancé : ratio 0,24× — la synthèse va quatre
fois plus vite que la parole — pour 1,75 Go de VRAM sur les ~5 Go que le jeu
laisse libres. Compter aussi **4,7 Go de mémoire vive**, stables : douze
répliques d'affilée n'y ajoutent rien. Le chargement du modèle prend 83 s,
une seule fois au démarrage, dans le fil de synthèse : la capture d'écran
n'attend pas. Comme avec Piper, le texte est découpé par phrases, si bien
que le son commence avant que le bloc entier soit synthétisé.

Pendant ces 83 s, rien n'est dépilé. La file de lecture est donc bornée à
deux dialogues : au-delà, les plus anciens sont ignorés — ils ne
correspondent plus à ce qui est à l'écran — et le programme le signale.
Sans cette borne, une longue session remplissait la mémoire de la machine.

CUDA est exigé : sur processeur le ratio serait environ dix fois pire, donc
la synthèse durerait plus longtemps que la réplique à dire. Sans carte
compatible, le programme le dit et s'arrête.

Installation. Coqui TTS n'est pas compatible d'origine avec Python 3.14, et
quatre contraintes en découlent :

```bash
# 1. torch depuis l'index PyPI par défaut : l'index cu124 de PyTorch n'a
#    rien pour Python 3.14.
# 2. torchaudio n'est pas tiré automatiquement, il faut le nommer.
# 3. l'extra [codec] est requis, sinon le chargement du modèle échoue.
python -m venv .venv-xtts
.venv-xtts/bin/pip install torch torchaudio 'coqui-tts[codec]'
```

4. Une rustine est nécessaire, et elle vit dans le code livré
   (`XttsEngine.__init__`) : Coqui importe `isin_mps_friendly`, retiré de
   `transformers` en 5.x. XTTS ne s'en sert pas, mais le module fautif est
   chargé au passage — sans la rustine, `from TTS.api import TTS` lève.

Le modèle (~1,8 Go) se télécharge au premier lancement dans
`~/.local/share/tts`, après acceptation de la licence : `COQUI_TOS_AGREED=1`
l'accepte d'avance.

Cette pile pèse environ 3 Go : elle est délibérément tenue hors du venv du
projet, qui ne dépend pas de torch.

### Pas de détection du genre du PNJ

La voix ne s'adapte pas au genre du personnage, faute de source fiable :
l'OCR du cartouche rend « Klako » en `R ÉN A`, avec des ratios de
rapprochement de 0,11 à 0,24 là où il en faudrait 0,9 ; et les accords dans
le texte sont muets, les PNJ disant « Je suis Klako, chasseur », où c'est le
métier qui porte le genre, pas la grammaire.

### Deux voix

Les actions écrites entre astérisques — `* se racle la gorge *` — sont dites
autrement que la parole du PNJ : par une seconde voix avec Piper et XTTS, et
par un débit ralenti avec Kokoro, qui n'a qu'une voix française.

### Onomatopées

Sans voyelle, les synthétiseurs épellent : « Pssst » sort en « p-s-s-s-t ».
Une table de réécriture corrige la prononciation avant la synthèse. Le texte
affiché, lui, reste celui du jeu.

## Fonctionnement

1. **Capture** — le portail `ScreenCast` ouvre un flux PipeWire. C'est la
   seule voie utilisable en continu sur Wayland : `spectacle` vole le focus
   à chaque appel, et l'API `KWin.ScreenShot2` refuse les scripts.
2. **Détection** — deux habillages de bulle sont reconnus. Sur le thème
   sombre d'origine, la bulle est un aplat gris neutre que le décor coloré
   n'imite pas : l'écart entre canaux RVB suffit. Sur le thème bleu, cet
   écart monte à 23 quand le bois du décor est à 47, donc c'est la teinte
   qui tranche — bulle à 117, décor sous 28.
3. **Validation** — un dialogue de PNJ est toujours suivi d'un bloc de
   réponses aligné juste en dessous. Sans cette paire, rien n'est lu : c'est
   ce qui écarte les menus, tooltips et fenêtres d'interface.
4. **Lecture** — OCR par Tesseract, puis synthèse vocale par pyttsx3 dans un
   fil séparé, pour ne pas bloquer la capture.

Seul le dialogue est lu. Les réponses proposées au joueur servent à
confirmer qu'il s'agit d'un dialogue, mais ne sont pas prononcées.

Fermer la fenêtre coupe la voix aussitôt, au milieu du mot s'il le faut :
la lecture se cale sur ce qui est à l'écran. La bulle doit avoir disparu de
trois images d'affilée — une seconde et demie à `--fps 2` — car elle
s'éclipse parfois le temps d'une image sans que rien ait été fermé.

C'est bien la disparition de la bulle qui est guettée, pas l'échec de la
lecture : l'OCR ne rend souvent rien d'une bulle pourtant affichée, et
couper là-dessus arrêtait la voix en plein milieu d'une réplique inchangée.

Un même dialogue n'est lu qu'une fois : l'OCR laisse des caractères
parasites variables autour du texte, donc la comparaison porte sur une
empreinte tolérante plutôt que sur le texte exact.

Dofus écrit ses répliques progressivement, et l'OCR les saisit en chemin.
La lecture attend donc une image où le texte n'a plus grandi — sans quoi
chaque état intermédiaire passait pour une réplique neuve, et la fin de la
phrase n'était jamais dite.

Deux lectures d'une même bulle se comparent sur leur vocabulaire, non sur
leur suite de caractères : l'OCR permute parfois les lignes, ce qui fait
chuter la ressemblance de séquence à 0,74 sans qu'un seul mot ait changé.
Entre les variantes retenues, celle qui s'écarte nettement des autres est
écartée — elle porte un bloc de réponses que la géométrie a laissé passer.

## Tests

```bash
.venv/bin/python -m pytest tests/
```

Les tests s'appuient sur de vraies captures du jeu (`tests/fixtures/`). Les
cas négatifs sont produits en masquant une zone d'une capture réelle, de
sorte que les couleurs du jeu restent autour.

## Limites connues

- Réglé sur les thèmes sombre et bleu de Dofus. Un thème clair changerait
  les seuils de `find_dialog` : la bulle y serait plus lumineuse que les
  bornes de `value` ne l'admettent.
- Le nom du PNJ n'est pas lu (il est sur un parchemin doré, dont l'aspect
  varie selon le PNJ).
- La détection n'a été validée que sur deux captures. D'autres dispositions
  de dialogue peuvent demander des ajustements.
