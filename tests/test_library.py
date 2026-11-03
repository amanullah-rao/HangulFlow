import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from hangulflow import backup, srs, transfer
from hangulflow.database import open_database
from hangulflow.paths import seed_vocabulary_path
from hangulflow.repository import VocabRepository


@pytest.fixture
def repo(tmp_path):
    r = VocabRepository(open_database(tmp_path / "t.db"))
    r.import_seed(seed_vocabulary_path())
    return r


def test_search_in_every_language(repo):
    found = [r.korean for r in repo.library("노력")]
    assert "노력" in found and all("노력" in k for k in found)
    assert "노력" in [r.korean for r in repo.library("努力")]        # Hanja
    assert "노력" in [r.korean for r in repo.library("hard work")]   # English
    assert "노력" in [r.korean for r in repo.library("محنت")]        # Urdu
    assert repo.library("no such word xyz") == []


def test_filters(repo):
    grammar = repo.library(category="Grammar Patterns")
    assert len(grammar) >= 20 and {r.category for r in grammar} == {"Grammar Patterns"}
    assert all(r.difficulty == 3 for r in repo.library(difficulty=3))
    first, second = repo.library()[:2]
    now = datetime.now(timezone.utc)
    repo.rate(first.id, srs.UNKNOWN, now - timedelta(hours=1))   # due again already
    repo.mark_learned(second.id, now)
    repo.set_starred(second.id, True)
    assert [r.id for r in repo.library(status="due")] == [first.id]
    assert [r.id for r in repo.library(status="learned")] == [second.id]
    assert [r.id for r in repo.library(status="starred")] == [second.id]
    assert len(repo.library(status="new")) == repo.count() - 2
    assert repo.review_history()[0][1] == second.korean  # newest first


def test_edit_protects_from_seed_refresh_and_rejects_clash(repo):
    row = next(r for r in repo.library("노력") if r.korean == "노력")
    repo.update_word(row.id, notes="my own note", difficulty=3)
    v = repo.get(row.id)
    assert v.notes == "my own note" and v.difficulty == 3 and v.korean == "노력"
    assert repo.conn.execute("SELECT edited FROM vocabulary WHERE id = ?", (row.id,)).fetchone()[0] == 1
    # A newer bundled list must not overwrite the edit, even within the same second.
    repo.conn.execute("UPDATE meta SET value = '0' WHERE key = 'seed_version'")
    repo.import_seed(seed_vocabulary_path())
    assert repo.get(row.id).notes == "my own note"
    other = repo.library("과제")[0]
    with pytest.raises(ValueError):
        repo.update_word(other.id, korean="노력", meaning_en=v.meaning_en)


def test_delete_cascades(repo):
    row = repo.library()[0]
    repo.rate(row.id, srs.KNOWN)
    repo.delete_word(row.id)
    assert repo.get(row.id) is None
    assert repo.conn.execute("SELECT COUNT(*) FROM review_log WHERE vocab_id = ?", (row.id,)).fetchone()[0] == 0


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_export_then_import_roundtrip(repo, tmp_path, suffix):
    path = tmp_path / f"words{suffix}"
    transfer.write_file(repo.export_entries(), path)
    entries = transfer.read_file(path)
    assert len(entries) == repo.count()
    assert any(e["meaning_ur"] == "کوشش، محنت" for e in entries)  # Urdu survives the file

    fresh = VocabRepository(open_database(tmp_path / f"fresh{suffix}.db"))
    added, skipped, problems = fresh.import_entries(entries)
    assert (added, skipped, problems) == (repo.count(), 0, [])
    assert fresh.import_entries(entries)[1] == repo.count()  # second import: all duplicates


def test_import_reports_bad_rows(repo, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("korean,meaning_en,difficulty\n눈치,tact,2\n,missing korean,1\n멋,style,abc\n", encoding="utf-8")
    added, skipped, problems = repo.import_entries(transfer.read_file(path))
    assert added == 1 and len(problems) == 2
    with pytest.raises(ValueError):
        transfer.read_file(tmp_path / "x.csv") if (tmp_path / "x.csv").write_text("a,b\n1,2\n") else None


def test_manual_backup_and_restore(repo, tmp_path):
    folder = tmp_path / "backups"
    saved = backup.manual_backup(repo.conn, folder)
    total = repo.count()
    repo.delete_word(repo.library()[0].id)
    assert repo.count() == total - 1

    safety = backup.restore(repo.conn, saved, folder)
    assert repo.count() == total                      # the live connection sees restored data
    assert sqlite3.connect(safety).execute("SELECT COUNT(*) FROM vocabulary").fetchone()[0] == total - 1
    assert {p.name for p in backup.list_backups(folder)} == {saved.name, safety.name}


def test_restore_rejects_damaged_file(repo, tmp_path):
    bad = tmp_path / "broken.db"
    bad.write_bytes(b"not a database" * 50)
    with pytest.raises(sqlite3.DatabaseError):
        backup.restore(repo.conn, bad, tmp_path / "backups")
    assert repo.count() > 0


def test_example_sentences_rotate(repo):
    vocab_id = repo.add_word("시험용", "test word", example_ko="첫째 문장")
    with repo.conn:
        repo.conn.executemany(
            "INSERT INTO examples(vocab_id, ko, en, ur) VALUES (?, ?, ?, ?)",
            [(vocab_id, "둘째 문장", "second", "دوسرا"), (vocab_id, "셋째 문장", "third", "تیسرا")],
        )
    shown = []
    for _ in range(4):
        repo.record_view(vocab_id)
        shown.append(repo.get(vocab_id).example_for_display()[0])
    assert shown == ["첫째 문장", "둘째 문장", "셋째 문장", "첫째 문장"]
    repo.delete_word(vocab_id)  # extra sentences go with the word
    assert repo.conn.execute("SELECT COUNT(*) FROM examples WHERE vocab_id = ?", (vocab_id,)).fetchone()[0] == 0


def test_study_levels_filter_new_words(repo):
    levels = dict(repo.conn.execute("SELECT id, difficulty FROM vocabulary").fetchall())
    started = next(i for i, d in levels.items() if d == 3)
    repo.rate(started, "known")
    repo.study_levels = (1,)
    ids = {c.vocab_id for c in repo.candidates()}
    assert started in ids  # words already being learned still come back
    assert all(levels[i] == 1 for i in ids - {started})
    repo.study_levels = None
    assert len(repo.candidates()) == len(levels)


def test_word_list_examples_merge(repo):
    entry = {"korean": "새말", "meaning_en": "new word", "category": "x",
             "example_ko": "첫 문장", "examples": [{"ko": "둘째", "en": "2", "ur": "۲"}, {"ko": ""}, "junk"]}
    assert repo.apply_word_list({"version": 99, "entries": [entry]}) == 1
    vocab = repo.get(repo.find("새말", "new word"))
    assert [e[0] for e in vocab.examples] == ["첫 문장", "둘째"]


def test_recent_views_follow_click_order_even_within_one_second(repo):
    """Regression: timestamps have 1-second precision, so fast Next clicks used to
    tie and the 'last shown' word was arbitrary - the same words kept coming back."""
    ids = [c.vocab_id for c in repo.candidates()[:5]]
    stamp = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
    for vid in ids:
        repo.record_view(vid, stamp)  # all in the same second
    assert repo.recent_view_ids(5) == list(reversed(ids))
