import random

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
