import random
from datetime import datetime, timedelta, timezone

from hangulflow.rotation import Candidate, WordSession, choose_next, recent_window


class FakeSource:
    def __init__(self, ids):
        self.seen = {i: 0 for i in ids}
        self.views = []

    def candidates(self):
        return [Candidate(i, n) for i, n in self.seen.items()]

    def recent_view_ids(self, limit):
        out = []
        for vid in reversed(self.views):
            if vid not in out:
                out.append(vid)
        return out[:limit]

    def record_view(self, vocab_id):
        self.seen[vocab_id] += 1
        self.views.append(vocab_id)


def test_empty_deck_returns_none():
    assert choose_next([], [], random.Random(1)) is None


def test_recent_words_are_skipped():
    cands = [Candidate(i, 0) for i in range(1, 6)]
    for seed in range(50):
        assert choose_next(cands, [1, 2, 3, 4], random.Random(seed)) == 5


def test_never_repeats_last_word_when_everything_is_recent():
    cands = [Candidate(1, 0), Candidate(2, 0)]
    for seed in range(50):
        assert choose_next(cands, [1, 2], random.Random(seed)) == 2


def test_unseen_words_are_preferred():
    cands = [Candidate(1, 0), Candidate(2, 50)]
    rng = random.Random(7)
    picks = [choose_next(cands, [], rng) for _ in range(1000)]
    assert picks.count(1) > picks.count(2) * 10


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_due_words_come_first_even_if_recent():
    cands = [
        Candidate(1, 0),                                                  # new
        Candidate(2, 3, "learning", NOW - timedelta(minutes=5)),         # due
        Candidate(3, 3, "review", NOW - timedelta(days=2)),              # more overdue
        Candidate(4, 3, "review", NOW + timedelta(days=3)),              # not due
    ]
    assert choose_next(cands, [9], random.Random(1), NOW) == 3   # most overdue wins, beats the new word
    assert choose_next(cands, [3], random.Random(1), NOW) == 2   # 3 just shown: next-most-overdue, not back to 3


def test_overdue_backlog_rotates_past_the_two_most_overdue():
    """Regression: clicking Next repeatedly without rating must not loop
    between just the one or two most-overdue words forever - the due_at of
    an unrated word never changes, so the old code got stuck bouncing
    between the top two. The whole backlog (up to the recent window) should
    get a turn before anything repeats."""
    cands = [Candidate(i, 3, "review", NOW - timedelta(days=i)) for i in range(1, 7)]  # 6 overdue words
    recent: list[int] = []
    shown = []
    for _ in range(12):
        picked = choose_next(cands, recent, random.Random(1), NOW)
        shown.append(picked)
        recent.insert(0, picked)
        recent = recent[: recent_window(len(cands))]
    assert len(set(shown)) > 2


def test_overdue_words_all_recently_shown_make_room_for_new_words():
    """Regression: 18 overdue words that were all just shown (the recent window
    holds 20) used to fall back to the two most-overdue words, swapping forever."""
    cands = [Candidate(i, 3, "learning", NOW - timedelta(days=30 - i)) for i in range(1, 19)]
    cands += [Candidate(100 + i, 0) for i in range(200)]            # plenty of new words
    recent = list(range(18, 0, -1)) + [100, 101]                    # newest first, all overdue ones inside
    shown = []
    for _ in range(40):
        picked = choose_next(cands, recent, random.Random(len(shown)), NOW)
        shown.append(picked)
        recent = ([picked] + [r for r in recent if r != picked])[:20]
    assert len(set(shown)) > 20             # variety: overdue words and new ones, not two words
    assert any(s >= 100 for s in shown)     # new words get through
    assert all(a != b for a, b in zip(shown, shown[1:]))   # never the same word twice in a row


def test_tiny_deck_of_overdue_words_still_rotates():
    cands = [Candidate(i, 3, "learning", NOW - timedelta(days=10 - i)) for i in range(1, 5)]
    recent: list[int] = []
    shown = []
    for _ in range(12):
        picked = choose_next(cands, recent, random.Random(1), NOW)
        shown.append(picked)
        recent = ([picked] + [r for r in recent if r != picked])[: recent_window(len(cands))]
    assert len(set(shown)) >= 3
    assert all(a != b for a, b in zip(shown, shown[1:]))


def test_new_words_before_early_practice():
    cands = [Candidate(1, 5, "review", NOW + timedelta(days=1)), Candidate(2, 0)]
    assert choose_next(cands, [], random.Random(1), NOW) == 2


def test_early_practice_prefers_unlearned_soonest():
    cands = [
        Candidate(1, 5, "learned", NOW + timedelta(hours=1)),
        Candidate(2, 5, "review", NOW + timedelta(days=4)),
        Candidate(3, 5, "review", NOW + timedelta(days=2)),
    ]
    assert choose_next(cands, [], random.Random(1), NOW) == 3


def test_recent_window_is_bounded():
    assert recent_window(0) == 0
    assert recent_window(10) == 5
    assert recent_window(500) == 20


def test_session_previous_and_next_walk_history():
    source = FakeSource(range(1, 11))
    session = WordSession(source, random.Random(3))
    first = session.next()
    second = session.next()
    assert first != second
    assert session.previous() == first
    assert not session.can_go_back
    assert session.next() == second          # forward through history, no new pick
    assert len(source.views) == 2            # ...and no extra view recorded


def test_session_resumes_preferred_word():
    source = FakeSource([1, 2, 3])
    assert WordSession(source).start(2) == 2
    assert WordSession(source).start(99) in {1, 2, 3}
