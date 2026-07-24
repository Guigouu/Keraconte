# Réactivité de la coupure et de la bascule de lecture

## Problème

Deux transitions de lecture sont trop lentes, mesurées à `--fps 2` :

- **Fermeture du dialogue.** La voix ne se coupe qu'après `CLOSED_AFTER = 3`
  images sans bulle, soit **1,5 s**. On vise **sous 0,5 s**.
- **Passage au dialogue suivant.** Un nouveau dialogue n'interrompt pas la
  lecture en cours : `say()` l'empile derrière la file (`BACKLOG = 4`). Le
  suivant attend que le courant et la file se vident.

## Décisions cadrées avec l'utilisateur

- **Bascule immédiate.** Un nouveau dialogue coupe net la lecture en cours et
  jette la file. Prix assumé : dans un échange très rapide, une réplique
  intermédiaire peut ne jamais être lue.
- **Menu ouvert par-dessus le dialogue.** La bulle disparaît de l'écran sans
  que le joueur ait fermé le dialogue. Comportement retenu : **se taire**
  pendant le masquage, et **ne pas relire** au retour (le dialogue est tenu
  pour déjà lu). Conséquence : toute disparition de bulle — vraie fermeture
  *ou* menu par-dessus — déclenche la même coupure. Il n'y a plus de
  « disparition passagère à protéger ».
- **Cadence.** Monter `--fps` à **4** par défaut. Regarder l'écran quatre fois
  par seconde suffit à couper vite, sans ajouter de voie de sondage séparée. Si
  le coût CPU pose problème plus tard, on optimisera alors.
- **Seuil de coupure : 2 images**, mesuré. `find_bubbles` (détection par
  couleur) est robuste au bruit léger et à la compression JPEG même à qualité
  50, mais peut rater une image sous bruit gaussien fort (σ≥5). Couper dès la
  1ʳᵉ image (0,25 s) supprimerait toute tolérance à ce flicker détecteur, que
  monter le fps à 4 rend deux fois plus probable par dialogue. Deux images à
  fps 4 = **0,5 s** : toujours sous la demi-seconde demandée, avec une image de
  tolérance. Assurance bon marché contre une coupure en plein milieu d'une
  réplique.

## Note sur l'« écriture progressive »

Le code commente la logique `pending` comme « Dofus écrit sa réplique
progressivement ». C'est **trompeur** : le jeu affiche la bulle d'un coup, et
l'on passe au dialogue suivant en cliquant une réponse. La logique reste
pourtant justifiée, pour une autre raison : **l'OCR renvoie parfois un texte
tronqué** (dernière ligne ratée) avant le texte complet, à l'image suivante.
L'attente d'une image de confirmation protège de ce tronqué, pas d'une
écriture lente. Le commentaire est à reformuler un jour ; le comportement ne
change pas. Hors périmètre de cette tâche.

## Conception

### 1. Coupure rapide à la fermeture

- `--fps` par défaut passe de 2 à **4**.
- La coupure se déclenche après **2** images sans bulle (au lieu de 3). Le
  compteur `CLOSED_AFTER` est **retiré** (et non ramené à une valeur) : chaque
  référence lève alors une erreur franche, forçant à revisiter explicitement
  chaque site plutôt que laisser des tests passer à vide.
- La sémantique « une seule fois par disparition » est préservée : la coupure
  doit se déclencher exactement une fois quand le seuil est atteint, pas à
  chaque image absente au-delà.
- **Garde-fou inchangé.** On ne coupe que si `find_bubbles` — détection par
  couleur, sans OCR — ne voit **aucun** bloc bleu/neutre. Si un bloc est
  présent mais que l'OCR échoue, on ne coupe pas : c'est la même réplique qui
  s'affiche encore. Ce garde-fou distingue « bulle absente » de « OCR raté sur
  bulle présente ».
- `last_text` continue de survivre à la coupure, pour ne pas relire au retour
  d'un menu.

### 2. Bascule immédiate au dialogue suivant

- `BACKLOG` passe de 4 à **1** : seul le dialogue en cours de lecture.
- `say(text)` **coupe le son en cours et vide la file** avant d'enfiler le
  nouveau texte (appelle `silence()` puis enfile).
- **Course sur `stopped` — le point délicat.** Un `silence()` (pose
  `stopped = True`) immédiatement suivi de `say()` → `resume()` (remet
  `stopped = False`) laisse le fil `Speaker` rater la coupure s'il n'a pas
  encore vu `stopped = True` : l'ancien dialogue finit sa phrase. Correction :
  un **compteur de génération**. Chaque `say()` incrémente un numéro ; le
  `Speaker` et les moteurs vérifient « suis-je toujours sur la génération
  courante ? » entre chaque phrase, au lieu d'un booléen partagé. Un dialogue
  de génération périmée s'arrête même après un `resume()` déjà passé. La course
  disparaît sans dépendre du timing.
- **Plancher incompressible.** Un nouveau dialogue exige une image de
  confirmation (logique `pending`, cf. note ci-dessus) avant d'être lu — ~0,25 s
  à `--fps 4`. La bascule ne descend pas sous ça, et c'est voulu : sinon on
  lirait des répliques tronquées.

## Tests

Sans audio réel : la suite mocke déjà `subprocess.Popen` (`FauxProcessus`) et
pilote `Reader.handle` image par image via `images(...)`.

**Coupure (section 1).**
- Dialogue lu → **1** image sans bulle → `silence()` appelé.
- Bulle présente mais OCR vide → **pas** de coupure (garde-fou).
- Dialogue → images sans bulle (menu) → retour du **même** dialogue → **pas**
  relu (`last_text` a survécu).
- Les tests encodant `CLOSED_AFTER = 3` sont mis à jour vers le nouveau seuil —
  la spec temporelle change, assumé.

**Bascule (section 2).**
- Dialogue A en cours → B arrive → la file a été purgée et A coupé
  (générations distinctes).
- `test_deux_repliques_successives_sont_toutes_deux_lues` **reste vert** : A et
  B sont toujours toutes deux lues ; on ne perd que le reliquat de A.
- Génération périmée : deux `say()` successifs ne laissent jouer que le second.

**Principe directeur.** Aucun attendu de **fixture** (détection de bout en
bout) n'est modifié — elles sont la spécification. Seuls changent les tests qui
encodaient les anciens seuils temporels.

## Hors périmètre

- Reformulation du commentaire « écriture progressive » (cosmétique).
- Voie de sondage `find_bubbles` séparée de l'OCR (repli si le CPU souffre).
- Réglages de genre/voix des PNJ (autre chantier).
