import json
import sqlite3

from datetime import datetime, timedelta, timezone

from hangulflow import srs
from hangulflow.database import SCHEMA_V1, SCHEMA_VERSION, open_database
from hangulflow.paths import seed_vocabulary_path
from hangulflow.repository import VocabRepository
from hangulflow.settings import Settings, SettingsStore


def test_seed_file_is_complete():
    data = json.loads(seed_vocabulary_path().read_text(encoding="utf-8"))
    required = ("korean", "romanization", "part_of_speech", "meaning_en", "meaning_ur",
                "example_ko", "example_en", "example_ur", "category", "difficulty")
    for entry in data["entries"]:
        for field in required:
            assert entry.get(field) not in (None, ""), (entry.get("korean"), field)
        assert 1 <= entry["difficulty"] <= 3
    keys = [(e["korean"], e["meaning_en"]) for e in data["entries"]]
    assert len(keys) == len(set(keys))


def test_seed_import_is_idempotent(tmp_path):
    repo = VocabRepository(open_database(tmp_path / "t.db"))
    added = repo.import_seed(seed_vocabulary_path())
    assert added > 0 and repo.count() == added
    assert repo.import_seed(seed_vocabulary_path()) == 0
    assert repo.count() == added


def test_v1_database_migrates_and_keeps_data(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_V1 + "\nPRAGMA user_version = 1;")
    conn.execute(
        "INSERT INTO vocabulary (korean, meaning_en, created_at, updated_at) VALUES ('노력', 'effort, hard work', 'x', 'x')"
    )
    conn.commit()
    conn.close()

    conn = open_database(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert tuple(conn.execute("SELECT korean, hanja FROM vocabulary").fetchone()) == ("노력", "")


def test_seed_refresh_respects_user_edits(tmp_path):
    def write_seed(version, notes):
        path = tmp_path / f"seed{version}.json"
        entries = [
            {"korean": k, "hanja": h, "meaning_en": en, "notes": notes, "category": "Test", "difficulty": 1}
            for k, h, en in (("노력", "努力", "effort"), ("과제", "課題", "assignment"))
        ]
        path.write_text(json.dumps({"version": version, "entries": entries}, ensure_ascii=False), encoding="utf-8")
        return path

    conn = open_database(tmp_path / "t.db")
    repo = VocabRepository(conn)
    repo.import_seed(write_seed(1, "old"))
    with conn:  # the learner edits one word
        conn.execute("UPDATE vocabulary SET notes = 'mine', updated_at = 'later' WHERE korean = '과제'")
    repo.import_seed(write_seed(2, "new"))

    notes = dict(conn.execute("SELECT korean, notes FROM vocabulary").fetchall())
    assert notes == {"노력": "new", "과제": "mine"}


def test_rating_persists_logs_and_counts_toward_stats(tmp_path):
    db = tmp_path / "t.db"
    repo = VocabRepository(open_database(db))
    repo.import_seed(seed_vocabulary_path())
    a, b = [c.vocab_id for c in repo.candidates()[:2]]
    now = datetime.now(timezone.utc)

    repo.rate(a, srs.UNKNOWN, now)
    repo.rate(a, srs.KNOWN, now)
    repo.mark_learned(b, now)

    repo = VocabRepository(open_database(db))  # survives a restart
    assert repo.card_state(a).status == srs.REVIEW
    assert repo.card_state(b).status == srs.LEARNED
    assert repo.conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0] == 3

    s = repo.stats(now)
    assert s.rated_today == 2 and s.learned == 1 and s.learning == 1
    assert s.new == s.total - 2 and s.streak_days == 1
    assert s.last_7_days[-1][1] == 2 and len(s.last_7_days) == 7
    assert repo.stats(now + timedelta(days=2)).due_now == 1  # word a is due again after 1 day


def test_add_word_and_star(tmp_path):
    repo = VocabRepository(open_database(tmp_path / "t.db"))
    vid = repo.add_word("눈치", "tact, social awareness", "سمجھ بوجھ")
    v = repo.get(vid)
    assert v.starred and v.source == "user" and v.category == "My Words"
    repo.set_starred(vid, False)
    assert not repo.get(vid).starred


def test_record_view_updates_progress(tmp_path):
    repo = VocabRepository(open_database(tmp_path / "t.db"))
    repo.import_seed(seed_vocabulary_path())
    first = repo.candidates()[0].vocab_id
    repo.record_view(first)
    repo.record_view(first)
    seen = {c.vocab_id: c.times_seen for c in repo.candidates()}
    assert seen[first] == 2
    assert repo.recent_view_ids(5) == [first]


def test_corrupted_database_is_replaced(tmp_path):
    db = tmp_path / "t.db"
    db.write_bytes(b"this is not a sqlite file" * 100)
    repo = VocabRepository(open_database(db))
    assert repo.count() == 0
    assert any(p.name.startswith("t.corrupt-") for p in tmp_path.iterdir())


def test_settings_roundtrip_and_corruption(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load() == Settings()
    store.save(Settings(interval_minutes=5, compact=True, x=10, y=20))
    loaded = store.load()
    assert (loaded.interval_minutes, loaded.compact, loaded.x) == (5, True, 10)

    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert store.load() == Settings()
    assert (tmp_path / "settings.corrupt.json").exists()


def test_settings_values_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"interval_minutes": 7, "opacity": 5, "width": 9999, "x": "oops"}), encoding="utf-8")
    s = SettingsStore(path).load()
    assert s.interval_minutes == 10 and s.opacity == 1.0 and s.width == 560 and s.x is None
