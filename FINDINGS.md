# Quest Reader — résultats de validation (Dofus)

Environnement : CachyOS, KDE Plasma, **Wayland natif**, Python 3.14, venv `--system-site-packages`.

## Validé sur capture réelle (`sample.png`, 2560×1350)

### OCR — fonctionne sans prétraitement
Tesseract `-l fra` lit le texte de bulle parfaitement en brut, accents inclus :
> "C'est moi le plus grand, le plus magique, le plus doué des forgemages du monde."

- Upscale 2× **dégrade** légèrement → ne pas prétraiter le corps de bulle.
- Nom du PNJ (parchemin doré) : nécessite upscale **4× + `--psm 6`** → `| Sotsiah Peh i` (nettoyer bruit de bordure).

### Détection de la bulle — par neutralité colorimétrique
La bulle est un aplat **gris neutre** ; le décor Dofus est coloré. Discriminant fiable :

```python
spread = max(B,G,R) - min(B,G,R)      # bulle: mean 0.2, p90 0.0
masque = (spread < 12) & (18 < V < 75) # 90% couverture dans bulle, 20% global
```

Morphologie : `OPEN 9×9` puis `CLOSE 41×41`.
Filtres forme : `aire > 80000`, `w > 300`, exclure `y+h > H*0.92` (chat) et `x+w > W*0.97` (UI droite).

**Ne pas** filtrer sur `fill ratio` (la queue de bulle le casse : 0.62).

Validation du candidat : ratio de blanc dans `[0.8 %, 15 %]` puis `len(texte) > 20`.
Faux positif écarté nettement — texte blanc 2.94 % vs 0.1 %.

### Signature décisive : la paire dialogue + réponses
Trop de faux positifs en jeu réel avec le seul bloc supérieur. Un dialogue de
PNJ est **toujours** suivi d'un bloc de réponses ; les panneaux d'interface
sont isolés. On exige donc la paire, et on lit le bloc du haut.

Géométrie mesurée : dialogue `xywh (1121,494,673,264)`, réponses
`(1122,742,614,88)` → écart vertical **-16 px** (léger chevauchement, d'où
`MAX_REPLY_OVERLAP`), bords gauches alignés à 1 px, largeurs à 9 %.

Cas de test vérifiés : dialogue nominal lu ; bulle masquée → `None` ;
bloc de réponses masqué → `None`.

### Non confirmé : teinte dorée des réponses
Le bloc de réponses est décrit comme jaune/doré. Mesuré sur les deux captures,
il est **gris neutre** : `sample.png` S médian 0, BGR 40/41/42 ; `sample2.png`
S médian 9, BGR 70/70/72 (simplement plus clair que la bulle, V 55 vs 31).
Le doré vient probablement du parchemin du nom au-dessus, ou du survol souris.
Aucune signature couleur codée tant qu'elle n'est pas mesurée.

### Réglages issus de la 2e capture (`sample2.png`, PNJ Tokageko)
- `CLOSE` ramené de 15 à **7** : à 9 et au-delà, bulle et réponses fusionnent
  quand l'écart est serré. 7 sépare correctement sur les deux captures.
- Filtre anti-chat (`y+h > H*0.92`) **supprimé** : il rejetait le dialogue sur
  une capture recadrée, et l'exigence de paire écarte déjà le chat.
- Icônes ⋮ et ✕ des coins de bulle : rognage `MARGIN = 34` **plus** nettoyage
  des fragments sans lettre en tête/queue dans `clean()`.

### État des tests (`--test`)
| Cas | Attendu | Résultat |
|---|---|---|
| `sample.png` | dialogue | texte exact, sans parasite |
| `sample2.png` | dialogue | texte exact, sans parasite |
| bulle masquée | `None` | `None` |
| réponses masquées | `None` | `None` |
| chat seul | `None` | `None` |

Non encore vérifié en conditions réelles : chemin portal + PipeWire, et la
suppression du sélecteur au second lancement (`restore_token`).

## Bloquant restant : capture continue Wayland

- `org.kde.KWin.ScreenShot2` **existe** (v5, `CaptureArea`) mais renvoie
  `Error.NoAuthorized` pour un script Python — KWin whitelist par chemin binaire.
- `spectacle` en boucle : fonctionne mais vole le focus KDE → inutilisable en continu.
- **Voie retenue** : portal `org.freedesktop.portal.ScreenCast` + PipeWire.
  - `persist_mode=2` + `restore_token` → autorisation une seule fois.
  - `gst-plugin-pipewire` et `python-gobject` déjà présents.
  - Throttle OCR à 1–2 Hz ; hash du texte pour ne pas relire en boucle.

## Dépendances
- pacman : `tesseract`, `tesseract-data-fra`
- venv : `numpy`, `opencv-python-headless`, `pytesseract`, `pyttsx3`
- TTS : pyttsx3 + espeak-ng, voix `roa/fr` — testé OK.
