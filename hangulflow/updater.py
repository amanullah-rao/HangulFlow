"""Optional online word-list updates.

Once a day HangulFlow downloads the curated word list from the project's GitHub
repository. If its version is newer than the one already imported, new words are
added and unedited curated words are refreshed, exactly like the bundled list.
Nothing about the learner is sent; when offline the check simply fails quietly.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import timedelta

from PySide6.QtCore import QObject, Signal

from . import __version__
from .repository import VocabRepository, from_iso, to_iso, utc_now

log = logging.getLogger(__name__)

WORDS_URL = "https://raw.githubusercontent.com/amanullah-rao/HangulFlow/main/hangulflow/resources/seed_vocabulary.json"
CHECK_EVERY = timedelta(days=1)
MAX_BYTES = 5_000_000  # the list is ~0.3 MB; refuse anything absurd
TIMEOUT_SECONDS = 20


def parse_word_list(raw: bytes) -> dict:
    """Decode a downloaded list and check its shape. Raises ValueError."""
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError("not a HangulFlow word list")
    if not isinstance(data.get("version"), int):
        raise ValueError("word list has no version number")
    return data


def download(url: str = WORDS_URL) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": f"HangulFlow/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("word list is too large")
    return parse_word_list(raw)


class WordUpdater(QObject):
    """Downloads in a background thread; merges into the database on the GUI thread."""

    finished = Signal(int, str)  # new words added, error text ("" on success)
    _downloaded = Signal(object, str)

    def __init__(self, repo: VocabRepository, url: str = WORDS_URL) -> None:
        super().__init__()
        self._repo = repo
        self._url = url
        self._busy = False
        self._downloaded.connect(self._merge)  # queued: emitted from the worker thread

    @property
    def busy(self) -> bool:
        return self._busy

    def check(self, force: bool = False) -> bool:
        """Start a check unless one ran recently (or is running). Returns True if started."""
        if self._busy:
            return False
        if not force:
            last = from_iso(self._repo.meta("last_word_check"))
            if last is not None and utc_now() - last < CHECK_EVERY:
                return False
        self._busy = True
        threading.Thread(target=self._work, name="word-update", daemon=True).start()
        return True

    def _work(self) -> None:
        try:
            self._downloaded.emit(download(self._url), "")
        except Exception as exc:  # network errors, bad JSON, HTTP 404 ... all non-fatal
            self._downloaded.emit(None, str(exc) or exc.__class__.__name__)

    def _merge(self, data: dict | None, error: str) -> None:
        self._busy = False
        if data is None:
            log.info("Word list update not available: %s", error)
            self.finished.emit(0, error)
            return
        self._repo.set_meta("last_word_check", to_iso(utc_now()))
        added = self._repo.apply_word_list(data)
        log.info("Online word list v%s checked: %d new words.", data["version"], added)
        self.finished.emit(added, "")
