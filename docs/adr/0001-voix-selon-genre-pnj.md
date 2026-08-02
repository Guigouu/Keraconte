# ADR-0001 — Adapter la voix au genre du PNJ

- **Statut** : Proposé
- **Date** : 2026-08-03

## Contexte et problème

Tous les PNJ parlent aujourd'hui d'une même voix (Piper : `fr_FR-tom-medium`,
masculine), quel que soit le personnage à l'écran. Une chasseuse de
dragodindes et un forgeron de Brâkmar sonnent pareil : pour un outil dont le
but est de faire *entendre* le jeu, c'est une perte d'incarnation nette.

La détection du genre a déjà été tentée, et **abandonnée sur mesure, pas sur
intuition** (README, « Pas de détection du genre du PNJ » ;
`plans/moteur-xtts-et-genre.md`) :

- **OCR du cartouche de nom** : le parchemin doré rend « Klako » en `R ÉN A`,
  « Sotsiah Peh » en `n l C DR`. Ratios difflib au vrai nom : 0,11 à 0,24,
  quand un rapprochement fiable en demande 0,9. Une table nom → genre était
  donc inalimentable.
- **Accords dans le texte** : la détection en première personne fonctionne
  (« je suis venue », « je suis la gardienne ») et évite le piège « tu es
  venue » qui vise le joueur — mais aucun des quatre dialogues alors en
  fixture n'en contenait. Les PNJ disent « Je suis Klako, chasseur », où
  c'est le métier qui porte le genre, pas la grammaire.

Trois choses ont changé depuis cette décision :

1. **Le registre de captures a grandi** : d'environ quatre dialogues à une
   trentaine de captures réelles versionnées (`tests/fixtures/dialogues/`,
   `themes/`, `echelle/`), couvrant dix thèmes et plusieurs échelles. C'est
   la base d'étalonnage (« samples ») sur laquelle toute détection doit être
   mesurée avant d'exister dans le code.
2. **Une recette d'OCR du cartouche existe** : FINDINGS.md documente que le
   nom sur parchemin sort lisible avec **upscale 4× + `--psm 6`**
   (« Sotsiah Peh » ressort dans `| Sotsiah Peh i`, bruit de bordure à
   nettoyer). Les ratios 0,11–0,24 mesurés au moment de l'abandon l'ont été
   sans ce prétraitement.
3. **Le rapprochement peut se faire sur vocabulaire fermé.** On ne cherche
   pas à *lire* le nom, mais à le *reconnaître* parmi une liste finie de PNJ
   connus. Sur vocabulaire fermé, le bon critère n'est pas un ratio absolu
   de 0,9 mais une **marge** : le meilleur candidat doit distancer nettement
   le deuxième. C'est plus tolérant au bruit d'OCR, et ça s'abstient de
   lui-même quand rien ne se détache.

Le mot « genre » désigne ici le rendu vocal du personnage — voix masculine ou
féminine — tel que le jeu le présente (nom, titre, accords) : c'est la seule
chose qu'un synthétiseur peut restituer.

## Décision

Adapter la voix du PNJ à son genre quand — et seulement quand — un signal
sûr l'établit. **L'abstention est le comportement par défaut** : en
l'absence de signal, la voix reste celle d'aujourd'hui, à l'identique. Une
mauvaise voix est pire que pas d'adaptation ; le critère d'acceptation
l'encode (zéro erreur tolérée, la couverture est la variable d'ajustement).

Trois signaux, du moins cher au plus cher, combinés en cascade :

1. **Lexique genré dans le texte de bulle** (déjà OCRisé, coût nul) :
   auto-désignations dont le français porte le genre — métiers et titres
   (« chasseur / chasseuse », « le gardien / la gardienne »), articles
   d'auto-présentation (« je suis *la* … »). Liste finie, versionnée,
   auditable. Les mots épicènes (« forgemage ») ne votent pas.
