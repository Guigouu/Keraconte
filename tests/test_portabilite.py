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
import threading
import types
from unittest import mock

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _faux_mss(largeur=64, hauteur=48, nb_ecrans=2):
    """Double la lib « mss » : deux écrans, des captures BGRA reproductibles.

    Chaque « grab » renvoie un objet à « raw »/« width »/« height » comme le
    vrai mss (tampon BGRA). L'alpha est mis à une valeur repérable (200) pour
    vérifier qu'elle est bien retirée en sortie (BGR, 3 canaux).
    """
    grabs = []

    class FausseCapture:
        def __init__(self, w, h):
            self.width, self.height = w, h
            pixel = bytes((10, 20, 30, 200))  # B, G, R, A
            self.raw = pixel * (w * h)

    class FausseMSS:
        def __init__(self):
            # monitors[0] = union ; monitors[1:] = écrans physiques.
            self.monitors = [{"left": 0, "top": 0, "width": largeur * nb_ecrans,
                              "height": hauteur}]
            for i in range(nb_ecrans):
                self.monitors.append(
                    {"left": largeur * i, "top": 0, "width": largeur, "height": hauteur}
                )

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def grab(self, moniteur):
            grabs.append(moniteur)
            return FausseCapture(moniteur["width"], moniteur["height"])

    module = types.ModuleType("mss")
    module.MSS = FausseMSS
    return module, grabs


def test_import_keraconte_sans_gi_ni_dbus():
    """« import keraconte » doit réussir quand gi et dbus sont absents.

    C'est le verrou du portage : reader.py et __init__.py tiraient gi/dbus au
    niveau module, donc importer le paquet échouait sur Windows/macOS et la
    suite de tests ne tournait pas. Le plumbing Linux vit désormais dans
    capture_linux, importé paresseusement par la factory. On simule ici un
    environnement sans python-gobject/dbus en les rendant inimportables.
    """
    sauvegarde = dict(sys.modules)
    try:
        for name in list(sys.modules):
            if name.startswith("keraconte") or name in ("gi", "dbus"):
                del sys.modules[name]
        # None dans sys.modules force un ImportError à l'import (comme absent).
        sys.modules["gi"] = None
        sys.modules["dbus"] = None

        paquet = importlib.import_module("keraconte")
        assert hasattr(paquet, "Reader")
        # reader.py lui-même ne doit tirer aucun des deux.
        importlib.import_module("keraconte.reader")
        # La factory non plus (elle importe le backend paresseusement).
        importlib.import_module("keraconte.capture_factory")
    finally:
        sys.modules.clear()
        sys.modules.update(sauvegarde)


def test_reader_module_ne_reference_ni_gi_ni_dbus():
    """Garde structurelle : reader.py ne doit plus mentionner gi/dbus/Gst.

    Le test d'import ci-dessus attrape la régression à l'exécution ; celui-ci
    la pointe à la source, plus lisible en cas d'échec.
    """
    import keraconte.reader as reader_mod

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
    import keraconte.detection as detection

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

    from keraconte.engines import KOKORO_DIR, VOICES

    racine = pathlib.Path(platformdirs.user_data_dir(appname=False))
    assert VOICES == racine / "piper-voices"
    assert KOKORO_DIR == racine / "kokoro"


# --- Backend de capture mss (Windows/macOS) ---------------------------------
# On double « mss » : le vrai rend un écran noir sous XWayland (max=0), et le
# contrat qui compte est indépendant du contenu — sortie BGR, cadence,
# arrêt/re-sélection inter-thread. Ces tests tournent sur les 3 OS.


def _args_capture(fps=1000):
    # fps très haut => période ~0 => la boucle n'attend pas, le test file.
    return types.SimpleNamespace(fps=fps)


