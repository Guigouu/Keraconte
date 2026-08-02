"""Package keraconte : lit à voix haute les dialogues de PNJ de Dofus.

Ré-exporte l'API publique utilisée par les tests, chaque symbole tiré de son
module propre.
"""

from keraconte.detection import (  # noqa: F401
    drop_replies,
    find_dialog,
    keep_word,
    reads_like_dialogue,
)
from keraconte.engines import (  # noqa: F401
    PiperEngine,
    XttsEngine,
    build_engine,
    check_xtts,
)
from keraconte.engines.xtts import voice_argument  # noqa: F401
from keraconte.playback import Playback  # noqa: F401
from keraconte.reader import Reader  # noqa: F401
from keraconte.speed import Vitesse  # noqa: F401
from keraconte.state import Etat, PlayerState  # noqa: F401
from keraconte.speaker import Speaker  # noqa: F401
from keraconte.text import (  # noqa: F401
    clean,
    pronounce,
    same_dialog,
    speakable,
    split_narration,
    split_sentences,
    strip_choices,
)
