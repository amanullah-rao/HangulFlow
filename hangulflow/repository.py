"""Data access for vocabulary, viewing history and learning progress."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import srs
from .rotation import Candidate

log = logging.getLogger(__name__)

_FIELDS = (
    "korean", "hanja", "romanization", "part_of_speech", "meaning_en", "meaning_ur",
    "example_ko", "example_en", "example_ur", "notes", "category", "difficulty",
)
# Fields the bundled list may refresh on words the learner has never edited.
_REFRESHABLE = tuple(f for f in _FIELDS if f not in ("korean", "meaning_en"))


@dataclass(frozen=True)
class Vocab:
    id: int
    korean: str
    hanja: str
    romanization: str
    part_of_speech: str
    meaning_en: str
    meaning_ur: str
    example_ko: str
    example_en: str
    example_ur: str
    notes: str
    category: str
    difficulty: int
    source: str
    starred: bool = False


@dataclass(frozen=True)
class Stats:
    total: int
    new: int
    learning: int  # learning + review: words in progress
    learned: int
    due_now: int
    rated_today: int  # distinct words rated today (counts toward the daily goal)
    viewed_today: int
    streak_days: int  # consecutive days (ending today or yesterday) with at least one rating
    last_7_days: list[tuple[date, int]]  # oldest first: (local date, distinct words rated)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def local_midnight_utc(day: date) -> datetime:
    """Start of a local calendar day, as a UTC datetime."""
    return datetime.combine(day, time.min).astimezone().astimezone(timezone.utc)


class VocabRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- vocabulary -------------------------------------------------------

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM vocabulary").fetchone()[0]

    def get(self, vocab_id: int) -> Vocab | None:
        row = self.conn.execute(
            "SELECT id, korean, hanja, romanization, part_of_speech, meaning_en, meaning_ur, example_ko,"
            " example_en, example_ur, notes, category, difficulty, source, starred"
            " FROM vocabulary WHERE id = ?",
            (vocab_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["starred"] = bool(data["starred"])
        return Vocab(**data)

    def add_word(
        self,
        korean: str,
        meaning_en: str,
        meaning_ur: str = "",
        romanization: str = "",
        part_of_speech: str = "",
        example_ko: str = "",
        example_en: str = "",
        example_ur: str = "",
        notes: str = "",
        category: str = "My Words",
    ) -> int:
        """Add the learner's own word (starred, so it is easy to find). Returns its id."""
        korean, meaning_en = korean.strip(), meaning_en.strip()
        if not korean or not meaning_en:
            raise ValueError("Korean word and English meaning are required")
        now = to_iso(utc_now())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO vocabulary (korean, romanization, part_of_speech, meaning_en, meaning_ur, example_ko,"
                " example_en, example_ur, notes, category, difficulty, source, starred, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 'user', 1, ?, ?)",
                (korean, romanization.strip(), part_of_speech.strip(), meaning_en, meaning_ur.strip(),
                 example_ko.strip(), example_en.strip(), example_ur.strip(), notes.strip(), category, now, now),
            )
        return cur.lastrowid

    def find(self, korean: str, meaning_en: str) -> int | None:
        """Id of the word with this Korean text and English meaning, if it exists."""
        row = self.conn.execute(
            "SELECT id FROM vocabulary WHERE korean = ? AND meaning_en = ?", (korean.strip(), meaning_en.strip())
        ).fetchone()
        return row[0] if row else None

    def set_starred(self, vocab_id: int, starred: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE vocabulary SET starred = ? WHERE id = ?", (int(starred), vocab_id))

    def import_seed(self, path: Path) -> int:
        """Load the bundled curated list if its version is newer than the last import.

        New words are added. Existing curated words are refreshed (e.g. new
        Hanja or notes) only if the learner never edited them, i.e. their
        updated_at still equals created_at. Returns the number of new words.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("Could not read seed vocabulary from %s", path)
            return 0

        version = int(data.get("version", 0))
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'seed_version'").fetchone()
        if row is not None and int(row[0]) >= version:
            return 0

        now = to_iso(utc_now())
        added = 0
        with self.conn:
            for entry in data.get("entries", []):
                values = [entry.get(f, "") for f in _FIELDS]
                values[_FIELDS.index("difficulty")] = int(entry.get("difficulty", 2))
                cur = self.conn.execute(
                    f"INSERT OR IGNORE INTO vocabulary ({', '.join(_FIELDS)}, source, created_at, updated_at)"
                    f" VALUES ({', '.join('?' * len(_FIELDS))}, 'curated', ?, ?)",
                    (*values, now, now),
                )
                added += cur.rowcount
                if cur.rowcount == 0:
                    refresh = {f: values[_FIELDS.index(f)] for f in _REFRESHABLE}
                    self.conn.execute(
                        f"UPDATE vocabulary SET {', '.join(f'{f} = ?' for f in refresh)}"
                        " WHERE korean = ? AND meaning_en = ? AND source = 'curated' AND updated_at = created_at",
                        (*refresh.values(), entry["korean"], entry["meaning_en"]),
                    )
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES ('seed_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(version),),
            )
        log.info("Seed vocabulary v%s imported: %d new words.", version, added)
        return added

    # --- rotation support ---------------------------------------------------

    def candidates(self) -> list[Candidate]:
        rows = self.conn.execute(
            "SELECT v.id, COALESCE(p.times_seen, 0) AS times_seen, COALESCE(p.status, 'new') AS status, p.due_at"
            " FROM vocabulary v LEFT JOIN progress p ON p.vocab_id = v.id"
        ).fetchall()
        return [
            Candidate(vocab_id=r["id"], times_seen=r["times_seen"], status=r["status"], due_at=from_iso(r["due_at"]))
            for r in rows
        ]

    def recent_view_ids(self, limit: int) -> list[int]:
        """Most recently shown word ids, newest first, without duplicates."""
        rows = self.conn.execute(
            "SELECT vocab_id, MAX(viewed_at) AS last FROM view_log"
            " GROUP BY vocab_id ORDER BY last DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["vocab_id"] for r in rows]

    def record_view(self, vocab_id: int, when: datetime | None = None) -> None:
        stamp = to_iso(when or utc_now())
        with self.conn:
            self.conn.execute(
                "INSERT INTO view_log(vocab_id, viewed_at) VALUES (?, ?)", (vocab_id, stamp)
            )
            self.conn.execute(
                "INSERT INTO progress(vocab_id, times_seen, last_seen_at) VALUES (?, 1, ?)"
                " ON CONFLICT(vocab_id) DO UPDATE SET"
                " times_seen = times_seen + 1, last_seen_at = excluded.last_seen_at",
                (vocab_id, stamp),
            )

    # --- learning progress ----------------------------------------------------

    def card_state(self, vocab_id: int) -> srs.CardState:
        row = self.conn.execute(
            "SELECT status, ease, interval_days, repetitions, lapses, due_at FROM progress WHERE vocab_id = ?",
            (vocab_id,),
        ).fetchone()
        if row is None:
            return srs.CardState()
        return srs.CardState(
            status=row["status"], ease=row["ease"], interval_days=row["interval_days"],
            repetitions=row["repetitions"], lapses=row["lapses"], due_at=from_iso(row["due_at"]),
        )

    def rate(self, vocab_id: int, rating: str, now: datetime | None = None) -> srs.CardState:
        """Apply a Known / Difficult / Unknown rating and log it."""
        now = now or utc_now()
        before = self.card_state(vocab_id)
        after = srs.schedule(before, rating, now)
        self._save_state(vocab_id, before, after, rating, now)
        return after

    def mark_learned(self, vocab_id: int, now: datetime | None = None) -> srs.CardState:
        now = now or utc_now()
        before = self.card_state(vocab_id)
        after = srs.mark_learned(before, now)
        self._save_state(vocab_id, before, after, srs.KNOWN, now)
        return after

    def _save_state(self, vocab_id: int, before: srs.CardState, after: srs.CardState, rating: str, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO progress (vocab_id, status, ease, interval_days, repetitions, lapses, due_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(vocab_id) DO UPDATE SET status = excluded.status, ease = excluded.ease,"
                " interval_days = excluded.interval_days, repetitions = excluded.repetitions,"
                " lapses = excluded.lapses, due_at = excluded.due_at",
                (vocab_id, after.status, after.ease, after.interval_days, after.repetitions, after.lapses,
                 to_iso(after.due_at) if after.due_at else None),
            )
            self.conn.execute(
                "INSERT INTO review_log (vocab_id, reviewed_at, rating, interval_before, interval_after, ease_after)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (vocab_id, to_iso(now), rating, before.interval_days, after.interval_days, after.ease),
            )

    def stats(self, now: datetime | None = None) -> Stats:
        now = now or utc_now()
        today = now.astimezone().date()
        today_start = to_iso(local_midnight_utc(today))

        counts = dict(self.conn.execute(
            "SELECT COALESCE(p.status, 'new'), COUNT(*) FROM vocabulary v"
            " LEFT JOIN progress p ON p.vocab_id = v.id GROUP BY 1"
        ).fetchall())
        due_now = self.conn.execute(
            "SELECT COUNT(*) FROM progress WHERE due_at IS NOT NULL AND due_at <= ?", (to_iso(now),)
        ).fetchone()[0]
        rated_today = self.conn.execute(
            "SELECT COUNT(DISTINCT vocab_id) FROM review_log WHERE reviewed_at >= ?", (today_start,)
        ).fetchone()[0]
        viewed_today = self.conn.execute(
            "SELECT COUNT(DISTINCT vocab_id) FROM view_log WHERE viewed_at >= ?", (today_start,)
        ).fetchone()[0]

        # Per local day over the last 60 days, for the weekly chart and the streak.
        since = to_iso(local_midnight_utc(today - timedelta(days=60)))
        per_day: dict[date, set[int]] = {}
        for vocab_id, stamp in self.conn.execute(
            "SELECT vocab_id, reviewed_at FROM review_log WHERE reviewed_at >= ?", (since,)
        ):
            per_day.setdefault(from_iso(stamp).astimezone().date(), set()).add(vocab_id)
        last_7 = [(d, len(per_day.get(d, ()))) for d in (today - timedelta(days=i) for i in range(6, -1, -1))]

        streak, day = 0, today if today in per_day else today - timedelta(days=1)
        while day in per_day:
            streak += 1
            day -= timedelta(days=1)

        return Stats(
            total=sum(counts.values()),
            new=counts.get(srs.NEW, 0),
            learning=counts.get(srs.LEARNING, 0) + counts.get(srs.REVIEW, 0),
            learned=counts.get(srs.LEARNED, 0),
            due_now=due_now,
            rated_today=rated_today,
            viewed_today=viewed_today,
            streak_days=streak,
            last_7_days=last_7,
        )
