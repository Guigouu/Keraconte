"""Moteur Piper : trois canaux de voix, découpés par phrases."""

import sys
import time
import wave

from keraconte.engines import Engine
from keraconte.genre import Canal
from keraconte.playback import play_wave, playback, wav_temporaire
from keraconte.text import pronounce, speakable, split_sentences


class PiperEngine(Engine):
    """Trois voix — PNJ masculin, PNJ féminin, narration — qui marquent mal
    la ponctuation.

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
        # On garde une référence aux classes pour ne pas réimporter « piper »
        # à chaud (l'import reste tardif, mais fait une seule fois ici).
        self.vitesse = vitesse
        self._SynthesisConfig = SynthesisConfig
        self._PiperVoice = PiperVoice
        self.pause = pause
        # « voices » : {Canal: « chemin.onnx[#locuteur] »}. Le « #locuteur »
        # sert aux modèles multi-locuteurs (upmc : jessica, pierre), résolu
        # via le speaker_id_map de la config de la voix.
        self.specs = dict(voices)
        self._chargees = {}
        self._replis_annonces = set()
        # Masculin et narration se chargent TOUT DE SUITE : ce sont les voix
        # d'avant l'ADR-0001, et une voix absente doit échouer au lancement,
        # pas à la première réplique — comportement inchangé. La FÉMININE se
        # charge à la première réplique féminine : nouvelle, souvent pas
        # encore téléchargée, son absence se replie sur la voix masculine
        # (voir « _voix ») au lieu d'empêcher le programme de démarrer.
        for canal in (Canal.PNJ_MASCULIN, Canal.NARRATION):
            self._chargees[canal] = self._charger(self.specs[canal])

    @staticmethod
    def _separer(spec):
        """Découpe « chemin.onnx#locuteur » en (chemin, locuteur ou None)."""
        chemin, _, locuteur = str(spec).partition("#")
        return chemin, (locuteur or None)

    def _charger(self, spec):
        """Charge une voix et résout son locuteur. Renvoie (voix, speaker_id).

        Un locuteur demandé mais inconnu du modèle se signale et retombe sur
        le locuteur par défaut du modèle : une faute de frappe ne doit pas
        rendre le canal muet.
        """
        chemin, locuteur = self._separer(spec)
        voix = self._PiperVoice.load(chemin)
        speaker_id = None
        if locuteur is not None:
            carte = getattr(getattr(voix, "config", None), "speaker_id_map", None) or {}
            speaker_id = carte.get(locuteur)
            if speaker_id is None:
                print(
                    f"locuteur « {locuteur} » inconnu de {chemin} : "
                    "locuteur par défaut du modèle (voir --list-voices)",
                    file=sys.stderr,
                )
        return voix, speaker_id

    def _voix(self, canal):
        """Voix du canal, chargée au premier besoin ; repli si elle manque.

        Le repli — la voix masculine, c'est-à-dire le comportement d'avant —
        s'annonce UNE fois : un joueur sans la voix féminine téléchargée doit
        savoir pourquoi tous les PNJ gardent la même voix, pas le relire à
        chaque réplique.
        """
        if canal in self._chargees:
            return self._chargees[canal]
        try:
            self._chargees[canal] = self._charger(self.specs[canal])
        except Exception as erreur:
            if canal not in self._replis_annonces:
                self._replis_annonces.add(canal)
                print(
                    f"voix {canal.name} indisponible ({erreur}) : repli sur la "
                    "voix par défaut. « python -m piper.download_voices "
                    "fr_FR-upmc-medium » l'installe (voir README).",
                    file=sys.stderr,
                )
            self._chargees[canal] = self._chargees[Canal.PNJ_MASCULIN]
        return self._chargees[canal]

    def speak(self, text, canal, generation):
        voice, speaker_id = self._voix(canal)
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
            # « speaker_id » n'a d'effet que sur un modèle multi-locuteurs ;
            # None laisse le locuteur par défaut (cas des voix mono-locuteur).
            config = self._SynthesisConfig(
                length_scale=1 / self.vitesse.valeur, speaker_id=speaker_id
            )
            with wav_temporaire() as path:
                with wave.open(path, "wb") as output:
                    voice.synthesize_wav(sentence, output, syn_config=config)
                play_wave(path, generation)
