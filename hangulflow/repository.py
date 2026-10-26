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
WORD_FIELDS = _FIELDS  # public name, used by import/export
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
    # Every example sentence as (ko, en, ur): the main one first, then the extras.
    examples: tuple[tuple[str, str, str], ...] = ()
    example_turn: int = 0  # how often the word was shown; picks the sentence to display

    def example_for_display(self) -> tuple[str, str, str]:
        """A different sentence each time the word comes back."""
        if not self.examples:
            return (self.example_ko, self.example_en, self.example_ur)
        return self.examples[max(self.example_turn - 1, 0) % len(self.examples)]


@dataclass(frozen=True)
class LibraryRow:
    id: int
    korean: str
    hanja: str
    meaning_en: str
    meaning_ur: str
    category: str
    difficulty: int
    starred: bool
    source: str
    status: str
    due_at: datetime | None
    times_seen: int
    lapses: int


def _clean_fields(raw: dict) -> dict:
    """Validate and normalise word fields coming from a form or an import file."""
    values = {f: str(raw.get(f, "") or "").strip() for f in _FIELDS if f != "difficulty"}
    if not values["korean"] or not values["meaning_en"]:
        raise ValueError("Korean word and English meaning are required")
    values["category"] = values["category"] or "My Words"
    try:
        difficulty = int(raw.get("difficulty") or 2)
    except (TypeError, ValueError):
        raise ValueError(f"level must be a number 1-3, got {raw.get('difficulty')!r}") from None
    values["difficulty"] = min(3, max(1, difficulty))
    return values


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
            " example_en, example_ur, notes, category, difficulty, source, starred, example_turn"
            " FROM vocabulary WHERE id = ?",
            (vocab_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["starred"] = bool(data["starred"])
        extras = self.conn.execute("SELECT ko, en, ur FROM examples WHERE vocab_id = ? ORDER BY id", (vocab_id,))
        main = (data["example_ko"], data["example_en"], data["example_ur"])
        data["examples"] = tuple(([main] if main[0] else []) + [tuple(r) for r in extras if r[0] != main[0]])
        return Vocab(**data)

    def example_count(self) -> int:
        """All example sentences: the main one of each word plus the extras."""
        main = self.conn.execute("SELECT COUNT(*) FROM vocabulary WHERE example_ko != ''").fetchone()[0]
        return main + self.conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0]

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
        hanja: str = "",
        difficulty: int = 2,
        source: str = "user",
        starred: bool = True,
    ) -> int:
        """Add a word (the learner's own words are starred, so they are easy to find). Returns its id."""
        values = _clean_fields({
            "korean": korean, "hanja": hanja, "romanization": romanization, "part_of_speech": part_of_speech,
            "meaning_en": meaning_en, "meaning_ur": meaning_ur, "example_ko": example_ko, "example_en": example_en,
            "example_ur": example_ur, "notes": notes, "category": category, "difficulty": difficulty,
        })
        now = to_iso(utc_now())
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO vocabulary ({', '.join(_FIELDS)}, source, starred, created_at, updated_at)"
                f" VALUES ({', '.join('?' * len(_FIELDS))}, ?, ?, ?, ?)",
                (*(values[f] for f in _FIELDS), source, int(starred), now, now),
            )
        return cur.lastrowid

    def update_word(self, vocab_id: int, **fields) -> None:
        """Edit a word. Marks it as edited, so bundled-list updates never overwrite it."""
        current = self.get(vocab_id)
        if current is None:
            raise KeyError(vocab_id)
        merged = {f: fields.get(f, getattr(current, f)) for f in _FIELDS}
        values = _clean_fields(merged)
        clash = self.find(values["korean"], values["meaning_en"])
        if clash is not None and clash != vocab_id:
            raise ValueError("Another word already has this Korean text and English meaning")
        with self.conn:
            self.conn.execute(
                f"UPDATE vocabulary SET {', '.join(f'{f} = ?' for f in _FIELDS)}, updated_at = ?, edited = 1 WHERE id = ?",
                (*(values[f] for f in _FIELDS), to_iso(utc_now()), vocab_id),
            )

    def delete_word(self, vocab_id: int) -> None:
        """Delete a word together with its progress and history (ON DELETE CASCADE)."""
        with self.conn:
            self.conn.execute("DELETE FROM vocabulary WHERE id = ?", (vocab_id,))

    def categories(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT category FROM vocabulary ORDER BY category")]

    def library(
        self,
        text: str = "",
        category: str | None = None,
        status: str | None = None,
        difficulty: int | None = None,
        now: datetime | None = None,
    ) -> list[LibraryRow]:
        """Words for the library table. `status` is a srs status, 'due', 'starred' or 'mine'."""
        where, params = [], []
        if text.strip():
            like = f"%{text.strip()}%"
            where.append(
                "(v.korean LIKE ? OR v.hanja LIKE ? OR v.romanization LIKE ? OR v.meaning_en LIKE ? OR v.meaning_ur LIKE ?)"
            )
            params += [like] * 5
        if category:
            where.append("v.category = ?")
            params.append(category)
        if difficulty:
            where.append("v.difficulty = ?")
            params.append(difficulty)
        if status == "due":
            where.append("p.due_at IS NOT NULL AND p.due_at <= ?")
            params.append(to_iso(now or utc_now()))
        elif status == "starred":
            where.append("v.starred = 1")
        elif status == "mine":
            where.append("v.source = 'user'")
        elif status:
            where.append("COALESCE(p.status, 'new') = ?")
            params.append(status)
        sql = (
            "SELECT v.id, v.korean, v.hanja, v.meaning_en, v.meaning_ur, v.category, v.difficulty, v.starred,"
            " v.source, COALESCE(p.status, 'new') AS status, p.due_at, COALESCE(p.times_seen, 0) AS times_seen,"
            " COALESCE(p.lapses, 0) AS lapses"
            " FROM vocabulary v LEFT JOIN progress p ON p.vocab_id = v.id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY v.category, v.id"
        )
        return [
            LibraryRow(**{**dict(r), "starred": bool(r["starred"]), "due_at": from_iso(r["due_at"])})
            for r in self.conn.execute(sql, params)
        ]

    def review_history(self, limit: int = 500) -> list[tuple[datetime, str, str, str, float]]:
        """Most recent ratings: (time, korean, meaning, rating, new interval in days)."""
        rows = self.conn.execute(
            "SELECT r.reviewed_at, v.korean, v.meaning_en, r.rating, r.interval_after FROM review_log r"
            " JOIN vocabulary v ON v.id = r.vocab_id ORDER BY r.reviewed_at DESC, r.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(from_iso(r[0]), r[1], r[2], r[3], r[4] or 0.0) for r in rows]

    # --- import / export ------------------------------------------------------

    def export_entries(self) -> list[dict]:
        """Every word as a plain dict (the same fields as the bundled list, plus starred)."""
        rows = self.conn.execute(f"SELECT {', '.join(_FIELDS)}, starred FROM vocabulary ORDER BY id").fetchall()
        return [{**{f: r[f] for f in _FIELDS}, "starred": bool(r["starred"])} for r in rows]

    def import_entries(self, entries: list[dict]) -> tuple[int, int, list[str]]:
        """Add words from an import. Returns (added, skipped duplicates, problems)."""
        added, skipped, problems = 0, 0, []
        for number, entry in enumerate(entries, start=1):
            try:
                korean, meaning = str(entry.get("korean", "")), str(entry.get("meaning_en", ""))
                if self.find(korean, meaning) is not None:
                    skipped += 1
                    continue
                fields = {f: entry.get(f, "") for f in _FIELDS if f in entry}
                fields.setdefault("category", "Imported")
                starred = str(entry.get("starred", "")).strip().lower() in ("1", "true", "yes")
                self.add_word(**fields, source="imported", starred=starred)
                added += 1
            except (ValueError, TypeError) as exc:
                problems.append(f"row {number}: {exc}")
        return added, skipped, problems

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
        Hanja or notes) only if the learner never edited them (edited = 0).
        Returns the number of new words.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("Could not read seed vocabulary from %s", path)
            return 0
        return self.apply_word_list(data)

    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row is not None else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def word_list_version(self) -> int:
        return int(self.meta("seed_version") or 0)

    def apply_word_list(self, data: dict) -> int:
        """Merge a curated word list (bundled or downloaded) if it is newer."""
        version = int(data.get("version", 0))
        if self.word_list_version() >= version:
            return 0

        now = to_iso(utc_now())
        added = 0
        with self.conn:
            for entry in data.get("entries", []):
                try:
                    clean = _clean_fields(entry if isinstance(entry, dict) else {})
                except ValueError:
                    continue  # a broken entry must not block the rest of the list
                values = [clean[f] for f in _FIELDS]
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
                        " WHERE korean = ? AND meaning_en = ? AND source = 'curated' AND edited = 0",
                        (*refresh.values(), clean["korean"], clean["meaning_en"]),
                    )
                self._merge_examples(clean["korean"], clean["meaning_en"], entry.get("examples"))
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES ('seed_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(version),),
            )
        log.info("Seed vocabulary v%s imported: %d new words.", version, added)
        return added

    def _merge_examples(self, korean: str, meaning_en: str, examples) -> None:
        """Store a list entry's extra sentences. For curated words the learner never
        edited, the list's sentences replace the old ones (so corrections arrive)."""
        if not isinstance(examples, list):
            return
        row = self.conn.execute(
            "SELECT id, source, edited FROM vocabulary WHERE korean = ? AND meaning_en = ?", (korean, meaning_en)
        ).fetchone()
        if row is None:
            return
        if row["source"] == "curated" and not row["edited"]:
            self.conn.execute("DELETE FROM examples WHERE vocab_id = ?", (row["id"],))
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            ko = str(ex.get("ko") or "").strip()
            if ko:
                self.conn.execute(
                    "INSERT OR IGNORE INTO examples(vocab_id, ko, en, ur, source) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], ko, str(ex.get("en") or "").strip(), str(ex.get("ur") or "").strip(),
                     str(ex.get("source") or "curated")),
                )

    # --- rotation support ---------------------------------------------------

    # Levels the learner studies (1 beginner, 2 intermediate, 3 advanced); None = all.
    study_levels: tuple[int, ...] | None = None

    def candidates(self) -> list[Candidate]:
        rows = self.conn.execute(
            "SELECT v.id, COALESCE(p.times_seen, 0) AS times_seen, COALESCE(p.status, 'new') AS status, p.due_at"
            " FROM vocabulary v LEFT JOIN progress p ON p.vocab_id = v.id"
            + self._level_filter()
        ).fetchall()
        if not rows and self.study_levels:  # no words at the chosen levels: use every word
            rows = self.conn.execute(
                "SELECT v.id, COALESCE(p.times_seen, 0) AS times_seen, COALESCE(p.status, 'new') AS status, p.due_at"
                " FROM vocabulary v LEFT JOIN progress p ON p.vocab_id = v.id"
            ).fetchall()
        return [
            Candidate(vocab_id=r["id"], times_seen=r["times_seen"], status=r["status"], due_at=from_iso(r["due_at"]))
            for r in rows
        ]

    def _level_filter(self) -> str:
        levels = [int(n) for n in self.study_levels or () if int(n) in (1, 2, 3)]
        # Words of other levels the learner already rated still come back when due.
        return (
            f" WHERE v.difficulty IN ({', '.join(map(str, levels))}) OR COALESCE(p.status, 'new') != 'new'"
            if levels and len(levels) < 3
            else ""
        )

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
            self.conn.execute("UPDATE vocabulary SET example_turn = example_turn + 1 WHERE id = ?", (vocab_id,))

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
