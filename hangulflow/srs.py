"""Spaced-repetition scheduling (a simplified SM-2).

Rules, in plain words:
- Unknown   -> back in 10 minutes; a word you had already learned counts as a lapse.
- Difficult -> new word: back in 1 hour; reviewed word: interval x 1.2 (at least 1 day).
- Known     -> new word: back in 1 day; reviewed word: interval x ease (about 2.5x).
Ease starts at 2.5 and drops when a word is hard, so hard words grow slowly.
A word counts as "learned" once its interval reaches 21 days.

Pure functions only (no Qt, no SQL), so it is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

KNOWN, DIFFICULT, UNKNOWN = "known", "difficult", "unknown"
RATINGS = (KNOWN, DIFFICULT, UNKNOWN)

NEW, LEARNING, REVIEW, LEARNED = "new", "learning", "review", "learned"

START_EASE, MIN_EASE, MAX_EASE = 2.5, 1.3, 3.0
RELEARN_MINUTES = 10
DIFFICULT_FIRST_HOURS = 1
LEARNED_AFTER_DAYS = 21
MARK_LEARNED_DAYS = 60


@dataclass(frozen=True)
class CardState:
    status: str = NEW
    ease: float = START_EASE
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0
    due_at: datetime | None = None


def _status_for(interval_days: float) -> str:
    if interval_days >= LEARNED_AFTER_DAYS:
        return LEARNED
    if interval_days >= 1:
        return REVIEW
    return LEARNING


def _clamp_ease(ease: float) -> float:
    return round(min(MAX_EASE, max(MIN_EASE, ease)), 2)


def schedule(state: CardState, rating: str, now: datetime) -> CardState:
    """Return the new state after the learner rates a word."""
    if rating not in RATINGS:
        raise ValueError(f"unknown rating: {rating!r}")

    if rating == UNKNOWN:
        interval = RELEARN_MINUTES / (24 * 60)
        return CardState(
            status=LEARNING,
            ease=_clamp_ease(state.ease - 0.2),
            interval_days=interval,
            repetitions=0,
            lapses=state.lapses + (1 if state.repetitions > 0 else 0),
            due_at=now + timedelta(days=interval),
        )

    if state.repetitions == 0:
        interval = DIFFICULT_FIRST_HOURS / 24 if rating == DIFFICULT else 1.0
        ease = state.ease - 0.15 if rating == DIFFICULT else state.ease
    elif rating == DIFFICULT:
        interval = max(1.0, state.interval_days * 1.2)
        ease = state.ease - 0.15
    else:
        interval = max(1.0, state.interval_days * state.ease)
        ease = state.ease + 0.05

    return replace(
        state,
        status=_status_for(interval),
        ease=_clamp_ease(ease),
        interval_days=round(interval, 4),
        repetitions=state.repetitions + 1,
        due_at=now + timedelta(days=interval),
    )


def mark_learned(state: CardState, now: datetime) -> CardState:
    """'I already know this word well' - skip it for two months."""
    return replace(
        state,
        status=LEARNED,
        interval_days=float(MARK_LEARNED_DAYS),
        repetitions=state.repetitions + 1,
        due_at=now + timedelta(days=MARK_LEARNED_DAYS),
    )


def describe_interval(days: float) -> str:
    """Human-friendly 'back in ...' text."""
    minutes = days * 24 * 60
    if minutes < 60:
        return f"{max(1, round(minutes))} min"
    if days < 1:
        hours = round(minutes / 60)
        return f"{hours} hour" + ("" if hours == 1 else "s")
    if days < 30:
        d = round(days)
        return f"{d} day" + ("" if d == 1 else "s")
    months = round(days / 30)
    return f"{months} month" + ("" if months == 1 else "s")