2. **Accords en première personne** (déjà écartés comme signal *principal*,
   gardés comme signal d'appoint) : « je suis venue », « je suis prête ».
   Rare mais sans ambiguïté quand il est là. Le piège « tu es venue » (qui
   accorde le *joueur*) reste exclu : seules les formes en « je » comptent.
3. **OCR ciblé du cartouche + table nom → genre embarquée** : recette
   FINDINGS (crop du parchemin, upscale 4×, `--psm 6`, nettoyage de
   bordure), rapprochement flou **à marge** contre une table finie générée
   hors ligne depuis les données communautaires du jeu (licence de la source
   à vérifier avant d'embarquer). Ce signal n'entre au code **que si la
   re-mesure sur le registre atteint le critère chiffré** ci-dessous — les
   ratios de l'abandon font foi tant qu'ils ne sont pas battus.

Règles de flux :

- **Une décision par dialogue, jamais par image.** Le genre est arrêté au
  moment du `say()` (le point où `Reader._dire` confie la réplique), et vaut
  pour toute la réplique : la voix ne change pas en cours de phrase quand
  l'OCR cligne. La déduplication `same_dialog` garantit déjà un seul `say`
  par réplique — la décision s'y adosse.
- **Coût borné** : le signal 3 (OCR du cartouche) ne tourne que sur un
  dialogue *nouveau*, jamais à chaque image. Une réplique = au plus un OCR
  de cartouche en plus de l'existant.
- **Contrat moteur** : le booléen `narration` de `Engine.speak` devient un
  **canal de voix** à trois valeurs — `pnj_masculin`, `pnj_feminin`,
  `narration` — avec `pnj_masculin` comme valeur d'inconnu (comportement
  actuel inchangé). Piper et XTTS ont déjà la mécanique deux-voix ; ils
  passent à trois. Kokoro n'a qu'une voix française : il reste hors
  adaptation, comme il est déjà hors seconde voix (débit ralenti pour les
  didascalies) — documenté, pas contourné.
- Le choix des voix par canal (et la règle « jamais la même voix sur deux
  canaux », qui interdit de réutiliser la voix de narration pour les PNJ
  féminins) relève de l'ADR-0002.

## Options étudiées

| Option | Sort | Pourquoi |
|---|---|---|
| A. Table nom → genre sur OCR brut du cartouche | Rejetée telle quelle | Mesuré à 0,11–0,24 de ratio ; recevable seulement via la recette 4× + psm 6 et le rapprochement à marge — c'est le signal 3, conditionné à la re-mesure |
| B. Accords grammaticaux seuls | Insuffisant | Mesuré : 0 des 4 dialogues d'origine n'en contient ; gardé en appoint (signal 2) |
| C. Lexique de métiers/titres genrés | Retenue (signal 1) | Présent dans les fixtures réelles (« chasseur », « L'Explorancienne », « Gardien des Geôles ») ; déterministe, auditable, coût nul |
| D. Classification du portrait (vision) | Rejetée | Aucune donnée étiquetée, variance forte (thèmes, zoom, angle), coût d'entretien sans commune mesure avec le besoin |
| E. Assignation manuelle par le joueur | Écartée comme mécanisme principal | Contraire au parti pris du README (« aucune sélection manuelle ») ; reste une échappatoire envisageable plus tard, hors de cette ADR |

## Prérequis de données

- **Étendre le registre** avec des captures où le cartouche de nom est
  visible (les crops actuels l'excluent souvent), chat masqué avant commit
  comme le veut l'usage du dépôt.
- **Étiqueter la vérité terrain** : un fichier versionné (nom du PNJ, genre,
  signaux attendus) par capture du registre. C'est lui que les tests et la
  mesure de couverture lisent.
- Les tests qui dépendent du texte rendu par tesseract portent le marqueur
  `ocr_fixture` existant : mêmes raisons, même discipline (exclus de la CI,
  actifs sur la machine de calibration).

## Critères d'acceptation

Mesurés sur le registre étiqueté, *avant* d'engager le code du signal 3 :

- **Zéro erreur de genre.** Toute erreur se corrige en resserrant le seuil
  (donc en s'abstenant), jamais en l'admettant.
- **Couverture initiale ≥ 50 %** des dialogues à cartouche visible pour le
  signal 3 (rapprochement à marge) ; en deçà, le signal reste hors code et
  seuls les signaux 1–2 embarquent.
- **Coût** : ≤ un OCR de région de cartouche par nouveau dialogue, mesuré en
  millisecondes via `QR_DEBUG` comme les mesures existantes.
- **Aucune régression** : la suite actuelle passe inchangée ; une réplique
  sans signal sonne exactement comme aujourd'hui.

## Conséquences

- Le contrat `Engine.speak` change (canal à trois valeurs) : les trois
  moteurs et leurs tests sont touchés ; `Speaker`/`Reader` font circuler le
  canal décidé.
- Une **voix féminine de dialogue** doit exister par moteur sans entrer en
  collision avec la voix de narration — c'est le premier livrable de
  l'ADR-0002, dont cette ADR dépend.
- La table nom → genre embarquée ajoute un artefact au bundle (spec
  PyInstaller) et une provenance à documenter (source, licence, date de
  génération, script de régénération hors ligne).
- Le registre de fixtures grandit encore : c'est assumé, il est déjà le
  socle de toutes les décisions de détection.

## Hors périmètre

- Le genre du **joueur** (piège « tu es venue », documenté dans le plan).
- Les PNJ créatures, objets parlants ou volontairement ambigus : voix par
  défaut, sans tentative.
- Kokoro (une seule voix française dans le modèle — contrainte amont).
- Tout traitement du signal audio (pitch-shift) pour « féminiser » une voix
  existante : le rendu est mauvais, et l'ADR-0002 traite le vrai besoin (des
  voix supplémentaires).

## Références

- README, section « Pas de détection du genre du PNJ » (mesures de
  l'abandon).
- `plans/moteur-xtts-et-genre.md`, « Pourquoi il n'y a pas de détection de
  genre ».
- `FINDINGS.md` (recette cartouche : upscale 4× + `--psm 6`).
- `tests/helpers.py` (registre `SAMPLES` et fixtures étiquetées à la main).
- ADR-0002 (catalogue de voix : affectation des canaux).
