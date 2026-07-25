# Overlay de contrôle de la lecture (pause / stop / reprise)

## Problème

La lecture des dialogues est aujourd'hui entièrement automatique : elle suit
l'écran, sans aucun contrôle manuel. On veut une petite interface flottante,
toujours au-dessus de la fenêtre du jeu, avec trois boutons — pause (‖), stop
(■), reprise (▶) — pour piloter la voix à la main.

Cette fonctionnalité prépare aussi un objectif plus large exprimé par
l'utilisateur : distribuer l'application sur Windows et Mac. Les choix
techniques ci-dessous privilégient donc des briques multiplateformes, même si
le périmètre livré maintenant reste Linux.

## Décisions cadrées avec l'utilisateur

- **Trois boutons, trois rôles distincts** :
  - **Stop (■)** = interrupteur marche/arrêt du lecteur. Il **cesse d'analyser
    l'écran**, coupe la voix, et plus rien n'est lu jusqu'à ▶.
  - **Pause (‖)** = suspension fine : **gèle la voix au milieu de la réplique
    en cours**, sans débrayer l'analyse.
  - **Reprise (▶)** = repart. Depuis une pause : reprend la réplique exactement
    où elle en était. Depuis un stop : réanalyse l'écran.
- **Pause vs écran** : en pause, si un **nouveau dialogue** apparaît, il reprend
  le dessus (comme la bascule immédiate déjà en place), et la pause saute. La
  pause gèle donc la réplique courante mais ne fige pas le jeu.
- **Périmètre maintenant** : UI + lecteur audio pausable, **sur Linux d'abord**.
  Le portage complet Windows/Mac (capture d'écran, packaging) est un chantier
  séparé ultérieur. Le lecteur audio est néanmoins écrit multiplateforme, pour
  ne pas être à refaire.
- **UI en Qt (PySide6)** : always-on-top sans bordure bien supporté sur les
  trois OS, packaging éprouvé — écrit une fois, réutilisé au portage. Coût
  assumé : une dépendance nouvelle et l'articulation de sa boucle d'événements
  avec la boucle GLib de capture.
- **Audio pausable via `sounddevice`** (PortAudio) : remplace `paplay`, qui joue
  un fichier d'un bloc et ne sait pas se mettre en pause. Une seule dépendance,
  identique sur les trois OS.

## Architecture

### État partagé

Un objet `PlayerState` porte l'état de lecture, à trois valeurs : `ACTIF`,
`EN_PAUSE`, `ARRÊTÉ`. Il est protégé par un lock (comme `Playback`
aujourd'hui). L'UI **écrit** cet état ; le `Reader` et le lecteur audio le
**lisent**. Les boutons ne touchent jamais directement la capture ni l'audio :
tout passe par cet état. C'est le point de découplage central.

- **Stop débraye l'analyse** : le `Reader` ignore les images quand l'état est
  `ARRÊTÉ`.
- **Pause agit sur l'audio en cours** sans débrayer l'analyse : le `Reader`
  continue de tourner (pour détecter un nouveau dialogue qui reprendra le
  dessus), mais le lecteur audio se fige.

### Lecteur audio pausable (réécriture de `playback.py`)

Au lieu de lancer `paplay` sur le WAV entier, on lit le fichier et on l'écrit
vers la sortie son **par tranches** (de l'ordre de 20 ms). Entre deux tranches,
on consulte :

- **la génération** (mécanisme existant de coupure/bascule, conservé tel quel) :
  si elle a changé, on abandonne et on sort ;
- **l'état de pause** : si `EN_PAUSE`, on attend avant d'écrire la tranche
  suivante.

La reprise repart à la tranche suivante — donc au milieu du mot, comme voulu.
Le compteur de génération reste le mécanisme de coupure/bascule ; la pause est
une notion ajoutée par-dessus, elle ne le remplace pas. La pause fine ne
concerne que l'audio : le découpage en phrases existant est inchangé, et la
pause peut tomber n'importe où dans une phrase.

Brique : `sounddevice` (binding PortAudio), multiplateforme.

### Overlay Qt (`overlay.py`)

Petite fenêtre sans bordure, always-on-top, déplaçable, avec les trois icônes.
Elle flotte au-dessus de tout : aucune dépendance à la position de la fenêtre de
jeu. Les icônes reflètent l'état courant (le bouton actif est grisé). Un clic se
contente d'écrire la transition dans `PlayerState`.

### Articulation des boucles (le point structurant)

On n'unifie pas les boucles d'événements ; on les **isole** dans des threads,
comme la capture et la synthèse le sont déjà :

- **Thread principal → Qt.** L'overlay tient la boucle principale.
- **Thread capture → GLib.** Le `Reader` et sa boucle GLib (PipeWire) descendent
  dans un thread dédié. Fonctionnement inchangé, seulement déplacé hors du thread
  principal.
- **Thread synthèse → `Speaker`.** Inchangé.

### Arborescence cible

```
quest_reader/
├── state.py       # PlayerState (ACTIF / EN_PAUSE / ARRÊTÉ) — feuille
├── playback.py    # réécrit : lecture par tranches, pausable (sounddevice)
├── overlay.py     # fenêtre Qt, 3 boutons → écrivent dans state
├── reader.py      # consulte state ; descend dans un thread
└── __main__.py    # démarre Qt (principal) + Reader (thread)
```

`state` est une feuille (aucun import du package). `playback` dépend de `state`.
`overlay` dépend de `state`. `reader` dépend de `state`. Aucun cycle.

## Gestion des erreurs et cas limites

- **Pas de périphérique audio / `sounddevice` absent** : le lecteur le signale
  et l'app continue ; l'overlay reste utilisable (même esprit que l'arrêt propre
  de XTTS sans CUDA).
- **Stop pendant une réplique** : coupe l'audio en cours (via génération) et le
  `Reader` cesse d'analyser. ▶ le réarme.
- **Pause puis nouveau dialogue** : le nouveau reprend le dessus (bascule),
  l'état repasse `ACTIF`.
- **Fermeture de l'app** : Qt quitte → arrêt propre du thread capture (boucle
  GLib) et du `Speaker`, comme le `finally` actuel de `reader.run`.

## Tests

- `state.py` : transitions d'état, testables seules (aucune dépendance).
- `playback.py` : la boucle de tranches consulte bien pause et génération —
  testée avec une fausse sortie audio (dans l'esprit de `FauxProcessus` /
  `faux_xtts`), sans vrai son.
- `overlay.py` : un clic écrit la bonne transition dans `PlayerState` (Qt permet
  de tester sans affichage réel).
- `reader.py` : ignore les images quand l'état est `ARRÊTÉ`, continue de tourner
  quand il est `EN_PAUSE`.

Pas de test du rendu visuel ni de l'always-on-top : vérification manuelle en
jeu, comme la latence de coupure/bascule.

## Hors périmètre

- Portage de la **capture d'écran** sur Windows/Mac (PipeWire est Linux-seul).
- Packaging/distribution multiplateforme.
- Toute pause qui figerait le jeu lui-même ou rembobinerait vers un dialogue
  précédent.
- Réglages fins de l'apparence de l'overlay (thème, taille configurable) au-delà
  des trois boutons et de leur état.
```
