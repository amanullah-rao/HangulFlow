"""Choosing which word to show next, plus Previous/Next history.

Kept free of Qt and SQL so it can be unit-tested directly. Phase 3 will
replace the weighting in `choose_next` with spaced-repetition due dates.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

MAX_HISTORY = 100


@dataclass(frozen=True)
class Candidate:
    vocab_id: int
    times_seen: int


def recent_window(total_words: int) -> int:
    """How many recently shown words to avoid: up to 20, never more than half the deck."""
    return max(0, min(20, total_words // 2))


def choose_next(
    candidates: list[Candidate],
    recent_ids: list[int],
    rng: random.Random | None = None,
) -> int | None:
    """Pick a word id, skipping recently shown words and favouring rarely seen ones."""
    if not candidates:
        return None
    rng = rng or random.Random()
    recent = set(recent_ids)
    pool = [c for c in candidates if c.vocab_id not in recent]
    if not pool:
        last = recent_ids[0] if recent_ids else None
        pool = [c for c in candidates if c.vocab_id != last] or list(candidates)
    weights = [1.0 / (1 + c.times_seen) for c in pool]  # unseen words weigh 1.0
    return rng.choices(pool, weights=weights, k=1)[0].vocab_id


class _Source(Protocol):
    def candidates(self) -> list[Candidate]: ...
    def recent_view_ids(self, limit: int) -> list[int]: ...
    def record_view(self, vocab_id: int) -> None: ...


class WordSession:
    """Tracks what is on screen and lets the user step back and forward."""

    def __init__(self, source: _Source, rng: random.Random | None = None) -> None:
        self._source = source
        self._rng = rng or random.Random()
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
        )
        if chosen is not None:
            self._source.record_view(chosen)
            self._push(chosen)
        return chosen

    def previous(self) -> int | None:
        if self.can_go_back:
            self._pos -= 1
        return self.current_id

    def _push(self, vocab_id: int) -> None:
        self._history.append(vocab_id)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._pos = len(self._history) - 1
