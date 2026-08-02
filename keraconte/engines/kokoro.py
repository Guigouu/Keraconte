"""Moteur Kokoro : une seule voix française, sur le processeur."""

from keraconte.engines import KOKORO_MODEL, KOKORO_VOICES, Engine
from keraconte.genre import Canal
from keraconte.playback import play_wave, wav_temporaire
from keraconte.text import pronounce, speakable


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

    def __init__(self, vitesse):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        # Vitesse partagée, mutée par l'overlay : relue à chaque « speak »
        # pour que le débit change à chaud, sans reconstruire le moteur.
        self.vitesse = vitesse

    def speak(self, text, canal, generation):
        import soundfile

        spoken = pronounce(text)
        # Sans phonème à concaténer, « create » lève au lieu de se taire.
        if not speakable(spoken):
            return
        speed = self.vitesse.valeur
        # Kokoro est HORS adaptation de genre (ADR-0001) : une seule voix
        # française dans le modèle. PNJ_MASCULIN et PNJ_FEMININ sonnent donc
        # pareil ; seule la narration se distingue, par le débit.
        if canal is Canal.NARRATION:
            speed *= self.NARRATION_SLOWDOWN
        samples, rate = self.kokoro.create(
            spoken, voice=self.VOICE, lang="fr-fr", speed=speed
        )
        with wav_temporaire() as path:
            soundfile.write(path, samples, rate)
            play_wave(path, generation)
