# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller du fat exec keraconte (Windows + Linux).

UNE seule spec, paramétrée par « sys.platform » : le layout à poser sous
« sys._MEIPASS » est le même contrat sur les deux OS (le code de résolution est
commun), seules la provenance du binaire tesseract et la variable de chemin de
libs diffèrent.

Mode onedir (pas onefile) : le payload embarqué pèse ~0,5-1 Go ; onefile le
ré-extrairait dans un dossier temporaire à CHAQUE lancement (démarrage lent),
tandis que onedir fait de « dist/keraconte/ » la racine « _MEIPASS » — le
code de résolution (detection.configurer_tesseract, engines._racine_donnees)
la lit telle quelle, démarrage instantané.

Contrat de layout attendu par le code, posé à la racine du bundle :
    tesseract[.exe]            (detection.configurer_tesseract)
    tessdata/fra.traineddata   (idem, via TESSDATA_PREFIX)
    piper-voices/*.onnx(.json) (engines._racine_donnees)
    <libs natives de tesseract> (Linux : résolues par ldd ci-dessous)

La pile GStreamer/gi (Linux) n'est PAS embarquée : prérequis système (paquets
distro). L'exe Linux suppose donc gi/GStreamer/PipeWire installés ; l'exe
Windows est autonome (backend mss, pur-Python, aucune pile système).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# --- Localisation des ressources à embarquer --------------------------------
# La spec est invoquée depuis la racine du dépôt ; SPECPATH pointe packaging/.
RACINE = Path(SPECPATH).resolve().parent

WINDOWS = sys.platform == "win32"
EXE_NOM = "keraconte"

# Les TROIS voix du comportement par défaut (ADR-0002) : tom pour le PNJ
# masculin (et l'inconnu), upmc — multi-locuteurs, dont jessica — pour le PNJ
# féminin (ADR-0001), siwis pour le narrateur d'actions entre astérisques.
# Chaque voix = .onnx + .onnx.json (config obligatoire de Piper). Omettre
# siwis => narrateur muet ; omettre upmc => repli féminin sur la voix
# masculine (annoncé au joueur, mais autant embarquer la voix).
VOIX_DEFAUT = ["fr_FR-tom-medium", "fr_FR-siwis-medium", "fr_FR-upmc-medium"]


def _dossier_voix():
    """Où trouver les .onnx à embarquer, sur la machine de build.

    Priorité à QR_VOICES (le workflow CI y télécharge les voix), sinon la
    racine utilisateur locale via platformdirs (identique au runtime hors
    bundle : ~/.local/share/piper-voices sous Linux).
    """
    force = os.environ.get("QR_VOICES")
    if force:
        return Path(force)
    import platformdirs
    return Path(platformdirs.user_data_dir(appname=False)) / "piper-voices"


def _tessdata_source():
    """Localise le fichier fra.traineddata à embarquer.

    QR_TESSDATA (posé par la CI) prime ; sinon on sonde les emplacements
    usuels (TESSDATA_PREFIX, /usr/share/tessdata).
    """
    force = os.environ.get("QR_TESSDATA")
    candidats = []
    if force:
        candidats.append(Path(force))
    prefixe = os.environ.get("TESSDATA_PREFIX")
    if prefixe:
        candidats.append(Path(prefixe))
    candidats += [Path("/usr/share/tessdata"), Path("/usr/share/tesseract-ocr/5/tessdata")]
    for base in candidats:
        fra = base / "fra.traineddata"
        if fra.is_file():
            return fra
    raise SystemExit(
        "fra.traineddata introuvable : poser QR_TESSDATA vers le dossier tessdata."
    )


def _binaire_tesseract():
    """Chemin du binaire tesseract à embarquer (QR_TESSERACT prime, sinon PATH).

    Sous Windows, QR_TESSERACT est EXIGÉ et doit pointer le VRAI binaire
    (« C:\\Program Files\\Tesseract-OCR\\tesseract.exe ») : « shutil.which »
    renverrait le shim de chocolatey (dans ...\\chocolatey\\bin), inutile une
    fois copié et dont le voisinage ne contient AUCUNE des DLL de tesseract.
    On refuse donc le fallback which sous Windows pour ne pas empaqueter un exe
    OCR-muet.
    """
    force = os.environ.get("QR_TESSERACT")
    if force and Path(force).is_file():
        return Path(force)
    if WINDOWS:
        raise SystemExit(
            "Windows : QR_TESSERACT doit pointer le vrai tesseract.exe "
            "(p.ex. C:\\Program Files\\Tesseract-OCR\\tesseract.exe), pas le "
            "shim chocolatey. « which » ne convient pas ici."
        )
    trouve = shutil.which("tesseract")
    if not trouve:
        raise SystemExit(
            "tesseract introuvable : poser QR_TESSERACT ou l'installer sur le PATH."
        )
    return Path(trouve)


def _libs_tesseract_linux(binaire):
    """Résout dynamiquement les .so dont dépend tesseract, via ldd.

    On ne code PAS la liste en dur : la chaîne transitive (leptonica -> curl ->
    krb5/ssl...) diffère entre distros et runner CI. ldd sur la machine de
    build capture exactement ce qu'il faut. On écarte les libs système de base
    (libc, ld-linux, libm, pthread...) que l'OS cible fournit toujours.
    """
    base_systeme = (
        "libc.so", "ld-linux", "libm.so", "libpthread", "libdl.so",
        "librt.so", "ld-linux-x86-64",
    )
    binaries = []
    try:
        sortie = subprocess.check_output(["ldd", str(binaire)], text=True)
    except (OSError, subprocess.CalledProcessError):
        return binaries
    for ligne in sortie.splitlines():
        if "=>" not in ligne:
            continue
        chemin = ligne.split("=>")[1].strip().split(" ")[0]
        if not chemin or not os.path.isfile(chemin):
            continue
        nom = os.path.basename(chemin)
        if any(nom.startswith(p) for p in base_systeme):
            continue
        # Posées à la racine du bundle ; le runtime-hook pointe LD_LIBRARY_PATH
        # dessus pour le PROCESS tesseract externe (PyInstaller ne le patche pas).
        binaries.append((chemin, "."))
    return binaries


# --- Assemblage datas / binaries --------------------------------------------
tesseract = _binaire_tesseract()
dossier_voix = _dossier_voix()
fra = _tessdata_source()

datas = [(str(fra), "tessdata")]
# Données de piper-tts, dont « espeak-ng-data/ » (phontab + dictionnaires de
# phonèmes). PyInstaller embarque les .so de piper via son hook, mais PAS ce
# dossier de données : sans lui, Piper phonémise dans le vide et la synthèse
# meurt au 1er mot — l'exe démarre, l'OCR marche, la voix reste muette (même
# forme que le bug tempfile). collect_data_files rétablit l'arborescence.
datas += collect_data_files("piper")
for voix in VOIX_DEFAUT:
    onnx = dossier_voix / f"{voix}.onnx"
    conf = dossier_voix / f"{voix}.onnx.json"
    for f in (onnx, conf):
        if not f.is_file():
            raise SystemExit(f"voix par défaut manquante : {f}")
        datas.append((str(f), "piper-voices"))

# tesseract à la racine du bundle (le code cherche _MEIPASS/tesseract[.exe]).
binaries = [(str(tesseract), ".")]
if not WINDOWS:
    binaries += _libs_tesseract_linux(tesseract)
else:
    # Sous Windows, choco installe tesseract + ses DLL dans un même dossier :
    # on embarque tout le voisinage du .exe (les DLL sont à côté).
    for dll in tesseract.parent.glob("*.dll"):
        binaries.append((str(dll), "."))

# Le runtime-hook pose LD_LIBRARY_PATH / PATH avant le code applicatif.
runtime_hooks = [str(RACINE / "packaging" / "rthook_tesseract_libs.py")]


# Moteurs optionnels JAMAIS embarqués dans le fat exec par défaut (voix Piper
# seulement). Sans ces excludes, un venv de build qui a XTTS installé aspire
# torch + nvidia/CUDA + triton + llvmlite (~4 Go de poids mort). La CI build
# depuis « .[build] » sans ces deps, mais l'exclude est la ceinture qui garantit
# un exe léger quelle que soit la machine de build. XTTS/Kokoro restent
# disponibles hors bundle (extras pip), pas dans l'exécutable livré.
EXCLUDES_LOURDS = [
    "torch", "torchaudio", "TTS", "coqui_tts",
    "nvidia", "triton", "llvmlite", "numba",
    "kokoro_onnx", "kokoro",
]

a = Analysis(
    [str(RACINE / "keraconte" / "__main__.py")],
    pathex=[str(RACINE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["keraconte.capture_mss", "keraconte.capture_factory"],
    hookspath=[],
    runtime_hooks=runtime_hooks,
    excludes=EXCLUDES_LOURDS
    + (["keraconte.capture_linux"] if WINDOWS else []),
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir : les binaires vont dans COLLECT
    name=EXE_NOM,
    console=True,            # sortie QR_DEBUG lisible ; overlay Qt reste GUI
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=EXE_NOM,
)
