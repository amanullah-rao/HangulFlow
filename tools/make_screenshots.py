"""Regenerate the README screenshots in docs/screenshots/.

Uses a throwaway data folder, so your own words and progress never appear.
Run:  .venv\\Scripts\\python.exe tools\\make_screenshots.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
DATA = Path(tempfile.mkdtemp(prefix="hangulflow-shots-"))
os.environ["HANGULFLOW_DATA_DIR"] = str(DATA)
(DATA / "settings.json").write_text('{"x": 120, "y": 120, "theme": "paper"}', encoding="utf-8")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import hangulflow.app as app_mod  # noqa: E402
from hangulflow.ui import theme  # noqa: E402

created = {}


def wait(ms: int, then) -> None:
    QTimer.singleShot(ms, then)


def save(widget, name: str) -> None:
    widget.grab().save(str(OUT / name))
    print("saved", name)


class Spy(app_mod.VocabWidget):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        created["w"] = self
        wait(600, step_card)


def word_id(w, korean: str) -> int:
    return w._repo.conn.execute("SELECT id FROM vocabulary WHERE korean = ?", (korean,)).fetchone()[0]


def step_card():
    w = created["w"]
    # Some realistic progress for history and statistics.
    for korean, rating in (("과제", "known"), ("환경", "difficult"), ("면접", "unknown"), ("전공", "known"),
                           ("갈등", "difficult"), ("영향", "known"), ("오해", "known")):
        w._repo.rate(word_id(w, korean), rating)
    w._refresh_goal()
    w._show_vocab(w._session.show(word_id(w, "노력")), animate=False)
    wait(300, lambda: (save(w, "card-question.png"), w.reveal(), wait(300, step_revealed)))


def step_revealed():
    w = created["w"]
    save(w, "card-revealed.png")
    w._show_vocab(w._session.show(word_id(w, "-(으)ㄹ 뿐만 아니라")), animate=False)
    w.reveal()
    wait(300, lambda: (save(w, "card-grammar.png"), step_themes()))


def step_themes():
    w = created["w"]
    w._show_vocab(w._session.show(word_id(w, "장학금")), animate=False)
    shots = []

    def next_theme(keys):
        if not keys:
            compose_themes(shots)
            w.set_theme("paper")
            w.library_requested.emit()
            wait(600, step_library)
            return
        key = keys.pop(0)
        w.set_theme(key)
        w.reveal()
        wait(300, lambda: (shots.append((theme.PALETTES[key].name, w.grab().toImage())), next_theme(keys)))

    next_theme(list(theme.PALETTES))


def compose_themes(shots):
    cols, pad, label_h = 3, 28, 34
    cw = max(i.width() for _, i in shots)
    ch = max(i.height() for _, i in shots)
    rows = (len(shots) + cols - 1) // cols
    canvas = QImage(cols * (cw + pad) + pad, rows * (ch + label_h + pad) + pad, QImage.Format.Format_ARGB32)
    p = QPainter(canvas)
    bg = QLinearGradient(0, 0, canvas.width(), canvas.height())
    bg.setColorAt(0, QColor("#5B6B7F"))
    bg.setColorAt(1, QColor("#A38F86"))
    p.fillRect(canvas.rect(), bg)
    font = QFont("Pretendard")
    font.setPixelSize(17)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("white"))
    for n, (name, img) in enumerate(shots):
        x = pad + (n % cols) * (cw + pad)
        y = pad + (n // cols) * (ch + label_h + pad)
        p.drawText(QRect(x, y, cw, label_h - 8), Qt.AlignmentFlag.AlignVCenter, name)
        p.drawImage(x, y + label_h, img)
    p.end()
    canvas.save(str(OUT / "themes.png"))
    print("saved themes.png")


def step_library():
    lib = next(x for x in QApplication.topLevelWidgets() if x.objectName() == "libraryWindow")
    lib.resize(1060, 620)
    lib._table.selectRow(2)
    wait(400, lambda: (save(lib, "library.png"), lib._tabs.setCurrentIndex(2), wait(400, lambda: step_stats(lib))))


def step_stats(lib):
    save(lib, "statistics.png")
    QApplication.instance().quit()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    app_mod.VocabWidget = Spy
    code = app_mod.main()
    shutil.rmtree(DATA, ignore_errors=True)
    sys.exit(code)
