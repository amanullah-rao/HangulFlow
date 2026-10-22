"""Korean pronunciation through the Windows text-to-speech voices (offline, free).

The voice is looked up the first time it is needed, so start-up stays fast.
If no Korean voice is installed, speak() returns False and the caller shows
how to install one - we never pretend audio played.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QLocale, QObject
from PySide6.QtTextToSpeech import QTextToSpeech

log = logging.getLogger(__name__)

ENGINES = ("winrt", "sapi")  # winrt = modern OneCore voices, sapi = classic desktop voices
INSTALL_HINT = "No Korean voice · Settings › Time & language › Speech › Add voices › 한국어"


class KoreanSpeaker(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tts: QTextToSpeech | None = None
        self._checked = False
        self.voice_name = ""

    def _ensure(self) -> bool:
        if self._checked:
            return self._tts is not None
        self._checked = True
        korean = QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea)
        for engine in ENGINES:
            if engine not in QTextToSpeech.availableEngines():
                continue
            tts = QTextToSpeech(engine, self)
            tts.setLocale(korean)
            voices = [v for v in tts.availableVoices() if v.locale().language() == QLocale.Language.Korean]
            if voices:
                tts.setVoice(voices[0])
                tts.setRate(-0.1)  # slightly slower than normal, easier for learners
                self._tts, self.voice_name = tts, voices[0].name()
                log.info("Korean voice: %s (%s engine)", self.voice_name, engine)
                return True
            tts.deleteLater()
        log.warning("No Korean text-to-speech voice installed.")
        return False

    @property
    def available(self) -> bool:
        return self._ensure()

    def speak(self, text: str) -> bool:
        if not text or not self._ensure():
            return False
        self._tts.stop()
        self._tts.say(text)
        return True

    def state(self) -> QTextToSpeech.State | None:
        return self._tts.state() if self._tts else None
