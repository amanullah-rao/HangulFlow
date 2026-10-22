"""`HangulFlow.exe --self-test`: check fonts, database and Korean speech, then exit.

The windowed .exe has no console, so the report is written to
self-test.txt in the data folder (and to the log). Exit code 0 = all passed.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtTextToSpeech import QTextToSpeech
from PySide6.QtWidgets import QApplication

from . import __version__, paths
from .database import open_database
from .repository import VocabRepository
from .ui import theme
from .ui.speech import KoreanSpeaker

log = logging.getLogger(__name__)


def run(app: QApplication) -> int:
    results: list[tuple[str, bool, str]] = []

    families = theme.load_bundled_fonts(paths.fonts_dir())
    fonts = theme.detect_fonts()
    results.append(("Bundled fonts", "Pretendard" in families and "Noto Nastaliq Urdu" in families, ", ".join(families)))
    results.append(("Fonts in use", True, f"Korean={fonts.korean}, Urdu={fonts.urdu}, Hanja={fonts.hanja}"))

    try:
        conn = open_database(paths.database_path())
        repo = VocabRepository(conn)
        repo.import_seed(paths.seed_vocabulary_path())
        results.append(("Database", repo.count() > 0, f"{repo.count()} words at {paths.database_path()}"))
        conn.close()
    except Exception as exc:  # report every failure instead of crashing
        results.append(("Database", False, repr(exc)))

    speaker = KoreanSpeaker()
    if speaker.speak("안녕하세요"):
        spoke, deadline = False, time.monotonic() + 8
        while time.monotonic() < deadline:
            app.processEvents()
            state = speaker.state()
            if state == QTextToSpeech.State.Speaking:
                spoke = True
            if state == QTextToSpeech.State.Error:
                break
            if spoke and state == QTextToSpeech.State.Ready:
                break
            time.sleep(0.02)
        results.append(("Korean speech", spoke and speaker.state() != QTextToSpeech.State.Error,
                        f"voice {speaker.voice_name}, final state {speaker.state().name}"))
    else:
        results.append(("Korean speech", False, "no Korean voice installed (optional feature)"))

    ok = all(passed for name, passed, _ in results if name != "Korean speech") and results[-1][1]
    lines = [f"HangulFlow {__version__} self-test: {'PASSED' if ok else 'FAILED'}"]
    lines += [f"[{'ok' if passed else 'FAIL'}] {name}: {detail}" for name, passed, detail in results]
    report = "\n".join(lines)
    (paths.data_dir() / "self-test.txt").write_text(report + "\n", encoding="utf-8")
    log.info(report)
    return 0 if ok else 1
