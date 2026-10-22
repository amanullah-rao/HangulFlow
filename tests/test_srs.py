from datetime import datetime, timedelta, timezone

import pytest

from hangulflow import srs
from hangulflow.srs import DIFFICULT, KNOWN, UNKNOWN, CardState, describe_interval, schedule

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_new_word_ratings():
    assert schedule(CardState(), UNKNOWN, NOW).due_at == NOW + timedelta(minutes=10)
    assert schedule(CardState(), DIFFICULT, NOW).due_at == NOW + timedelta(hours=1)
    known = schedule(CardState(), KNOWN, NOW)
    assert known.due_at == NOW + timedelta(days=1)
    assert known.status == srs.REVIEW and known.repetitions == 1


def test_known_words_spread_out_and_become_learned():
    state, intervals = CardState(), []
    for _ in range(5):
        state = schedule(state, KNOWN, NOW)
        intervals.append(state.interval_days)
    assert intervals == sorted(intervals)
    assert intervals[0] == 1 and intervals[1] == pytest.approx(2.5)
    assert state.status == srs.LEARNED  # 1, 2.5, 6.4, 16.6, 43.9 days


def test_difficult_grows_slowly_and_lowers_ease():
    state = schedule(schedule(CardState(), KNOWN, NOW), KNOWN, NOW)  # 2.5 days
    hard = schedule(state, DIFFICULT, NOW)
    assert hard.interval_days == pytest.approx(state.interval_days * 1.2)
    assert hard.ease < state.ease


def test_unknown_resets_and_counts_lapse_only_for_reviewed_words():
    assert schedule(CardState(), UNKNOWN, NOW).lapses == 0
    reviewed = schedule(CardState(), KNOWN, NOW)
    lapsed = schedule(reviewed, UNKNOWN, NOW)
    assert lapsed.lapses == 1 and lapsed.repetitions == 0 and lapsed.status == srs.LEARNING


def test_ease_is_clamped():
    state = CardState()
    for _ in range(20):
        state = schedule(state, UNKNOWN, NOW)
    assert state.ease == srs.MIN_EASE


def test_mark_learned_and_bad_rating():
    assert srs.mark_learned(CardState(), NOW).status == srs.LEARNED
    with pytest.raises(ValueError):
        schedule(CardState(), "maybe", NOW)


@pytest.mark.parametrize("days, text", [
    (10 / 1440, "10 min"), (1 / 24, "1 hour"), (0.5, "12 hours"), (1, "1 day"), (6.4, "6 days"), (60, "2 months"),
])
def test_describe_interval(days, text):
    assert describe_interval(days) == text
