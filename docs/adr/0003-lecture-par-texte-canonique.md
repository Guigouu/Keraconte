# ADR-0003 — Lecture par texte canonique : l'OCR devient une clé d'index

- **Statut** : Proposé
- **Date** : 2026-08-03

## Contexte et problème

L'association réplique → PNJ de l'ADR-0001 (mécanique du signal 3) ouvre
plus que le choix d'une voix : la base communautaire porte **le texte
exact** de chaque réplique. Or aujourd'hui, ce qui est lu à voix haute est
le texte *OCRisé*, avec ses défauts assumés — les fixtures elles-mêmes les
consignent (« Il y en a dans le donjon _kd'à côté », « Zog Zog à toû. ») —
et toute la mécanique de patience qui va avec : le portail à deux images
(`pending`) n'existe que parce que l'OCR saisit des versions tronquées
avant la complète, et il coûte au moins une image de latence à chaque
réplique.

Si l'association est sûre, l'OCR n'a plus besoin d'être *lu* : il n'a
besoin que d'*identifier*. Le texte canonique fait le reste — bruit
résiduel éliminé, ponctuation exacte (dont Piper tire ses pauses), fin de
réplique jamais tronquée.

## Décision

Quand — et seulement quand — l'association de l'ADR-0001 identifie la
réplique avec une confiance **stricte**, la synthèse reçoit le **texte
canonique** de la base au lieu du texte OCRisé. Dans tous les autres cas,
rien ne change : l'OCR reste lu tel quel, comme aujourd'hui.

Règles :

- **Deux seuils distincts, pas un.** Se tromper de voix est un désagrément ;
  faire *dire autre chose que ce qui est à l'écran* est une faute. Le seuil
  de substitution du texte est donc plus strict que le seuil de choix de
  voix (chiffres à caler sur le registre : la bande mesurée des variantes
  d'un même texte, 0,00–0,31, est la zone de départ), et la marge sur le
  deuxième candidat s'applique aux deux.
- **Placeholders** : un texte canonique à `#N` (nom du joueur, quantités)
  n'est substitué que si les valeurs se réinjectent depuis le texte OCRisé
  par alignement ; sinon repli sur l'OCR. Les nombres portent les quantités
  de quête — le projet les protège déjà (`keep_word`), on ne va pas les
  perdre dans la substitution.
- **Latence : le portail à deux images devient un repli.** Une association
  sûre dès la *première* image permet de parler immédiatement — le texte
  canonique est complet par construction, il n'y a plus rien à attendre.
  La mécanique `pending` actuelle reste en place pour les répliques hors
  table.
- **Honnêteté d'affichage** : la console (`> …`) montre ce qui est *dit*.
  Si le canonique est substitué, c'est lui qui s'affiche.
- **La table avec textes est un artefact LOCAL, jamais redistribué.**
  L'ADR-0001 n'embarque que des empreintes non réversibles — le genre
  fonctionne dès l'installation. Les textes en clair, eux, posent une
  question de droits (redistribuer les dialogues du jeu n'est pas
  redistribuer des empreintes) : la table complète est donc **générée ou
  téléchargée à l'installation par l'utilisateur**, exactement comme les
  voix Piper aujourd'hui (le README documente une commande, le dépôt ne
  contient que le script). Le runtime reste strictement hors ligne ; la
  génération est un geste d'installation, au même titre que
  `piper.download_voices`.
- **Périmption** : table absente ou périmée (mise à jour du jeu) →
  comportement strictement identique à aujourd'hui, réplique par réplique.
  La lecture canonique est une amélioration opportuniste, jamais une
  dépendance.

## Options étudiées

| Option | Sort | Pourquoi |
|---|---|---|
| Lire toujours l'OCR (statu quo) | Conservée comme repli permanent | C'est le comportement hors table, hors seuil, hors placeholders — la substitution ne fait que s'y superposer |
| Embarquer les textes en clair dans le bundle | Écartée pour l'instant | Redistribuer les dialogues du jeu ≠ redistribuer des empreintes ; à ne rouvrir qu'après vérification de la politique fan-content d'Ankama. La génération locale à l'installation donne le même service sans la question |
| Corriger l'OCR mot à mot contre le canonique | Rejetée | Complexité d'alignement pour un résultat inférieur à la substitution entière ; et un alignement partiel fabrique des phrases qui n'existent nulle part |
| Reformuler/résumer par un modèle de langue | Rejetée net | Le projet lit le jeu, il ne le réécrit pas ; et tout ce qui sort du déterminisme mesurable est contraire à la méthode du dépôt |

## Critères d'acceptation

- **Zéro substitution erronée** sur le registre étiqueté : chaque texte
  substitué doit être exactement la réplique affichée à l'écran de la
  capture. Une seule erreur = seuil resserré, jamais l'inverse.
- **Latence mesurée** (`QR_DEBUG`, comme les mesures existantes) : réplique
  dite dès la première image quand l'association tient — contre deux images
  minimum aujourd'hui.
- **Repli bit-à-bit** : table absente → la suite de tests actuelle passe
  inchangée, et le comportement en jeu est celui d'aujourd'hui.
- Les répliques à placeholders du registre (s'il s'en trouve) sont soit
  correctement réinjectées, soit lues à l'OCR — jamais dites avec un trou.

## Conséquences

- `Reader._dire` gagne un chemin de substitution (décidé une fois par
  dialogue, comme le genre de l'ADR-0001 — même point d'ancrage, même
  cache).
- Un script d'installation de la table locale rejoint le README, à côté du
  téléchargement des voix ; sa provenance et sa date s'affichent pour que
  l'utilisateur sache de quand datent ses textes.
- La dédup `same_dialog` peut, quand l'association tient, se faire par
  identité canonique — exacte au lieu de tolérante. Amélioration
  opportuniste, même discipline de repli.
- Dépend de l'ADR-0001 (mécanique d'association) ; orthogonale à
  l'ADR-0002 (la voix choisie lit ce texte, quel qu'il soit).

## Hors périmètre

- Les réponses du joueur (jamais lues, inchangé) et le nom du PNJ.
- Les autres langues que le français.
- Toute correction *linguistique* du texte du jeu (fautes d'Ankama
  comprises : on lit ce que le jeu affiche).

## Références

- ADR-0001, « Mécanique d'association (signal 3) » — chaîne de données
  vérifiée (`/npcs` → paires d'ids → `/npc-messages/<id>` → texte fr,
  placeholders `#N`).
- `keraconte/reader.py` (portail à deux images, `pending`) et
  `keraconte/text.py` (`clearest`, `same_dialog` : les mesures 0,00–0,31 /
  1,86–4,11).
- `tests/helpers.py` (« _kd'à côté », « toû » : le bruit OCR résiduel que
  cette ADR fait disparaître de la voix).
- README, « Onomatopées » et « Deux voix » (la synthèse profite d'une
  ponctuation exacte).
