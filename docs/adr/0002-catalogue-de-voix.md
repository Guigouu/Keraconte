# ADR-0002 — Élargir le catalogue de voix et gagner en naturel

- **Statut** : Proposé
- **Date** : 2026-08-03

## Contexte et problème

Le catalogue vocal effectif est étroit :

| Moteur | Voix françaises disponibles | Matériel |
|---|---|---|
| Piper (défaut) | 2 embarquées : `tom` (PNJ), `siwis` (narration) | CPU |
| Kokoro | 1 seule dans le modèle (`ff_siwis`) | CPU |
| XTTS-v2 | 58 voix nommées + clonage d'échantillon | **CUDA obligatoire** |

Deux besoins poussent à l'élargir :

1. **L'ADR-0001** (voix selon le genre du PNJ) exige, par moteur, une voix
   masculine et une voix féminine de *dialogue*, distinctes de la voix de
   *narration*. Aujourd'hui Piper n'a que deux voix embarquées : affecter
   `siwis` aux PNJ féminins la ferait entrer en collision avec les
   didascalies — les deux canaux deviendraient indistinguables à l'oreille,
   ce qui est précisément ce que la seconde voix devait empêcher.
2. **Le naturel.** Le README l'assume : « aucun [moteur] ne l'emporte
   partout ». Piper est rapide mais marque mal la ponctuation (pauses
   ajoutées par le programme) ; Kokoro est « un peu robotique » ; le timbre
   le plus naturel (XTTS) est enfermé derrière CUDA, donc inaccessible à qui
   joue sans carte NVIDIA — le cas visé par l'exécutable autonome.

Contraintes non négociables, héritées du projet : fonctionnement
**hors-ligne** (l'écran capturé ne sort pas de la machine, pas de coût
récurrent, pas de latence réseau), **CPU par défaut** (la carte graphique
appartient au jeu), licences compatibles avec une redistribution
non commerciale (PolyForm NC).

## Décision

Trois volets, du plus court au plus long terme. Le volet 1 suffit à
débloquer l'ADR-0001 ; les volets 2–3 traitent le naturel.

### 1. Élargir le catalogue Piper (court terme, CPU)

Le dépôt canonique `rhasspy/piper-voices` fournit d'autres voix françaises
que les deux embarquées : `upmc` (medium, **multi-locuteurs** : jessica —
féminine — et pierre — masculin), `gilles` (low), `mls` (medium), `siwis`
(low). Décision :

