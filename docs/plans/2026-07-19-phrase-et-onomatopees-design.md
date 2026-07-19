# Phrasé posé et onomatopées prononçables

Date : 2026-07-19

## Problème

Deux défauts de la lecture actuelle, relevés à l'écoute en jeu.

**Le phrasé n'est pas posé.** Tout le dialogue part à Piper d'un seul bloc.
Le moteur gère les pauses lui-même, et les silences entre phrases sont trop
courts : la lecture débite sans respirer.

**Les onomatopées sont épelées.** « Pssst » est prononcé « p-s-s-s-t ». Le
défaut vient du phonémiseur, qui ne sait pas traiter cette suite de
consonnes sans voyelle — pas de la voix. Vérifié : les quatre voix
françaises testées épellent de la même manière.

## Contraintes

- Gratuit et local. Aucune API payante, aucune clé, aucun envoi de données.
- Le texte affiché reste celui du jeu : on ne corrige que la prononciation.

## Choix de la voix

`fr_FR-tom-medium` est conservée. Les alternatives ont été écoutées et
écartées :

| Voix | Verdict |
|---|---|
| `fr_FR-gilles-low` | timbre moins convaincant |
| `fr_FR-upmc-medium` locuteur 0 | voix féminine (`jessica`), hors sujet ici |
| `fr_FR-upmc-medium` locuteur 1 | dégradée — `Missing phoneme from id map` |

## Deux moteurs au choix

Kokoro a été mesuré face à Piper. Les deux ont des forces opposées, donc le
moteur devient un choix au lancement plutôt qu'une décision figée.

| | Piper `fr_FR-tom-medium` | Kokoro `ff_siwis` |
|---|---|---|
| Voix | masculine | féminine — seule voix FR sur 54 |
| Latence (Ryzen 5900X, CPU) | 0,26 s | 1,51 s |
| Modèle | 63 Mo | 310 Mo |
| Ponctuation | pauses trop courtes | mieux respectée |
| Onomatopées | épelées | correctes |
| Timbre | plus naturel | un peu robotique |

Aucun des deux ne domine : Piper offre la voix masculine et la réactivité,
Kokoro le phrasé et les onomatopées. D'où l'option `--engine`.

Kokoro tourne sur CPU à dessein. La RTX 3070 Ti n'a que 1,4 Go de VRAM
libre hors jeu, et Dofus en a besoin : occuper le GPU provoquerait des
saccades en partie.

## Limites de Piper, assumées

Piper produit un timbre naturel et une intonation correcte, mais ne joue
pas : ni colère, ni ironie, ni personnage. Un PNJ menaçant et un marchand
jovial sonnent pareil. C'est une limite d'architecture du modèle ; aucun
réglage ne la lève. Un moteur expressif supposerait une API payante, ce que
la contrainte exclut.

Ce document ne cherche donc pas l'expressivité, mais un phrasé plus posé.

## Conception

### Choix du moteur

Une option `--engine piper|kokoro` sélectionne la synthèse. Piper reste le
défaut : voix masculine et latence quatre fois moindre.

Les deux moteurs sont placés derrière une interface commune — une classe
par moteur, exposant `speak(texte, narration)`. `Speaker` ne connaît que
cette interface et ignore lequel tourne.

Kokoro reste une dépendance facultative : son import n'a lieu que si
`--engine kokoro` est demandé, afin que le programme démarre sans lui.

### Phrasé

Piper reçoit le texte phrase par phrase, avec un silence inséré entre
chacune et un débit légèrement ralenti — ce qui lui manque aujourd'hui.
Kokoro respecte déjà la ponctuation et reçoit donc le texte entier.

| Option | Rôle | Défaut |
|---|---|---|
| `--engine` | moteur de synthèse : `piper` ou `kokoro` | `piper` |
| `--pause` | silence entre deux phrases, en millisecondes (Piper) | `320` |
| `--speed` | durée de la parole ; au-dessus de 1, plus lent | `1.05` |

### Onomatopées

Une table de substitution s'applique juste avant la synthèse. « Pssst » et
ses variantes deviennent « Pssit », qui ajoute la voyelle nécessaire au
phonémiseur tout en gardant la sonorité sifflante.

La substitution ne touche que le texte envoyé au moteur. Le texte affiché à
l'écran reste intact.

La table démarre volontairement petite — une entrée. On l'étoffera sur
constat, pas par anticipation.

## Ce qui ne change pas

Détection de la bulle, OCR, séparation des deux voix, anti-répétition. Les
17 tests existants doivent rester verts.

## Erreurs

Si une phrase échoue à la synthèse, elle est ignorée et la lecture continue.
Un dialogue amputé vaut mieux qu'un plantage en pleine partie.

## Tests

Le découpage en phrases et la substitution sont des fonctions pures,
testables sans audio :

- découpage sur points, points d'interrogation et d'exclamation ;
- espace avant la ponctuation double, comme le veut l'usage français ;
- didascalie à cheval sur deux phrases ;
- substitution appliquée quelle que soit la casse, sans toucher au reste.

Le rendu sonore, lui, se juge à l'oreille : aucun test automatique ne
remplacera une écoute en jeu.
