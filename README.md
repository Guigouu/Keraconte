# Kéraconte

Lit à voix haute les dialogues de PNJ de Dofus, en français.

Le programme observe l'écran en continu, repère la bulle de dialogue,
en extrait le texte et le prononce. Aucune sélection manuelle : il suffit
de parler à un PNJ.

## Installation

La capture d'écran dépend de la plateforme : sous Linux elle passe par le
portail `ScreenCast` + PipeWire + GStreamer ; sous Windows et macOS par `mss`.
Le reste — OCR, synthèse, overlay — est commun. Le backend est choisi
automatiquement selon le système.

### Linux (développé et testé sur CachyOS / KDE Plasma en Wayland)

```bash
sudo pacman -S --needed tesseract tesseract-data-fra
python -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[linux]'

mkdir -p ~/.local/share/piper-voices && cd ~/.local/share/piper-voices
python -m piper.download_voices fr_FR-tom-medium fr_FR-siwis-medium fr_FR-upmc-medium
```

Le `--system-site-packages` est nécessaire : `python-gobject` et
`gst-plugin-pipewire`, tirés par l'extra `[linux]`, s'appuient sur les
bibliothèques système de la distribution.

### Windows

Le backend de capture `mss` est inclus dans les dépendances de base ; il
n'y a pas d'extra à installer. Tesseract doit être présent : soit dans le
`PATH`, soit désigné par `--tesseract CHEMIN` ou la variable `QR_TESSERACT`
(l'installeur Windows standard n'ajoute rien au `PATH`).

### Exécutable autonome

Une spec PyInstaller (`packaging/keraconte.spec`, extra `[build]`) empaquette
tesseract, les données `fra` et les voix Piper dans un exécutable unique. Un
workflow GitHub Actions le construit pour Windows et Linux sur les tags `v*`
(ou à la demande via `workflow_dispatch`). Ces exécutables n'ont pas encore
été validés hors de l'environnement de développement.

## Utilisation

```bash
.venv/bin/python -m keraconte
```

Sous Linux, au premier lancement, KDE demande quel écran partager.
L'autorisation est mémorisée : les lancements suivants démarrent sans rien
demander.

Options utiles :

| Option | Effet | Défaut |
|---|---|---|
| `--engine` | moteur de synthèse : `piper`, `kokoro` ou `xtts` | `piper` |
| `--voice` | voix du PNJ masculin — et de l'inconnu (piper) | `fr_FR-tom-medium` |
| `--voice-feminine` | voix du PNJ féminin (piper) ; `chemin.onnx#locuteur` pour un modèle multi-locuteurs | `fr_FR-upmc-medium#jessica` |
| `--narration-voice` | voix des didascalies (piper) | `fr_FR-siwis-medium` |
| `--voice-sample` | voix du PNJ masculin : nom du modèle ou WAV à cloner (xtts) | `Damien Black` |
| `--feminine-sample` | voix du PNJ féminin : nom ou WAV (xtts) | `Ana Florence` |
| `--narration-sample` | voix des didascalies : nom ou WAV (xtts) | `Sofia Hellen` |
| `--list-voices` | lister les voix Piper installées et leurs locuteurs, puis quitter | — |
| `--speed` | débit de la parole : au-dessus de 1, plus rapide | `1.22` |
| `--pause` | silence entre deux phrases, en ms (piper) | `320` |
| `--fps` | images analysées par seconde | `4` |
| `--repeat-after` | délai avant de relire un dialogue identique | `30` s |
| `--test IMAGE` | teste la détection sur une capture, sans lecture | — |
| `--tesseract CHEMIN` | binaire tesseract (sinon `QR_TESSERACT`, puis le `PATH`) | — |
| `--dire TEXTE` | synthétise une phrase de test et quitte (contrôle du moteur) | — |

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
.venv/bin/python -m keraconte --engine kokoro
```

Kokoro tourne sur le processeur, à dessein : la carte graphique reste
disponible pour le jeu.

Installation, si l'on veut l'essayer :

```bash
.venv/bin/pip install -e '.[kokoro]'
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
.venv/bin/python -m keraconte --engine xtts \
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

### Voix selon le genre du PNJ

Quand un signal **sûr** établit le genre du personnage, la réplique part sur
la voix correspondante (masculine ou féminine) ; sans signal, rien ne change
— la voix par défaut, exactement comme avant. Une mauvaise voix étant pire
que pas d'adaptation, le doute vaut toujours abstention, et la voix ne change
jamais en cours de réplique (décision prise une fois, au lancement de la
lecture). Détail des signaux et mesures : `docs/adr/0001-voix-selon-genre-pnj.md`.

Trois signaux, en cascade :

1. **le lexique genré** en auto-désignation — « Je suis Klako, *chasseur* »,
   « je suis *la gardienne* » : c'est le métier ou le titre qui porte le
   genre, pas la grammaire ;
2. **les accords en première personne** — « je suis venue » (le « tu es
   venue », qui accorde le joueur, ne vote pas) ;
3. **une table locale optionnelle** `empreinte de réplique → genre`, générée
   hors ligne par `outils/generer_table_genre.py` depuis les données
   communautaires du jeu (champ `gender` des PNJ). Sans table, ce signal est
   simplement inerte — le programme ne fait AUCUNE requête réseau en jeu.

L'OCR du cartouche de nom, lui, reste écarté : mesuré, il rend « Klako » en
`R ÉN A` (ratios 0,11–0,24 là où il en faudrait 0,9). Kokoro n'a qu'une voix
française : il reste hors adaptation.

