"""Garde-fous de portabilité multi-plateforme (Windows + Linux).

Ces tests protègent les invariants qui rendent le paquet importable et
lançable hors Linux. Ils tournent SOUS Linux (où gi/dbus sont présents) mais
simulent leur absence, façon proxy Windows — analogue à la garde structurelle
du bug NamedTemporaryFile.
"""

import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def test_import_quest_reader_sans_gi_ni_dbus():
    """« import quest_reader » doit réussir quand gi et dbus sont absents.

    C'est le verrou du portage : reader.py et __init__.py tiraient gi/dbus au
    niveau module, donc importer le paquet échouait sur Windows/macOS et la
    suite de tests ne tournait pas. Le plumbing Linux vit désormais dans
    capture_linux, importé paresseusement par la factory. On simule ici un
    environnement sans python-gobject/dbus en les rendant inimportables.
    """
    sauvegarde = dict(sys.modules)
    try:
        for name in list(sys.modules):
            if name.startswith("quest_reader") or name in ("gi", "dbus"):
                del sys.modules[name]
        # None dans sys.modules force un ImportError à l'import (comme absent).
        sys.modules["gi"] = None
        sys.modules["dbus"] = None

        paquet = importlib.import_module("quest_reader")
        assert hasattr(paquet, "Reader")
        # reader.py lui-même ne doit tirer aucun des deux.
        importlib.import_module("quest_reader.reader")
        # La factory non plus (elle importe le backend paresseusement).
        importlib.import_module("quest_reader.capture_factory")
    finally:
        sys.modules.clear()
        sys.modules.update(sauvegarde)


def test_reader_module_ne_reference_ni_gi_ni_dbus():
    """Garde structurelle : reader.py ne doit plus mentionner gi/dbus/Gst.

    Le test d'import ci-dessus attrape la régression à l'exécution ; celui-ci
    la pointe à la source, plus lisible en cas d'échec.
    """
    import quest_reader.reader as reader_mod

    source = pathlib.Path(reader_mod.__file__).read_text(encoding="utf-8")
    for interdit in ("import gi", "import dbus", "gi.repository", "Gst."):
        assert interdit not in source, (
            f"reader.py référence « {interdit} » : le plumbing Linux doit "
            "vivre dans capture_linux, pas dans l'orchestration agnostique."
        )
