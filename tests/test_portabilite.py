"""Garde-fous de portabilité multi-plateforme (Windows + Linux).

Ces tests protègent les invariants qui rendent le paquet importable et
lançable hors Linux. Ils tournent SOUS Linux (où gi/dbus sont présents) mais
simulent leur absence, façon proxy Windows — analogue à la garde structurelle
du bug NamedTemporaryFile.
"""

import importlib
import os
import pathlib
import sys
from unittest import mock

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


def test_qr_tesseract_prime_sur_le_path():
    """« QR_TESSERACT » impose le binaire tesseract, avant le PATH.

    Sous Windows l'installeur ne touche pas au PATH : cette variable est
    l'échappatoire pour désigner le binaire. On vérifie qu'elle prend le pas.
    """
    import quest_reader.detection as detection

    ancien = detection.pytesseract.pytesseract.tesseract_cmd
    try:
        with mock.patch.dict(os.environ, {"QR_TESSERACT": "/chemin/bidon/tesseract"}):
            detection.configurer_tesseract()
        assert (
            detection.pytesseract.pytesseract.tesseract_cmd
            == "/chemin/bidon/tesseract"
        )
    finally:
        detection.pytesseract.pytesseract.tesseract_cmd = ancien


def test_les_chemins_de_voix_sont_natifs_par_os():
    """Les chemins de modèles passent par platformdirs, pas par un ~/.local codé.

    Sous Linux, la racine reste ~/.local/share (dossiers piper-voices/ et
    kokoro/ inchangés — pas de rupture) ; le point vérifié ici est qu'ils
    dérivent bien de platformdirs.user_data_dir, donc natifs ailleurs.
    """
    import platformdirs

    from quest_reader.engines import KOKORO_DIR, VOICES

    racine = pathlib.Path(platformdirs.user_data_dir(appname=False))
    assert VOICES == racine / "piper-voices"
    assert KOKORO_DIR == racine / "kokoro"