- **Affectation des canaux par défaut** (vocabulaire de l'ADR-0001) :
  `pnj_masculin` = `tom` (inchangé), `pnj_feminin` = `upmc`/jessica (à
  valider à l'oreille contre `siwis-low` avant de figer), `narration` =
  `siwis-medium` (inchangée). Règle générale : **jamais la même voix sur
  deux canaux**.
- **`--list-voices`** : lister les voix trouvées dans le dossier de voix
  (nom, genre déclaré, locuteurs pour les modèles multi-locuteurs), pour que
  l'utilisateur découvre ce qu'il peut passer à `--voice` /
  `--narration-voice` sans fouiller le disque.
- Les options `--voice` existantes restent le mécanisme de personnalisation :
  ce volet élargit ce qu'on peut y mettre et ce qui est embarqué, il ne crée
  pas de nouveau système de configuration.

**Point de validation avant d'engager le code** : le support des modèles
multi-locuteurs (sélection du `speaker_id`) par l'API `piper-tts` utilisée
(`PiperVoice`/`SynthesisConfig`, ≥ 1.5). S'il manque, `upmc` est remplacée
par la meilleure voix féminine mono-locuteur du catalogue, et la décision
d'affectation est mise à jour ici même.

### 2. Un banc d'essai standard, porte d'entrée de tout nouveau moteur

Le naturel ne s'obtiendra pas en empilant des moteurs au jugé : chaque
candidat passe le **même banc** que XTTS a passé
(`plans/moteur-xtts-et-genre.md`) — les trois répliques de référence
(« Bienvenue ! », Klako 86 car., Oto Mustam 171 car.), sur la machine de
calibration, Dofus lancé. Mesures : ratio synthèse/parole, latence de
première phrase, chargement du modèle, RAM/VRAM, poids sur disque.

**Critères d'admission d'un moteur CPU** (tous chiffrés, tous mesurés) :

- ratio synthèse/parole **< 0,8×** sur le CPU de calibration, jeu lancé —
  au-delà, la voix prend du retard sur le jeu et l'expérience se dégrade ;
- chargement du modèle **< 15 s** (le fil `Speaker` absorbe le chargement,
  mais 83 s à la XTTS ne sont acceptables que pour un moteur optionnel) ;
- français **natif** (pas une voix anglaise qui lit du français) ;
- **≥ 2 voix françaises** ou clonage, pour servir les canaux de l'ADR-0001 ;
- hors-ligne, licence compatible redistribution non commerciale ;
- contrat `Engine` inchangé (découpage par phrases, `speakable`, générations).

Candidats identifiés, **dans l'ordre de passage au banc** — aucun n'est
adopté par cette ADR, qui fixe la porte, pas le lauréat :

| Candidat | Pour | Contre / à vérifier |
|---|---|---|
| Chatterbox Multilingual (Resemble AI, MIT) | naturel élevé, 23 langues dont le français, clonage | latence CPU incertaine (~0,5 G paramètres) : c'est LA mesure qui décide |
| MeloTTS (MIT) | français, temps réel CPU annoncé | timbre à comparer à Piper : s'il ne fait pas mieux, il n'apporte rien |
| Kyutai TTS | français natif excellent, streaming | GPU en pratique : même niche que XTTS, à ne considérer que si XTTS décroche |

Un candidat recalé l'est **avec ses mesures**, consignées ici — même
discipline que l'abandon documenté de la détection de genre.

### 3. XTTS reste la voie « naturel maximal », assumée GPU

Rien de nouveau côté moteur. Deux compléments de documentation seulement :
les voix nommées se choisissent déjà par canal (`Damien Black` /
`Sofia Hellen` câblées) — l'étendre au canal féminin de l'ADR-0001 est un
choix de nom, pas du code ; et le clonage par échantillon WAV reste l'option
« voix sur mesure » pour qui a la carte.

## Options rejetées

- **TTS en ligne** (ElevenLabs, OpenAI, Azure…) : rejet net. L'outil capture
  l'écran en continu — envoyer quoi que ce soit à un tiers change la nature
  du programme ; s'ajoutent la latence réseau, le coût récurrent et des
  conditions d'usage incompatibles avec un outil libre non commercial.
- **Embarquer tout le catalogue dans l'exécutable** : chaque voix Piper pèse
  60–75 Mo ; le bundle par défaut reste à trois voix (les trois canaux), le
  reste se télécharge — commande documentée au README, comme aujourd'hui.
- **Rendre Kokoro multi-voix** : le modèle n'a qu'une voix française ;
  contrainte amont, rien à décider ici.
- **Pitch-shift d'une voix existante** pour fabriquer le canal manquant :
  rendu artificiel notoire, et le volet 1 fournit de vraies voix pour moins
  cher.

## Critères d'acceptation

- **Volet 1** : sur la réplique du smoke test (`--dire` avec didascalie),
  les trois canaux rendent trois voix distinctes à l'oreille ; la latence
  Piper reste ~0,26 s ; le bundle ne grossit pas de plus de ~80 Mo (une voix
  de plus) ; spec PyInstaller (`VOIX_DEFAUT`) et workflow de release étendus
  en conséquence, smoke test de l'exe figé couvrant les **trois** voix.
- **Volet 2** : le banc est rejouable (procédure ou script versionné) ; le
  tableau comparatif des moteurs du README devient la *sortie* du banc, pas
  une prose entretenue à part.

## Conséquences

- `packaging/keraconte.spec` (`VOIX_DEFAUT`) et `build-release.yml` (liste
  `VOIX`) gagnent la voix du canal féminin ; le README documente le
  téléchargement des voix optionnelles.
- L'ADR-0001 devient réalisable pour Piper et XTTS ; Kokoro reste
  documenté comme mono-voix.
- Tout futur débat « ce moteur est mieux » a désormais un terrain : le banc
  et ses seuils, ici. Les changer se fait en changeant cette ADR.

## Références

- README, tableau « Trois moteurs » (latences et poids mesurés).
- `plans/moteur-xtts-et-genre.md` (banc d'essai d'origine, mesures XTTS).
- `packaging/keraconte.spec` (`VOIX_DEFAUT`), `.github/workflows/build-release.yml`.
- ADR-0001 (canaux de voix : `pnj_masculin`, `pnj_feminin`, `narration`).
