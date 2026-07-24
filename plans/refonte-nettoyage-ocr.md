# Refonte du nettoyage OCR et correction des plantages de synthèse

## Pourquoi ce plan

Le nettoyage actuel énumère les formes de bruit observées, une regex par
forme : `E x`, `SE x`, `(3 e e x`, `2E`, `x.`, `CON .`, `Â 3 Ë x`. Sept
motifs, et la dernière session de jeu en a produit cinq nouveaux (`A3`,
`»/`, `SN 64`, `dn S`, `mc 2S`). La liste ne converge pas : chaque partie
révèle une variante inédite.

Le coût de cette approche est mesuré, pas supposé :

- **Perte silencieuse de dialogue.** `strip_choices(clean("Bonjour. Rester
  ici serait dangereux."))` renvoie `"Bonjour."`. Toute phrase de PNJ
  ouvrant sur un infinitif disparaît sans trace.
- **Régressions en chaîne.** Corriger `CON .` a cassé `Direction le NORD.`
  Corriger `2E` a cassé le nettoyage de queue (8 tests rouges d'un coup).

## Ce qui remplace l'énumération

`pytesseract.image_to_data` donne un score de confiance par mot. Mesuré sur
les trois fixtures :

| Capture | Mots | Bruit détecté (confiance) |
|---|---|---|
| brakmar | 29 | `E` 36, `e` 43, `:` 50 |
| cliquetis | 6 | `PE` 24, `A` 44 |
| enrolement | 55 | `x` 49 |

Le bruit tombe entre 24 et 50. Un critère unique remplace les sept regex.

**Réserve à traiter, pas à ignorer :** de vrais mots sont mal notés —
`t'enrôler` à 41, `lieux,` à 53. Un seuil de confiance seul les
supprimerait.

### Le discriminant, mesuré

La position en extrémité **ne peut pas** servir de critère : la dernière
trace de jeu montre du bruit en plein milieu d'une phrase —
« Si ça **A3** t'intéresse » et « serviront à **»/** entraîner ». Un
critère positionnel les laisserait passer, reproduisant le trou que cette
refonte doit fermer.

Deux signaux sont donc croisés, aucun n'étant suffisant seul (vérifié) :

**Structure** — pas de voyelle, ou mélange chiffre+lettre :

| Rejette | Laisse passer à tort |
|---|---|
| `A3` `»/` `SN` `64` `dn` `mc` `2S` `2E` `(3` `Ë` `x` | `PE` `E` `CON` `SE` (ont une voyelle) |

Elle sauve `t'enrôler` et `lieux,` malgré leur faible confiance, mais
rejette `10` à tort — un nombre seul est un mot légitime.

**Confiance** — `PE` 24, `A` 44, `E` 36 : c'est elle qui attrape ce que la
structure laisse passer.

Règle : un token est du bruit s'il est **implausible structurellement** ou
**de confiance faible ET court**. Les nombres purs (`10`, `5`) sont
toujours conservés : ils portent les quantités de quête.

## Étapes

### 1. Corriger les deux plantages de synthèse (bloquant, indépendant)

Observés en jeu, ils cassent la lecture immédiatement.

- `need at least one array to concatenate` — Kokoro reçoit un texte vide.
  Vient de `split_narration` sur `* *Cliquetis*-*Cliquecliquetis*` : le
  segment hors astérisques est vide. Filtrer les segments vides avant
  synthèse, dans les deux moteurs.
- `[Errno 2] libespeak-ng.so` — chemin **Kokoro**, pas Piper : `phonemizer`
  et `espeakng_loader` sont importés par `kokoro_onnx` (vérifié). La
  bibliothèque est extraite dans un dossier temporaire ; au `Ctrl+C` ce
  dossier disparaît alors que le thread `Speaker`, marqué `daemon`,
  continue de vider sa file et rappelle espeak à chaque élément — d'où la
  cascade d'erreurs identiques. Traiter l'arrêt propre du thread, pas
  seulement l'erreur.

**Validation :** lire une bulle ne contenant qu'une didascalie sans plantage ;
interrompre puis relancer sans erreur `libespeak-ng.so`.

### 2. Remplacer le nettoyage par le critère de confiance

- Passer `find_dialog` à `image_to_data`.
- Écrire `clean` sur les trois signaux ci-dessus.
- Supprimer les sept regex de bruit.
- Conserver : recollage des lignes, `split_narration`, `pronounce`,
  `same_dialog`, la garde sur les chiffres.

**Où vit le filtrage, et ce que deviennent les tests.** Les scores de
confiance n'existent qu'au niveau du mot, dans `find_dialog`. Or une
vingtaine de tests appellent `clean("chaîne brute")`, où aucun score n'est
disponible. Les trois exigences « filtrer sur la confiance », « supprimer
les regex » et « ne toucher aucun test » sont donc incompatibles.

Décision : le retrait du bruit remonte au niveau mot, dans une fonction
`keep_word(texte, confiance)` testable seule. `clean` ne garde que le
recollage des lignes et la ponctuation.

Conséquence assumée sur les tests :

- les tests sur **fixtures** (comportement de bout en bout) ne changent
  pas — ce sont eux la spécification ;
- les tests appelant `clean("E x …")` sont **ré-exprimés** contre
  `keep_word`, avec les mêmes cas. Le cas couvert survit, son point
  d'entrée change.

Aucun attendu de fixture ne doit être modifié pour faire passer la suite.

Cas de non-régression qui ont déjà cassé une fois :
`Direction le NORD.`, `C'est` (élision), `Œuvre`, `5 peaux` vs `6 peaux`,
`Tu es blessé`, `STOP.`

### 3. Retrait des réponses du joueur

> Les étapes 2 et 3 touchent toutes deux `find_dialog` et reposent sur le
> même passage à `image_to_data` : elles vont **au même agent**, en
> séquence. Seule l'étape 1 est indépendante et peut tourner en parallèle.

Aujourd'hui, `strip_choices` reconnaît un choix à son verbe à l'infinitif —
d'où la perte de `Rester ici serait dangereux.`

Les réponses sont **géométriquement** séparées du dialogue : elles occupent
le bas du bloc fusionné. Découper par position plutôt que par grammaire
supprime la classe entière de faux positifs.

**Validation :** `Bonjour. Rester ici serait dangereux.` intact sur le
chemin fusionné ; `enrolement` continue de ne pas lire les deux choix.

### 4. Vérification en jeu

Les fixtures sont figées : elles ne peuvent pas reproduire l'alternance
frame propre / frame bruitée qui cause la relecture. Confirmer sur les deux
PNJ connus (Oto Mustam, Mak Gahan) qu'aucun dialogue n'est relu ni perdu.

## Hors périmètre

- **Voix selon le genre du PNJ.** Bloqué : Kokoro n'a qu'une voix française
  (`ff_siwis`, féminine) ; ses 53 autres voix sont anglaises. Question
  ouverte de l'utilisateur — d'autres moteurs (XTTS-v2, Coqui, Bark) —
  à traiter séparément.
- Lecture du nom du PNJ sur le cartouche : OCR trop instable
  (« Sotsiah Peh » lu « Chtoish Dah »). Piste abandonnée.
