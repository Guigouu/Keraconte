"""Backend de capture multiplateforme via mss (Windows, macOS).

Miroir de « capture_linux » sans le portail ni GStreamer : mss capture un
moniteur entier, on convertit en BGR et on alimente « on_frame ». Pas de boucle
GLib — une boucle synchrone cadencée à « fps », qui s'auto-régule exactement
comme la « queue leaky=downstream » du pipeline Linux : appeler « on_frame »
en ligne bloque le temps de l'OCR, donc on prend toujours l'image la plus
FRAÎCHE, sans accumuler de retard.

mss n'est PAS thread-safe (poignées de contexte par thread sous Windows) :
l'instance est créée DANS la boucle (le thread de capture), jamais dans
« demarrer_capture » (le thread Qt). Toute interaction inter-thread (arrêt,
re-sélection) passe par un drapeau lu en tête de boucle, jamais par un appel
direct à mss depuis l'autre thread.
"""

import threading
import time

import numpy as np


class MssCapture:
    """Capture un moniteur via mss et alimente « on_frame » en images BGR.

    Interface identique au backend Linux : demarrer_capture / boucler /
    arreter / demander_reselection. « on_stop() » est exécuté à la fin de la
    boucle (arrêt du Speaker, que reader.py ne pilote plus). « args.fps » cadence.
    """

    def __init__(self, on_frame, args, on_stop=None):
        self.on_frame = on_frame
        self.args = args
        self.on_stop = on_stop
        # Index du moniteur dans mss.monitors. 1 = premier écran physique ;
        # monitors[0] est l'UNION de tous les écrans, à ne pas capturer : sa
        # géométrie doublée fausserait les seuils de détection calibrés sur un
        # seul écran (cf. mémoire seuils-pixels-absolus).
        self._moniteur = 1
        # Re-sélection demandée depuis le thread Qt : on ne touche pas mss là,
        # on pose l'intention, la boucle l'applique avant la prochaine capture.
        self._changer_moniteur = False
        # Arrêt interruptible : « wait » dort mais se réveille dès « set() »,
        # donc « join » côté Qt revient vite (pas de time.sleep bloquant).
        self._arret = threading.Event()

    def demarrer_capture(self):
        """Prépare la capture. NE crée PAS l'instance mss (thread Qt ici).

        mss vit entièrement dans « boucler » (thread de capture) : rien à
        ouvrir sur le thread principal. Présent pour l'uniformité d'interface.
        """
        print("Capture mss prête. Ctrl+C pour arrêter.", flush=True)

    def boucler(self):
        """Boucle de capture (thread dédié) : grab → BGR → on_frame, cadencé.

        L'instance mss est créée ICI et n'est manipulée que par ce thread.
        Le délai est le RESTE après « on_frame » (et non un 1/fps plat) : un
        cycle rapide vise quand même la cadence, un cycle lent (OCR long) ne
        dort pas et enchaîne — l'auto-régulation du pipeline Linux.
        """
        import mss

        periode = 1.0 / max(self.args.fps, 1)
        try:
            with mss.MSS() as sct:
                while not self._arret.is_set():
                    debut = time.perf_counter()
                    # Re-sélection en attente : on l'applique AVANT de capturer.
                    if self._changer_moniteur:
                        self._changer_moniteur = False
                        self._moniteur = self._moniteur_suivant(sct)
                    moniteur = sct.monitors[self._moniteur]
                    shot = sct.grab(moniteur)
                    self.on_frame(self._en_bgr(shot))
                    # Reste à dormir pour tenir la cadence ; jamais négatif.
                    reste = periode - (time.perf_counter() - debut)
                    if reste > 0:
                        # « wait » rend la main dès l'arrêt demandé.
                        self._arret.wait(reste)
        finally:
            if self.on_stop is not None:
                self.on_stop()

    @staticmethod
    def _en_bgr(shot):
        """Convertit une capture mss (BGRA) en tableau BGR contigu.

        Le tampon brut de mss est réutilisé d'une capture à l'autre et la
        tranche « :3 » n'est pas contiguë : la copie n'est PAS optionnelle
        (même raison que le « frame.copy() » du backend Linux).
        """
        raw = np.frombuffer(shot.raw, np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(raw[:, :, :3])

    def _moniteur_suivant(self, sct):
        """Passe au moniteur physique suivant, en bouclant.

        On ne parcourt que « monitors[1:] » (écrans réels), jamais l'union
        monitors[0]. Sous Windows/macOS il n'y a pas de sélecteur de source
        façon portail : re-sélectionner = changer d'écran.
        """
        nb_ecrans = len(sct.monitors) - 1  # hors union monitors[0]
        if nb_ecrans <= 1:
            return self._moniteur  # un seul écran : rien à changer
        # 1..nb_ecrans, en cyclant.
        return (self._moniteur % nb_ecrans) + 1

    def arreter(self):
        """Demande l'arrêt de la boucle (appelé depuis le thread Qt)."""
        self._arret.set()

    def demander_reselection(self):
        """Demande de passer à l'écran suivant (appelé depuis le thread Qt).

        On ne touche pas mss ici (autre thread) : on pose le drapeau, la
        boucle l'applique en tête d'itération, sur son propre thread.
        """
        self._changer_moniteur = True
