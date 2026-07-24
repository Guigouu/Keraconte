"""Moteur XTTS : clone deux voix sur la carte graphique.

« torch » et « transformers » sont importés tardivement, dans « __init__ » :
le venv du projet ne les a pas — ~3 Go pour XTTS seul — et les importer au
niveau module casserait le reste du programme, qui tourne sans eux.
"""

import concurrent.futures
import contextlib
import os
import tempfile

from quest_reader.engines import Engine
from quest_reader.playback import play_wave, playback
from quest_reader.text import pronounce, speakable, split_sentences


def voice_argument(voice):
    """Traduit une voix en argument pour XTTS.

    Le modèle embarque cinquante-huit voix humaines : les nommer donne un
    bien meilleur rendu que cloner un échantillon, surtout si celui-ci
    provient déjà d'une synthèse — les défauts s'y accumulent.
    """
    if os.path.isfile(voice):
        return {"speaker_wav": voice}
    return {"speaker": voice}


class XttsEngine(Engine):
    """Clone deux voix à partir d'échantillons WAV, sur la carte graphique.

    Mesuré sur RTX 3070 Ti : ratio 0,24× — la synthèse va quatre fois plus
    vite que la parole — pour 1,96 Go de VRAM. Le découpage par phrases,
    comme chez Piper, rend l'attente imperceptible malgré les 83 s de
    chargement initial, payées une seule fois dans le fil « Speaker ».
    """

    MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

    def __init__(self, samples, speed):
        # Import tardif, comme les autres moteurs : le venv du projet n'a
        # pas torch, et l'importer au niveau module casserait tout le reste.
        import torch
        import transformers.pytorch_utils as pu

        # Rustine obligatoire. Coqui importe « isin_mps_friendly » depuis
        # transformers, qui l'a retiré en 5.x : sans elle, « from TTS.api
        # import TTS » lève ImportError. XTTS ne s'en sert pas, mais le
        # module fautif (tortoise) est chargé au passage. Les arguments
        # sont passés par mot-clé, d'où cette signature exacte.
        if not hasattr(pu, "isin_mps_friendly"):
            pu.isin_mps_friendly = lambda elements, test_elements: torch.isin(
                elements, test_elements
            )

        from TTS.api import TTS

        self.tts = TTS(self.MODEL).to("cuda")
        self.samples = samples
        self.speed = speed
        # Un seul fil : deux synthèses simultanées se disputeraient la carte
        # sans rien gagner. Il ne sert qu'à prendre une phrase d'avance.
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def render(self, sentence, sample, path):
        # Pas de « no_grad » ici : Coqui l'applique déjà en interne. Mesuré —
        # douze répliques d'affilée, avec et sans, la mémoire reste plate à
        # 4,7 Go dans les deux cas.
        #
        # « speed » va déjà dans le sens du débit chez XTTS : au-dessus de 1,
        # plus rapide. Pas d'inversion, contrairement à Piper qui raisonne
        # en durée.
        self.tts.tts_to_file(
            text=sentence,
            language="fr",
            speed=self.speed,
            file_path=path,
            **voice_argument(sample),
        )

    def speak(self, text, narration):
        """Synthétise la phrase suivante pendant que la précédente se joue.

        « play_wave » bloque, et XTTS met environ une seconde et demie par
        phrase : les enchaîner bout à bout laissait un silence entre chacune,
        soit cinq trous dans une réplique un peu longue. Piper synthétise
        trop vite pour que cela s'entende, d'où le découpage naïf d'origine.
        """
        sample = self.samples["narration" if narration else "dialogue"]
        # Sans phonème, le moteur concatène une liste vide et lève.
        sentences = [
            sentence
            for sentence in split_sentences(pronounce(text))
            if speakable(sentence)
        ]
        with contextlib.ExitStack() as stack:
            files = [
                stack.enter_context(tempfile.NamedTemporaryFile(suffix=".wav"))
                for _ in sentences
            ]
            avance = None
            for position, sentence in enumerate(sentences):
                # Inutile d'occuper la carte pour un dialogue déjà fermé :
                # « Playback » refuserait de jouer le résultat.
                if playback.stopped:
                    break
                if avance is None:
                    self.render(sentence, sample, files[position].name)
                else:
                    avance.result()
                suivante = position + 1
                avance = (
                    self.pool.submit(
                        self.render, sentences[suivante], sample, files[suivante].name
                    )
                    if suivante < len(sentences)
                    else None
                )
                play_wave(files[position].name)
