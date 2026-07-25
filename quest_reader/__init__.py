"""Package quest_reader : lit à voix haute les dialogues de PNJ de Dofus.

Ré-exporte l'API publique utilisée par les tests, chaque symbole tiré de son
module propre.
"""

from quest_reader.detection import (  # noqa: F401
    drop_replies,
    find_dialog,
    keep_word,
    reads_like_dialogue,
)
from quest_reader.engines import (  # noqa: F401
    PiperEngine,
    XttsEngine,
    build_engine,
    check_xtts,
)
from quest_reader.engines.xtts import voice_argument  # noqa: F401
from quest_reader.playback import Playback  # noqa: F401
from quest_reader.reader import Reader  # noqa: F401
from quest_reader.state import Etat, PlayerState  # noqa: F401
from quest_reader.speaker import Speaker  # noqa: F401
from quest_reader.text import (  # noqa: F401
    clean,
    pronounce,
    same_dialog,
    speakable,
    split_narration,
    split_sentences,
    strip_choices,
)
