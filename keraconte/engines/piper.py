"""Moteur Piper : voix masculine rapide, découpée par phrases."""

import time
import wave

from keraconte.engines import Engine
from keraconte.playback import play_wave, playback, wav_temporaire
from keraconte.text import pronounce, speakable, split_sentences


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
        # CHAQUE phrase (voir la boucle de « speak »), pour que le débit change
        # à chaud, dès la phrase suivante de la réplique en cours.
        # On garde une référence à la classe pour ne pas réimporter « piper »
        # à chaud (l'import reste tardif, mais fait une seule fois ici).
        self.vitesse = vitesse
        self._SynthesisConfig = SynthesisConfig
        self.voices = {kind: PiperVoice.load(path) for kind, path in voices.items()}
        self.pause = pause

    def speak(self, text, narration, generation):
        voice = self.voices["narration" if narration else "dialogue"]
        premiere = True
        for sentence in split_sentences(pronounce(text)):
            # Le découpage isole parfois une ponctuation seule (« Ah… ! »).
            if not speakable(sentence):
                continue
            if generation != playback.generation:  # nouveau dialogue survenu
                return
            # La pause sépare deux phrases : on la place EN TÊTE, sauf avant la
            # première. Elle ne s'exécute donc plus après la dernière phrase, où
            # elle n'ajoutait qu'un silence mort avant que la voix se rende (320
            # ms par défaut) — sans rien séparer.
            if not premiere:
                time.sleep(self.pause / 1000)
            premiere = False
            # Piper raisonne en durée : au-dessus de 1, il ralentit. On expose
            # un débit, donc on inverse. Recalculé À CHAQUE phrase, et non une
            # fois avant la boucle : muter la vitesse au milieu d'une réplique
            # prend alors effet dès la phrase suivante. L'objet de config est
            # léger, le modèle .onnx reste chargé, rien n'est rechargé.
            config = self._SynthesisConfig(length_scale=1 / self.vitesse.valeur)
            with wav_temporaire() as path:
                with wave.open(path, "wb") as output:
                    voice.synthesize_wav(sentence, output, syn_config=config)
                play_wave(path, generation)
