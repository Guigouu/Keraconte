"""Journal de diagnostic partagé, silencieux par défaut.

Activé par « QR_DEBUG=1 » dans l'environnement, il trace sur stderr les étapes
du pipeline (détection, OCR, décisions say/silence) sans changer le
comportement. Centralisé ici pour que « detection.py » puisse tracer ses
propres mesures de temps sans dépendre de « reader.py » (ce qui créerait un
cycle d'import). À n'utiliser que pour déboguer ou profiler en jeu.
"""

import os
import sys

DEBUG = bool(os.environ.get("QR_DEBUG"))


def trace(message):
    if DEBUG:
        print(f"[qr] {message}", file=sys.stderr, flush=True)
