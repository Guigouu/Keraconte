"""Package quest_reader — réorganisation en cours depuis _legacy."""

from quest_reader._legacy import (  # noqa: F401
    Playback,
    PiperEngine,
    Reader,
    Speaker,
    XttsEngine,
    build_engine,
    check_xtts,
    clean,
    drop_replies,
    find_dialog,
    keep_word,
    pronounce,
    reads_like_dialogue,
    same_dialog,
    speakable,
    split_narration,
    strip_choices,
    split_sentences,
    voice_argument,
)
