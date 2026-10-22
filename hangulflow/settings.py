"""User settings stored as JSON, written atomically.

A missing or corrupted settings file never stops the app: we fall back to
defaults and keep the broken file as settings.corrupt.json for inspection.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

INTERVAL_CHOICES = (1, 5, 10, 15, 20, 30)  # minutes; 1 is mainly for testing
DAILY_GOAL_CHOICES = (10, 20, 30, 50)  # words rated per day
REVEAL_MODES = ("hidden", "shown")
# Which side of the card is shown first: Korean, the meaning (recall the Korean), or a mix.
CARD_DIRECTIONS = ("korean", "meaning", "mixed")
MIXED_REVERSE_SHARE = 0.3  # in "mixed", about 3 in 10 cards show the meaning first
MIN_WIDTH, MAX_WIDTH = 260, 560
LAYERS = ("desktop", "normal", "top")  # behind all windows | like any window | always on top
THEME_KEYS =("midnight", "graphite", "ocean", "forest", "paper", "hanji")  # see ui/theme.py


@dataclass
class Settings:
    interval_minutes: int = 10
    theme: str = "paper"
    daily_goal: int = 20
    paused: bool = False
    reveal_mode: str = "hidden"  # "hidden": click Reveal; "shown": meanings visible at once
    card_direction: str = "korean"
    compact: bool = False
    opacity: float = 0.95
    layer: str = "desktop"
    auto_pause: bool = True  # pause when locked/idle; hide during fullscreen apps
    x: int | None = None
    y: int | None = None
    width: int = 340
    current_vocab_id: int | None = None
    tray_hint_shown: bool = False

    def validated(self) -> Settings:
        """Return a copy with every field coerced into a sane range."""
        defaults = Settings()
        return Settings(
            interval_minutes=self.interval_minutes
            if _is_int(self.interval_minutes) and self.interval_minutes in INTERVAL_CHOICES
            else defaults.interval_minutes,
            theme=self.theme if self.theme in THEME_KEYS else defaults.theme,
            daily_goal=self.daily_goal if self.daily_goal in DAILY_GOAL_CHOICES else defaults.daily_goal,
            paused=bool(self.paused),
            reveal_mode=self.reveal_mode if self.reveal_mode in REVEAL_MODES else defaults.reveal_mode,
            card_direction=self.card_direction if self.card_direction in CARD_DIRECTIONS else defaults.card_direction,
            compact=bool(self.compact),
            opacity=min(1.0, max(0.3, float(self.opacity)))
            if isinstance(self.opacity, (int, float)) and not isinstance(self.opacity, bool)
            else defaults.opacity,
            layer=self.layer if self.layer in LAYERS else defaults.layer,
            auto_pause=bool(self.auto_pause),
            x=self.x if _is_int(self.x) else None,
            y=self.y if _is_int(self.y) else None,
            width=min(MAX_WIDTH, max(MIN_WIDTH, self.width)) if _is_int(self.width) else defaults.width,
            current_vocab_id=self.current_vocab_id if _is_int(self.current_vocab_id) else None,
            tray_hint_shown=bool(self.tray_hint_shown),
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root is not a JSON object")
        except (OSError, ValueError) as exc:
            log.warning("Settings file unreadable (%s); using defaults.", exc)
            self._quarantine()
            return Settings()

        known = {f.name for f in fields(Settings)}
        return Settings(**{k: v for k, v in raw.items() if k in known}).validated()

    def save(self, settings: Settings) -> None:
        payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except OSError:
            log.exception("Could not save settings to %s", self.path)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def _quarantine(self) -> None:
        try:
            os.replace(self.path, self.path.with_name("settings.corrupt.json"))
        except OSError:
            log.exception("Could not move the corrupted settings file aside")