### Deux voix

Les actions écrites entre astérisques — `* se racle la gorge *` — sont dites
autrement que la parole du PNJ : par une seconde voix avec Piper et XTTS, et
par un débit ralenti avec Kokoro, qui n'a qu'une voix française.

### Onomatopées

Sans voyelle, les synthétiseurs épellent : « Pssst » sort en « p-s-s-s-t ».
Une table de réécriture corrige la prononciation avant la synthèse. Le texte
affiché, lui, reste celui du jeu.

## Fonctionnement

1. **Capture** — sous Linux, le portail `ScreenCast` ouvre un flux PipeWire.
   C'est la seule voie utilisable en continu sur Wayland : `spectacle` vole le
   focus à chaque appel, et l'API `KWin.ScreenShot2` refuse les scripts. Sous
   Windows et macOS, `mss` capture directement l'écran. Le backend est choisi
   selon la plateforme, mais tout ce qui suit reçoit la même image et ne
   dépend plus du système.
2. **Détection** — deux habillages de bulle sont reconnus. Sur le thème
   sombre d'origine, la bulle est un aplat gris neutre que le décor coloré
   n'imite pas : l'écart entre canaux RVB suffit. Sur le thème bleu, cet
   écart monte à 23 quand le bois du décor est à 47, donc c'est la teinte
   qui tranche — bulle à 117, décor sous 28.
3. **Validation** — un dialogue de PNJ est toujours suivi d'un bloc de
   réponses aligné juste en dessous. Sans cette paire, rien n'est lu : c'est
   ce qui écarte les menus, infobulles et fenêtres d'interface. La paire se
   reconnaît de trois façons : le bloc de réponses est un contour distinct
   sous la bulle ; ou une réponse tenant sur une seule ligne, retrouvée dans
   la bande sous la bulle ; ou, quand bulle et réponses se touchent au point
   de fondre en un seul contour, en re-segmentant ce contour. Un vrai bloc de
   réponses n'est jamais plus haut que la bulle qu'il suit, ni détaché d'elle :
   ces deux mesures écartent les panneaux qui, sans elles, imitaient la paire.
4. **Lecture** — OCR par Tesseract, puis synthèse vocale (Piper par défaut)
   dans un fil séparé, pour ne pas bloquer la capture.

Seul le dialogue est lu. Les réponses proposées au joueur servent à
confirmer qu'il s'agit d'un dialogue, mais ne sont pas prononcées.

Fermer la fenêtre coupe la voix aussitôt, au milieu du mot s'il le faut :
la lecture se cale sur ce qui est à l'écran. La bulle doit avoir disparu de
deux images d'affilée — une demi-seconde à `--fps 4` — car elle s'éclipse
parfois le temps d'une image sans que rien ait été fermé.

C'est bien la disparition de la bulle qui est guettée, pas l'échec de la
lecture : l'OCR ne rend souvent rien d'une bulle pourtant affichée, et
couper là-dessus arrêtait la voix en plein milieu d'une réplique inchangée.

Un même dialogue n'est lu qu'une fois : l'OCR laisse des caractères
parasites variables autour du texte, donc la comparaison porte sur une
empreinte tolérante plutôt que sur le texte exact.

Le jeu affiche la bulle d'un coup, mais l'OCR la saisit en chemin : une
image donne parfois une version tronquée (dernière ligne manquante) avant
la version complète. La lecture attend donc une image où le texte n'a plus
grandi — sans quoi chaque saisie partielle passait pour une réplique neuve,
et la fin de la phrase n'était jamais dite.

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

- **Configuration validée** : pour l'instant, la détection n'est éprouvée
  qu'avec la résolution de développement, le thème standard, une accessibilité
  à 100 % et une taille de texte « très grand ». Les registres de captures
  couvrent plusieurs thèmes de couleurs et confirment cette base, mais les
  autres résolutions, échelles d'accessibilité et tailles de police (au-dessus
  de « Petit ») restent à valider.
- **Seuils calibrés en pixels** : le seuil d'aire d'une bulle est absolu, calé
  sur la résolution de développement (bulle large de ~555-633 px). À une tout
  autre échelle de rendu, il faudrait le rendre relatif. Les autres seuils
  géométriques (écart bulle/réponse, alignement) suivent déjà la largeur de la
  bulle et ne dépendent pas de la résolution.
- **Thèmes** : réglé sur les thèmes sombre et bleu de Dofus. Un thème clair
  changerait les seuils de `find_dialog` : la bulle y serait plus lumineuse que
  les bornes de `value` ne l'admettent.
- **Panneau Recettes** : il est parfois lu comme une étiquette (« Galet Solaire
  150 ») faute de pouvoir le distinguer d'un dialogue par la seule géométrie ;
  le seul signal qui l'écartait dépend de la version de Tesseract et ne se
  transporte pas d'une installation à l'autre, donc il est laissé de côté.
- **Nom du PNJ** : non lu (il est sur un parchemin doré, dont l'aspect varie
  selon le PNJ).

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE.md). Le code est ouvert : chacun peut le
cloner, le forker, le modifier et proposer des contributions, pour tout usage
**non commercial** — usage personnel, projets amateurs, recherche, éducation,
associations. La seule chose interdite est d'en tirer un produit commercial ou
de le vendre. Ce n'est donc pas « open source » au sens strict de l'OSI (qui
exige d'autoriser aussi l'usage commercial), mais du *source-available*.

Kéraconte est un outil non officiel, sans lien avec Ankama ; « Dofus » est
une marque d'Ankama.
