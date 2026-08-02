"""Vitesse de parole partagée entre l'overlay et le moteur de synthèse.

Feuille du DAG : aucun import du package, comme « state ». L'overlay (thread
Qt) MUTE la vitesse via « augmenter »/« diminuer » ; le moteur (thread
« Speaker ») la LIT à chaque réplique via « valeur ». Un « Lock » protège
l'accès concurrent : ce ne sont que des flottants Python, mais l'un écrit
pendant que l'autre lit, donc on synchronise.

Le débit change ainsi À CHAUD, sans reconstruire le moteur — reconstruire
rechargerait un modèle (jusqu'à 83 s pour XTTS). Le changement prend effet dès
la phrase suivante de la réplique en cours : les moteurs relisent « valeur » à
chaque phrase (Piper reconstruit sa config, XTTS et Kokoro passent le débit).
Un audio déjà remis à la lecture ne peut plus changer — la phrase est donc la
granularité la plus fine atteignable.
"""

import threading

MIN = 0.5
MAX = 2.5
PAS = 0.1


def _borner(valeur):
    """Ramène la valeur dans [MIN, MAX], arrondie à deux décimales.

    L'arrondi évite la dérive flottante : sans lui, additionner 0.1 dix fois
    ne redonnerait pas exactement la valeur de départ après dix baisses.
    """
    return round(max(MIN, min(MAX, valeur)), 2)


class Vitesse:
    """Un débit de parole, borné à [MIN, MAX], protégé par un « Lock »."""

    def __init__(self, valeur):
        self._verrou = threading.Lock()
        self._valeur = _borner(valeur)

    @property
    def valeur(self):
        with self._verrou:
            return self._valeur

    def augmenter(self):
        """Accélère d'un PAS, sans franchir MAX."""
        with self._verrou:
            self._valeur = _borner(self._valeur + PAS)

    def diminuer(self):
        """Ralentit d'un PAS, sans franchir MIN."""
        with self._verrou:
            self._valeur = _borner(self._valeur - PAS)

    def au_maximum(self):
        """Vrai si l'on est à la borne haute (tolérance flottante)."""
        with self._verrou:
            return self._valeur >= MAX - 1e-9

    def au_minimum(self):
        """Vrai si l'on est à la borne basse (tolérance flottante)."""
        with self._verrou:
            return self._valeur <= MIN + 1e-9
