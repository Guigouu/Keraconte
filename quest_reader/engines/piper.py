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

    def __init__(self, voices, vitesse, pause):
        from piper import PiperVoice, SynthesisConfig

        # Vitesse partagée, mutée par l'overlay. À la différence des autres
        # moteurs, Piper attend un objet de configuration (length_scale), pas
        # un simple débit relu : on reconstruit donc « SynthesisConfig » à
        # CHAQUE « speak » (voir plus bas), pour que le débit change à chaud.
        # On garde une référence à la classe pour ne pas réimporter « piper »
        # à chaud (l'import reste tardif, mais fait une seule fois ici).
        self.vitesse = vitesse
        self._SynthesisConfig = SynthesisConfig
        self.voices = {kind: PiperVoice.load(path) for kind, path in voices.items()}
        self.pause = pause

    def speak(self, text, narration, generation):
        voice = self.voices["narration" if narration else "dialogue"]
        # Piper raisonne en durée : au-dessus de 1, il ralentit. On expose un
        # débit, donc on inverse. Recalculé ici, et non figé à la construction,
        # pour lire la vitesse courante — l'objet de config est léger, le
        # modèle .onnx reste chargé dans « self.voices », rien n'est rechargé.
        config = self._SynthesisConfig(length_scale=1 / self.vitesse.valeur)
        for sentence in split_sentences(pronounce(text)):
            # Le découpage isole parfois une ponctuation seule (« Ah… ! »).
            if not speakable(sentence):
                continue
            if generation != playback.generation:  # nouveau dialogue survenu
                return
            with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
                with wave.open(handle.name, "wb") as output:
                    voice.synthesize_wav(sentence, output, syn_config=config)
                play_wave(handle.name, generation)
            time.sleep(self.pause / 1000)
