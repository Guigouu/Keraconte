"""Runtime-hook PyInstaller : rend les libs natives de tesseract trouvables.

Exécuté par le bootloader AVANT tout code applicatif. Le binaire tesseract est
un PROCESS EXTERNE lancé par pytesseract : PyInstaller ne le patche pas et ne
touche pas à son chargeur de bibliothèques. Ses .so/.dll ont été posées à la
racine du bundle (« sys._MEIPASS ») par la spec ; on pointe donc le chemin de
recherche de libs de l'OS vers cette racine pour que le process les résolve.

Sans ce hook, l'exe démarre mais tesseract meurt au 1er OCR avec un « cannot
open shared object » sur une machine qui n'a pas ces libs — même forme que le
bug tempfile : démarrage OK, échec au 1er usage.

La pile GStreamer/gi (Linux) n'est pas concernée : prérequis système, elle vit
dans les chemins standard de la distro.
"""

import os
import sys

_racine = getattr(sys, "_MEIPASS", None)
if _racine:
    if sys.platform == "win32":
        # Le process tesseract cherche ses DLL dans le PATH (et son dossier).
        variable = "PATH"
    else:
        # Linux : chemin de recherche du chargeur dynamique pour le process.
        variable = "LD_LIBRARY_PATH"
    actuel = os.environ.get(variable, "")
    if _racine not in actuel.split(os.pathsep):
        os.environ[variable] = (
            _racine + (os.pathsep + actuel if actuel else "")
        )
