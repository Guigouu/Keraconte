"""Choisit le backend de capture selon la plateforme.

Ce module NE doit importer aucune dépendance spécifique à un OS au niveau
module — c'est lui qui casse la chaîne d'import : « reader.py » et
« __init__.py » ne tirent plus gi/dbus. L'import du backend est PARESSEUX,
fait dans la branche correspondante, pour qu'importer quest_reader sur une
plateforme sans python-gobject/dbus (Windows, macOS) réussisse.
"""

import sys


def make_capture(on_frame, args, on_stop=None):
    """Construit le backend de capture adapté à la plateforme courante.

    « on_frame(np.ndarray) » reçoit chaque image BGR ; « on_stop() » est
    exécuté à la fin de la boucle (arrêt propre du Speaker). Tous les backends
    exposent la même interface : demarrer_capture / boucler / arreter /
    demander_reselection.
    """
    if sys.platform.startswith("linux"):
        from quest_reader.capture_linux import LinuxCapture

        return LinuxCapture(on_frame, args, on_stop)
    # Windows / macOS : backend mss (à venir). L'erreur est explicite tant
    # qu'il n'est pas écrit, plutôt qu'un ImportError obscur.
    raise NotImplementedError(
        f"Aucun backend de capture pour la plateforme « {sys.platform} ». "
        "Le backend mss (Windows/macOS) n'est pas encore implémenté."
    )
