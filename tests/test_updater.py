import json

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from hangulflow.database import open_database
from hangulflow.paths import seed_vocabulary_path
from hangulflow.repository import VocabRepository
from hangulflow.updater import WordUpdater, parse_word_list


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def repo(tmp_path):
    r = VocabRepository(open_database(tmp_path / "t.db"))
    r.import_seed(seed_vocabulary_path())
    return r


def write_list(path, version, entries):
    path.write_text(json.dumps({"version": version, "entries": entries}, ensure_ascii=False), encoding="utf-8")
    return path.as_uri()  # urllib reads file:// URLs, so no network is needed


def run_check(updater, force=True):
    results = []
    loop = QEventLoop()
    updater.finished.connect(lambda added, error: (results.append((added, error)), loop.quit()))
    assert updater.check(force=force)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    return results[0]


NEW = {"korean": "보람", "meaning_en": "worthwhile feeling", "meaning_ur": "اطمینان", "category": "Emotions & Relationships"}


def test_parse_rejects_wrong_shapes():
    with pytest.raises(ValueError):
        parse_word_list(b"[]")
    with pytest.raises(ValueError):
        parse_word_list(b'{"entries": []}')  # no version
    assert parse_word_list(b'{"version": 9, "entries": []}')["version"] == 9


def test_newer_list_adds_words_and_skips_broken_entries(qapp, repo, tmp_path):
    before = repo.count()
    url = write_list(tmp_path / "w.json", repo.word_list_version() + 1, [NEW, {"korean": ""}, "junk"])
    added, error = run_check(WordUpdater(repo, url))
    assert (added, error) == (1, "")
    assert repo.count() == before + 1 and repo.find("보람", "worthwhile feeling") is not None


def test_same_version_adds_nothing_and_daily_limit_applies(qapp, repo, tmp_path):
    url = write_list(tmp_path / "w.json", repo.word_list_version(), [NEW])
    updater = WordUpdater(repo, url)
    assert run_check(updater) == (0, "")
    assert repo.find("보람", "worthwhile feeling") is None
    assert not updater.check()  # checked moments ago: the automatic check waits a day


def test_edited_words_survive_an_online_update(qapp, repo, tmp_path):
    word_id = repo.find("노력", "effort, hard work")
    repo.update_word(word_id, notes="my own note")
    entry = {"korean": "노력", "meaning_en": "effort, hard work", "notes": "server note", "category": "x"}
    run_check(WordUpdater(repo, write_list(tmp_path / "w.json", repo.word_list_version() + 1, [entry])))
    assert repo.get(word_id).notes == "my own note"


def test_offline_fails_quietly(qapp, repo, tmp_path):
    added, error = run_check(WordUpdater(repo, (tmp_path / "missing.json").as_uri()))
    assert added == 0 and error
