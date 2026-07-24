"""Tests du fil de synthèse (quest_reader.speaker)."""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.speaker import Speaker  # noqa: E402


def test_le_speaker_s_arrete_sans_vider_sa_file():
    """Après un Ctrl+C, le reste de la file ne doit plus être synthétisé.

    Le thread est « daemon » : s'il survit à l'arrêt, il rappelle espeak
    pendant que l'interpréteur détruit les dossiers temporaires, d'où la
    cascade de « [Errno 2] libespeak-ng.so » — une par élément restant.
    """

    dits = []

    class MoteurFactice:
        def speak(self, texte, narration):
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
