"""Choosing which word to show next, plus Previous/Next history.

Priority (see choose_next):
1. Words that are due for review (most overdue first) - this is how
   difficult and unknown words come back quickly.
2. New words, favouring ones seen least often.
3. If nothing is due and nothing is new: early practice with the word whose
   review is closest, preferring words not yet learned.
Recently shown words are skipped so the same few words don't repeat.

Kept free of Qt and SQL so it can be unit-tested directly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .srs import LEARNED, NEW

MAX_HISTORY = 100


@dataclass(frozen=True)
class Candidate:
    vocab_id: int
    times_seen: int
    status: str = NEW
    due_at: datetime | None = None


def recent_window(total_words: int) -> int:
    """How many recently shown words to avoid: up to 20, never more than half the deck."""
    return max(0, min(20, total_words // 2))


def choose_next(
    candidates: list[Candidate],
    recent_ids: list[int],
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> int | None:
    if not candidates:
        return None
    rng = rng or random.Random()
    now = now or datetime.now(timezone.utc)
    last = recent_ids[0] if recent_ids else None

    recent = set(recent_ids)

    # 1. Due reviews win. Prefer ones outside the recent window first, so a
    #    backlog of overdue words rotates through instead of just bouncing
    #    between the one or two most-overdue words forever when the learner
    #    clicks Next without rating (nothing then changes due_at).
    due_all = [c for c in candidates if c.due_at is not None and c.due_at <= now]
    fresh = [c for c in due_all if c.vocab_id not in recent]
    if fresh:
        return min(fresh, key=lambda c: c.due_at).vocab_id

    pool = [c for c in candidates if c.vocab_id not in recent]
    if not pool:
        # The window covers the whole deck. Overdue words go round-robin, the one
        # shown longest ago first; picking the most overdue again would just swap
        # the same two words forever.
        age = {vid: i for i, vid in enumerate(recent_ids)}  # newest first, so bigger = older
        others = [c for c in due_all if c.vocab_id != last]
        if others:
            return max(others, key=lambda c: age.get(c.vocab_id, len(age))).vocab_id
        pool = [c for c in candidates if c.vocab_id != last] or list(candidates)

    # 2. New words, weighted towards the least seen.
    new = [c for c in pool if c.status == NEW]
    if new:
        weights = [1.0 / (1 + c.times_seen) for c in new]
        return rng.choices(new, weights=weights, k=1)[0].vocab_id

    # 3. Early practice: closest review first, learned words last.
    far = datetime.max.replace(tzinfo=timezone.utc)
    return min(pool, key=lambda c: (c.status == LEARNED, c.due_at or far)).vocab_id


class _Source(Protocol):
    def candidates(self) -> list[Candidate]: ...
    def recent_view_ids(self, limit: int) -> list[int]: ...
    def record_view(self, vocab_id: int) -> None: ...


class WordSession:
    """Tracks what is on screen and lets the user step back and forward."""

    def __init__(
        self,
        source: _Source,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._rng = rng or random.Random()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history: list[int] = []
        self._pos = -1

    @property
    def current_id(self) -> int | None:
        return self._history[self._pos] if self._pos >= 0 else None

    @property
    def can_go_back(self) -> bool:
        return self._pos > 0

    def start(self, preferred_id: int | None) -> int | None:
        """Resume on the word shown before the app closed, if it still exists."""
        if preferred_id is not None and any(c.vocab_id == preferred_id for c in self._source.candidates()):
            self._push(preferred_id)
            return preferred_id
        return self.next()

    def next(self) -> int | None:
        if self._pos < len(self._history) - 1:  # walking forward through history
            self._pos += 1
            return self.current_id
        candidates = self._source.candidates()
        chosen = choose_next(
            candidates,
            self._source.recent_view_ids(recent_window(len(candidates))),
            self._rng,
            self._clock(),
        )
        if chosen is not None:
            self._source.record_view(chosen)
            self._push(chosen)
        return chosen

    def show(self, vocab_id: int) -> int:
        """Jump to a specific word (e.g. one the learner just added)."""
        self._source.record_view(vocab_id)
        self._push(vocab_id)
        return vocab_id

    def previous(self) -> int | None:
        if self.can_go_back:
            self._pos -= 1
        return self.current_id

    def _push(self, vocab_id: int) -> None:
        self._history.append(vocab_id)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._pos = len(self._history) - 1
