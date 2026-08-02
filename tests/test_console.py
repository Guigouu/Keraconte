"""Tests du masquage de la console (keraconte.console).

Windows n'est pas là pour tourner : on double « ctypes.windll » et l'on
vérifie le CONTRAT — quelle constante ShowWindow est passée, et que rien ne se
produit hors Windows (où le terminal appartient à l'utilisateur).
"""

import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte import console  # noqa: E402


class _FauxWindll:
    """Double de « ctypes.windll » : journalise les appels Win32."""

    def __init__(self, poignee=1234):
        self.poignee = poignee
        self.appels = []
        self.kernel32 = self._Kernel32(self)
        self.user32 = self._User32(self)

    class _Kernel32:
        def __init__(self, parent):
            self.parent = parent

        def GetConsoleWindow(self):
            return self.parent.poignee

    class _User32:
        def __init__(self, parent):
            self.parent = parent

        def ShowWindow(self, poignee, commande):
            self.parent.appels.append((poignee, commande))


def _sous_windows(faux):
    """Contexte : on est sous Windows, avec « ctypes.windll » doublé."""
    ctypes_double = mock.MagicMock()
    ctypes_double.windll = faux
    return mock.patch.object(console.sys, "platform", "win32"), mock.patch.dict(
        sys.modules, {"ctypes": ctypes_double}
    )


def test_hors_windows_rien_n_est_touche():
    """Sous Linux, le terminal appartient à l'utilisateur : on n'y touche pas."""
    with mock.patch.object(console.sys, "platform", "linux"):
        assert console.disponible() is False
        assert console.masquer_au_demarrage() is False
        assert console.montrer(True) is False


def test_masquer_au_demarrage_cache_la_console():
    """Au lancement de l'interface, la console disparaît (SW_HIDE)."""
    faux = _FauxWindll()
    plateforme, modules = _sous_windows(faux)
    with plateforme, modules:
        assert console.masquer_au_demarrage() is True
    assert faux.appels == [(1234, console.SW_HIDE)]


def test_montrer_rouvre_la_console():
    """Le bouton de bascule doit pouvoir la faire revenir (SW_SHOW)."""
    faux = _FauxWindll()
    plateforme, modules = _sous_windows(faux)
    with plateforme, modules:
        assert console.montrer(True) is True
    assert faux.appels == [(1234, console.SW_SHOW)]


def test_sans_console_il_n_y_a_rien_a_basculer():
    """GetConsoleWindow renvoie 0 : aucun appel, et le bouton n'a pas lieu d'être.

    Cas d'un processus Windows lancé sans console attachée : prétendre la
    montrer afficherait un bouton qui ne fait rien.
    """
    faux = _FauxWindll(poignee=0)
    plateforme, modules = _sous_windows(faux)
    with plateforme, modules:
        assert console.disponible() is False
        assert console.masquer_au_demarrage() is False
        assert console.montrer(True) is False
    assert faux.appels == []
