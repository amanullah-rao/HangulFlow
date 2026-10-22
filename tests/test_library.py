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
    assert [r.korean for r in repo.library("노력")] == ["노력"]
    assert "노력" in [r.korean for r in repo.library("努力")]        # Hanja
    assert "노력" in [r.korean for r in repo.library("hard work")]   # English
    assert "노력" in [r.korean for r in repo.library("محنت")]        # Urdu
    assert repo.library("no such word xyz") == []


def test_filters(repo):
    grammar = repo.library(category="Grammar Patterns")
    assert len(grammar) == 20 and {r.category for r in grammar} == {"Grammar Patterns"}
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
    row = repo.library("노력")[0]
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
