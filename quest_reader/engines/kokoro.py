"""Moteur Kokoro : une seule voix française, sur le processeur."""

import tempfile

from quest_reader.engines import KOKORO_MODEL, KOKORO_VOICES, Engine
from quest_reader.playback import play_wave
from quest_reader.text import pronounce, speakable


class KokoroEngine(Engine):
    """Respecte mieux la ponctuation, mais n'a qu'une voix française.

    Faute d'une seconde voix, les didascalies se distinguent par un débit
    plus lent. Le modèle tourne sur le processeur : la carte graphique est
    réservée au jeu.
    """

    VOICE = "ff_siwis"
    # Seul signe distinctif des didascalies faute d'une seconde voix : il
    # faut donc que l'écart de débit s'entende nettement.
    NARRATION_SLOWDOWN = 0.75

    def __init__(self, speed):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        self.speed = speed

    def speak(self, text, narration, generation):
        import soundfile

        spoken = pronounce(text)
        # Sans phonème à concaténer, « create » lève au lieu de se taire.
        if not speakable(spoken):
            return
        speed = self.speed
        if narration:
            speed *= self.NARRATION_SLOWDOWN
        samples, rate = self.kokoro.create(
            spoken, voice=self.VOICE, lang="fr-fr", speed=speed
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            soundfile.write(handle.name, samples, rate)
            play_wave(handle.name, generation)