def test_mss_convertit_en_bgr_trois_canaux():
    """La capture BGRA de mss ressort en BGR contigu (3 canaux, alpha retirée)."""
    faux_mss, _ = _faux_mss()
    with mock.patch.dict(sys.modules, {"mss": faux_mss}):
        from keraconte.capture_mss import MssCapture

        recues = []

        def au_frame(frame):
            recues.append(frame)
            cap.arreter()  # une seule image suffit

        cap = MssCapture(au_frame, _args_capture())
        cap.boucler()

    frame = recues[0]
    assert frame.shape[2] == 3  # BGR, plus d'alpha
    assert frame.flags["C_CONTIGUOUS"]  # copie contiguë, pas une vue du tampon
    # Le pixel BGRA (10,20,30,200) doit devenir BGR (10,20,30).
    assert tuple(frame[0, 0]) == (10, 20, 30)


def test_mss_arreter_termine_la_boucle_et_tire_on_stop():
    """arreter() (thread Qt) fait sortir la boucle vite ; on_stop tiré une fois."""
    faux_mss, _ = _faux_mss()
    with mock.patch.dict(sys.modules, {"mss": faux_mss}):
        from keraconte.capture_mss import MssCapture

        arrets = []
        cap = MssCapture(lambda f: None, _args_capture(fps=50),
                         on_stop=lambda: arrets.append(1))
        fil = threading.Thread(target=cap.boucler)
        fil.start()
        cap.arreter()  # depuis « l'autre thread », comme le bouton ✕
        fil.join(timeout=5)

    assert not fil.is_alive()  # la boucle s'est bien arrêtée
    assert arrets == [1]  # on_stop exactement une fois


def test_mss_reselection_change_de_moniteur_a_l_iteration_suivante():
    """demander_reselection() (thread Qt) fait passer à l'écran suivant.

    Le drapeau est posé depuis l'extérieur et consommé EN TÊTE de boucle, avant
    la capture — jamais d'appel mss inter-thread.
    """
    faux_mss, grabs = _faux_mss(largeur=64, hauteur=48, nb_ecrans=2)
    with mock.patch.dict(sys.modules, {"mss": faux_mss}):
        from keraconte.capture_mss import MssCapture

        cap = MssCapture(lambda f: None, _args_capture())
        etat = {"n": 0}

        def au_frame(_frame):
            etat["n"] += 1
            if etat["n"] == 1:
                cap.demander_reselection()  # demandée après la 1re capture
            elif etat["n"] >= 2:
                cap.arreter()

        cap.on_frame = au_frame
        cap.boucler()

    # 1re capture sur l'écran 1 (left=0), 2e sur l'écran 2 (left=64).
    assert grabs[0]["left"] == 0
    assert grabs[1]["left"] == 64


def test_le_vrai_mss_expose_bien_MSS():
    """La classe « mss.MSS » que « boucler » appelle existe dans le vrai paquet.

    Les 3 tests ci-dessus DOUBLENT mss : ils passeraient même si le vrai paquet
    n'avait pas d'attribut « MSS » (renommage de « mss.mss » en 10.x). Ce test
    importe le VRAI module — mss est pur-Python et s'installe aussi sous Linux —
    et vérifie le seul symbole dont dépend « boucler ». C'est le garde-fou qui
    attrape un floor de version trop bas AVANT le jeu (même classe de bug que
    NamedTemporaryFile : démarre bien, meurt au 1er usage). Cf. pyproject
    « mss>=10.0 » : c'est la version qui garantit « MSS » en majuscule.
    """
    import mss

    assert hasattr(mss, "MSS"), (
        "le vrai paquet mss n'expose pas « MSS » : « boucler » appelle "
        "« mss.MSS() ». Vérifier le floor de version dans pyproject.toml."
    )


def test_factory_route_vers_mss_sur_windows_et_macos():
    """make_capture rend un MssCapture sous win32/darwin, un LinuxCapture sous linux.

    La branche win32/darwin de la factory n'a AUCUNE couverture sinon : la
    branche Linux est exercée implicitement par le reste de la suite, la
    nouvelle non. On simule mss (absent en dev) et la plateforme.
    """
    from keraconte import capture_factory

    faux_mss, _ = _faux_mss()
    args = _args_capture()
    with mock.patch.dict(sys.modules, {"mss": faux_mss}):
        for plateforme in ("win32", "darwin"):
            with mock.patch.object(sys, "platform", plateforme):
                cap = capture_factory.make_capture(lambda f: None, args)
                assert type(cap).__name__ == "MssCapture", plateforme
