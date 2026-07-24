"""Moteur Piper : voix masculine rapide, découpée par phrases."""

import tempfile
import time
import wave

from quest_reader.engines import Engine
from quest_reader.playback import play_wave, playback
from quest_reader.text import pronounce, speakable, split_sentences


class PiperEngine(Engine):
    """Voix masculine, rapide, mais qui marque mal la ponctuation.

    D'où le découpage : chaque phrase est synthétisée à part, puis suivie
    d'un silence. Laisser Piper lire un paragraphe entier donne un débit
    sans respiration.
    """

    def __init__(self, voices, speed, pause):
        from piper import PiperVoice, SynthesisConfig

        # Piper raisonne en durée : au-dessus de 1, il ralentit. On expose
        # un débit, donc on inverse.
        self.config = SynthesisConfig(length_scale=1 / speed)
        self.voices = {kind: PiperVoice.load(path) for kind, path in voices.items()}
        self.pause = pause

    def speak(self, text, narration, generation):
        voice = self.voices["narration" if narration else "dialogue"]
        for sentence in split_sentences(pronounce(text)):
            # Le découpage isole parfois une ponctuation seule (« Ah… ! »).
            if not speakable(sentence):
                continue
            if generation != playback.generation:  # nouveau dialogue survenu
                return
            with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
                with wave.open(handle.name, "wb") as output:
                    voice.synthesize_wav(sentence, output, syn_config=self.config)
                play_wave(handle.name, generation)
            time.sleep(self.pause / 1000)
