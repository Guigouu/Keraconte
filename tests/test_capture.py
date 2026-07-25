"""Tests de la re-sélection de la source (quest_reader.reader + capture).

Le vrai portail demande Wayland et une interaction ; on double « ScreenCast »
et l'oubli du jeton pour vérifier l'ORDRE du redémarrage — c'est lui le bug
silencieux : recréer une session sans fermer l'ancienne, ou sans oublier le
jeton, échoue sans erreur visible.
"""

import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader import Reader  # noqa: E402


class _FauxCast:
    """Tient le rôle de ScreenCast : note les fermetures et les démarrages."""

    journal = []  # partagé : on veut l'ordre entre l'ancien et le nouveau

    def __init__(self, on_node):
        self.on_node = on_node

    def close(self):
        _FauxCast.journal.append("close")

    def start(self):
        _FauxCast.journal.append("start")


def test_la_reselection_ferme_oublie_puis_redemarre():
    """L'ordre voulu : fermer l'ancienne session, oublier le jeton, redémarrer.

    Fermer après avoir recréé entrerait en collision de session côté portail ;
    ne pas oublier le jeton ferait réutiliser l'ancien choix sans sélecteur.
    """
    _FauxCast.journal = []
    reader = Reader.__new__(Reader)
    reader.cast = _FauxCast(on_node=None)  # l'ancienne session
    reader.pipeline = None

    ordre = []
    with mock.patch("quest_reader.reader.ScreenCast", _FauxCast), mock.patch(
        "quest_reader.reader.forget_token", side_effect=lambda: ordre.append("forget")
    ):
        # « close » de l'ancienne va dans le journal partagé ; on veut le voir
        # AVANT l'oubli du jeton et AVANT le « start » de la nouvelle.
        vrai_close = reader.cast.close

        def close_et_note():
            ordre.append("close")
            vrai_close()

        reader.cast.close = close_et_note
        # Le « start » de la NOUVELLE session : on l'intercepte au niveau classe.
        with mock.patch.object(
            _FauxCast, "start", lambda self: ordre.append("start")
        ):
            resultat = reader._reselectionner()

    assert ordre == ["close", "forget", "start"]
    assert resultat is False  # idle_add ne doit pas répéter


def test_la_reselection_installe_une_nouvelle_session():
    """Après re-sélection, « reader.cast » est une nouvelle instance."""
    reader = Reader.__new__(Reader)
    ancienne = _FauxCast(on_node=None)
    reader.cast = ancienne
    reader.pipeline = None

    with mock.patch("quest_reader.reader.ScreenCast", _FauxCast), mock.patch(
        "quest_reader.reader.forget_token"
    ):
        reader._reselectionner()

    assert reader.cast is not ancienne
    assert isinstance(reader.cast, _FauxCast)
