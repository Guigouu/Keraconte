# Moteur XTTS-v2

## Ce qui est mesuré

Banc d'essai réel sur cette machine (RTX 3070 Ti, Dofus lancé).

| Réplique | Synthèse | Audio | Ratio |
|---|---|---|---|
| « Bienvenue ! » | 0,26 s | 1,15 s | 0,22× |
| Klako (86 car.) | 1,44 s | 6,11 s | 0,24× |
| Oto Mustam (171 car.) | 2,50 s | 10,48 s | 0,24× |

- **VRAM** : 1,96 Go au pic, sur ~5 Go libres jeu lancé.
- **Chargement du modèle** : 83 s au premier démarrage.
- Ratio 0,24× : la synthèse va 4× plus vite que la parole. En découpant par
  phrases, le son démarre presque aussitôt.

## Pourquoi il n'y a pas de détection de genre

La feature a été abandonnée sur mesure, pas sur intuition :

- **Table par nom de PNJ : impossible.** L'OCR du cartouche rend « Klako »
  en `R ÉN A` et « Sotsiah Peh » en `n l C DR`. Ratios difflib au vrai nom :
  0,11 à 0,24, là où un rapprochement fiable en demande 0,9.
- **Accords dans le texte : muets.** La détection en première personne
  fonctionne (« je suis venue », « je suis la gardienne ») et évite le piège
  « tu es venue » qui vise le joueur. Mais **aucun** des quatre dialogues
  réels des fixtures n'en contient : les PNJ disent « Je suis Klako,
  chasseur », où le métier porte le genre, pas la grammaire.

Conclusion : presque tous les PNJ auraient reçu la voix par défaut. La
distinction homme/femme est hors périmètre tant qu'aucune source fiable
n'existe.

## Contrainte d'installation, vérifiée

Coqui TTS n'est pas compatible d'origine avec Python 3.14 :

1. `torch` depuis l'index PyPI par défaut (2.13.0+cu130). L'index
   `download.pytorch.org/whl/cu124` n'a **rien** pour 3.14.
2. `torchaudio` n'est pas tiré automatiquement.
3. `coqui-tts[codec]` est requis, sinon le chargement échoue.
4. **Rustine obligatoire, à placer dans le code livré** (pas seulement dans
   un script de test) : `TTS/tts/layers/tortoise/autoregressive.py` importe
   `isin_mps_friendly`, retiré de `transformers` 5.x. XTTS ne s'en sert pas,
   mais le module est importé au chargement.

```python
import torch, transformers.pytorch_utils as pu
if not hasattr(pu, "isin_mps_friendly"):
    pu.isin_mps_friendly = lambda elements, test_elements: torch.isin(
        elements, test_elements
    )
```

La signature compte : ces arguments sont passés par mot-clé.

## Le travail

Un seul bloc cohérent : tout touche au routage vocal. **Un seul agent.**

Ajouter `XttsEngine` à côté de `PiperEngine` et `KokoroEngine`, activé par
`--engine xtts`. Contrat inchangé : `speak(text, narration)` — aucune
signature n'est modifiée, puisqu'il n'y a pas de genre à faire circuler.

- Le modèle se charge **dans le thread `Speaker`**, comme les autres : 83 s
  ne doivent pas bloquer la capture d'écran. `Speaker` construit déjà son
  moteur lui-même, ce point est acquis.
- Découper par phrases via `split_sentences`, comme `PiperEngine` : c'est ce
  qui rend la latence imperceptible. Ne pas synthétiser le bloc entier.
- Deux voix de référence, en WAV : `--voice-sample` pour le PNJ,
  `--narration-sample` pour les didascalies. Sans elles, `--engine xtts`
  doit échouer avec un message clair, jamais planter.
- Appeler `speakable` avant chaque synthèse : un segment vide fait planter
  les moteurs (bug déjà rencontré et corrigé sur Kokoro).
- Si CUDA est indisponible, dire pourquoi et s'arrêter : le ratio en CPU
  serait environ 10× pire, donc inutilisable en jeu.

## Validation

- Les 127 tests existants passent sans modification.
- Le moteur se construit sans charger le modèle quand c'est testable
  (mock), pour que la suite reste rapide.
- Test du repli : sans fichier de voix, message clair et pas de trace.
- Vérification manuelle : synthétiser les trois répliques du banc d'essai.

## Hors périmètre

- Ne pas toucher à `clean`, `find_dialog`, `keep_word`, `drop_replies`,
  `reads_like_dialogue` : la détection vient d'être refondue et validée.
- Ne pas changer le moteur par défaut. `piper` reste le défaut tant que
  l'utilisateur n'a pas validé le rendu XTTS en jeu.
- Ne pas installer XTTS dans le venv du projet : ~3 Go. Documenter la
  commande dans le README, laisser l'utilisateur décider.
