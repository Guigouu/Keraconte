"""Tests du fil de synthèse (keraconte.speaker)."""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte.playback import playback  # noqa: E402
from keraconte.speaker import Speaker  # noqa: E402


def test_le_speaker_s_arrete_sans_vider_sa_file():
    """Après un Ctrl+C, le reste de la file ne doit plus être synthétisé.

    Le thread est « daemon » : s'il survit à l'arrêt, il rappelle espeak
    pendant que l'interpréteur détruit les dossiers temporaires, d'où la
    cascade de « [Errno 2] libespeak-ng.so » — une par élément restant.
    """

    dits = []

    class MoteurFactice:
        def speak(self, texte, narration, generation):
            dits.append(texte)

    speaker = Speaker(MoteurFactice)
    speaker.start()
    speaker.say("Premier.")
    speaker.say("Deuxième.")
    speaker.stop()

    assert not speaker.is_alive()
    # La file est purgée, pas jouée jusqu'au bout : l'arrêt est immédiat.
    assert dits == [] or dits == ["Premier."]


def test_la_file_du_speaker_ne_grossit_pas_sans_fin():
    """Empiler pendant le chargement du moteur ne doit rien accumuler.

    XTTS met 83 s à charger, et « run » ne dépile rien pendant ce temps.
    Avec une file non bornée, tout ce que la capture voyait s'y entassait,
    puis partait en rafale à la fin du chargement : c'est ce qui a rempli
    la mémoire de la machine.
    """

    speaker = Speaker(lambda: None)  # jamais démarré : personne ne dépile

    for numero in range(50):
        speaker.say(f"Réplique numéro {numero}.")

    assert speaker.queue.qsize() <= Speaker.BACKLOG


def test_say_ne_bloque_pas_le_fil_de_capture():
    """Une file pleine doit rendre la main, pas figer l'écran.

    « say » est appelé depuis la boucle de capture : s'il bloque, la
    capture s'arrête avec lui.
    """

    speaker = Speaker(lambda: None)
    for numero in range(Speaker.BACKLOG + 3):
        speaker.say(f"Réplique {numero}.")

    debut = time.monotonic()
    speaker.say("Celle-ci est de trop.")
    assert time.monotonic() - debut < 0.5


def test_un_nouveau_dialogue_coupe_le_precedent():
    """say(B) pendant la lecture de A coupe A et n'empile pas.

    On n'a pas besoin de démarrer le thread : on éprouve l'effet de say sur
    la file et la génération de l'instance module « playback ».
    """

    class MoteurFactice:
        def speak(self, texte, narration, generation):
            pass

    speaker = Speaker(MoteurFactice)
    g0 = playback.generation
    speaker.say("Dialogue A.")
    speaker.say("Dialogue B.")
    assert speaker.queue.qsize() <= 1     # BACKLOG = 1, pas d'empilement
    assert playback.generation > g0       # chaque say ouvre une génération


def test_un_nouveau_dialogue_leve_la_pause():
    """Une bascule vers un nouveau dialogue défige la voix (design : la
    pause « saute » quand un nouveau dialogue reprend le dessus)."""
    from keraconte.playback import player_state
    from keraconte.speaker import Speaker

    player_state.pause()
    try:
        speaker = Speaker.__new__(Speaker)
        speaker.queue = __import__("queue").Queue(maxsize=1)
        speaker.say("Un nouveau dialogue.")
        assert not player_state.en_pause
    finally:
        # « player_state » est une instance unique de module : on remet
        # l'état à ACTIF pour ne pas contaminer les autres tests (un
        # EN_PAUSE fuité ferait tourner la boucle de « play » sans fin).
        player_state.reprendre()


def test_fermer_le_dialogue_ne_leve_pas_la_pause():
    """silence() coupe la voix mais ne défige pas : fermer une fenêtre
    pendant une pause ne doit pas relancer une lecture."""
    from keraconte.playback import player_state
    from keraconte.speaker import Speaker

    player_state.pause()
    try:
        speaker = Speaker.__new__(Speaker)
        speaker.queue = __import__("queue").Queue(maxsize=1)
        speaker.silence()
        assert player_state.en_pause
    finally:
        player_state.reprendre()
