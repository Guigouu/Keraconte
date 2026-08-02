"""Masquage de la fenêtre console (Windows), et son bouton de bascule.

L'exe est construit avec « console=True » à dessein, et NON en mode fenêtré :
le smoke test de la CI lit la sortie de « --test » sur stdout, et un build
« windowed » n'a pas de stdout du tout (PyInstaller met « sys.stdout » à None,
où le moindre « print » lève). On garde donc la console — mais on la CACHE au
démarrage, puisqu'elle n'a rien à faire devant le joueur.

Tout est no-op hors Windows : sous Linux le programme est lancé depuis un
terminal que l'application n'a aucun droit de faire disparaître.
"""

import sys


def disponible():
    """Y a-t-il une fenêtre console à piloter ? (Windows seulement)"""
    if sys.platform != "win32":
        return False
    return _fenetre() != 0


def _fenetre():
    """Poignée de la fenêtre console, ou 0 s'il n'y en a pas.

    Un processus Windows lancé sans console (double-clic sur un build fenêtré)
    renvoie 0 : il n'y a alors rien à montrer ni à cacher.
    """
    import ctypes

    return ctypes.windll.kernel32.GetConsoleWindow()


# Constantes de l'API Win32 « ShowWindow ».
SW_HIDE = 0
SW_SHOW = 5


def montrer(visible):
    """Affiche ou masque la fenêtre console. Sans effet hors Windows.

    Renvoie l'état effectivement appliqué : « False » si rien n'a pu être fait
    (pas de console), pour que l'appelant n'affiche pas un bouton mensonger.
    """
    if not disponible():
        return False
    import ctypes

    ctypes.windll.user32.ShowWindow(_fenetre(), SW_SHOW if visible else SW_HIDE)
    return visible


def masquer_au_demarrage():
    """Cache la console dès le lancement de l'interface graphique.

    Appelé UNIQUEMENT depuis le chemin overlay : « --test » et « --dire » sont
    des sorties texte (la CI les lit), et leur cacher la console n'aurait aucun
    sens. Renvoie True si une console existe et a été masquée — c'est le signal
    qu'un bouton de bascule a lieu d'être.
    """
    if not disponible():
        return False
    montrer(False)
    return True
