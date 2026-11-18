import hashlib
import json

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from hangulflow import __version__
from hangulflow.app_update import AppUpdater, Release, download_installer, is_newer, parse_release, version_tuple
from hangulflow.database import open_database
from hangulflow.repository import VocabRepository


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def repo(tmp_path):
    return VocabRepository(open_database(tmp_path / "t.db"))


def release_json(tag, url="", digest=""):
    asset = {"name": f"HangulFlow-Setup-{tag.lstrip('v')}.exe", "browser_download_url": url, "size": 3}
    if digest:
        asset["digest"] = digest
    return {"tag_name": tag, "html_url": "https://example.invalid/r", "assets": [asset]}


def test_versions_compare_as_numbers():
    assert version_tuple("v0.10.2") == (0, 10, 2)
    assert is_newer("0.10.0", "0.9.9")
    assert is_newer("v1.0", "0.4.0")
    assert not is_newer("0.4.0", "0.4.0")
    assert not is_newer("0.3.9", "0.4.0")


def test_release_json_gives_installer_and_hash():
    r = parse_release(json.dumps(release_json("v9.0.0", "https://x/setup.exe", "sha256:ABC")).encode())
    assert (r.version, r.installer_url, r.sha256) == ("9.0.0", "https://x/setup.exe", "abc")
    no_hash = parse_release(json.dumps(release_json("v9.0.0", "https://x/setup.exe")).encode())
    assert no_hash.sha256 == ""   # the app then only offers the download page
    with pytest.raises(ValueError):
        parse_release(b'{"message": "Not Found"}')


def test_installer_is_kept_only_if_its_hash_matches(tmp_path):
    source = tmp_path / "setup.exe"
    source.write_bytes(b"installer bytes")
    good = hashlib.sha256(b"installer bytes").hexdigest()
    release = Release("9.0.0", "", source.as_uri(), "HangulFlow-Setup-9.0.0.exe", good)
    path = download_installer(release, tmp_path / "out")
    assert path.read_bytes() == b"installer bytes"
    bad = Release("9.0.0", "", source.as_uri(), "HangulFlow-Setup-9.0.0.exe", "0" * 64)
    with pytest.raises(ValueError):
        download_installer(bad, tmp_path / "bad")
    assert not (tmp_path / "bad" / "HangulFlow-Setup-9.0.0.exe").exists()   # a bad download is deleted


def run_check(updater):
    results = []
    loop = QEventLoop()
    updater.checked.connect(lambda release, error: (results.append((release, error)), loop.quit()))
    assert updater.check(force=True)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    return results[0]


def test_updater_reports_only_newer_releases(qapp, repo, tmp_path):
    feed = tmp_path / "latest.json"
    feed.write_text(json.dumps(release_json("v99.0.0")), encoding="utf-8")
    release, error = run_check(AppUpdater(repo, feed.as_uri()))
    assert release.version == "99.0.0" and error == ""

    feed.write_text(json.dumps(release_json("v" + __version__)), encoding="utf-8")
    release, error = run_check(AppUpdater(repo, feed.as_uri()))
    assert release is None and error == ""


def test_updater_offline_is_quiet(qapp, repo, tmp_path):
    release, error = run_check(AppUpdater(repo, (tmp_path / "missing.json").as_uri()))
    assert release is None and error
