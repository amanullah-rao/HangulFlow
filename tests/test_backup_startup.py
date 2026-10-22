import sqlite3
import sys
from datetime import date, timedelta

import pytest

from hangulflow import backup, startup
from hangulflow.database import open_database


def test_daily_backup_once_per_day_and_pruned(tmp_path):
    conn = open_database(tmp_path / "live.db")
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('probe', 'ok')")
    folder = tmp_path / "backups"
    start = date(2026, 10, 1)

    first = backup.daily_backup(conn, folder, start)
    assert first is not None and backup.daily_backup(conn, folder, start) is None  # only once a day
    copy = sqlite3.connect(first)
    assert copy.execute("SELECT value FROM meta WHERE key = 'probe'").fetchone()[0] == "ok"
    copy.close()

    for i in range(1, 20):
        backup.daily_backup(conn, folder, start + timedelta(days=i), keep=5)
    names = sorted(p.name for p in folder.glob("*.db"))
    assert len(names) == 5 and names[-1] == "hangulflow-2026-10-20.db"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_startup_toggle_uses_registry(tmp_path):
    key = r"Software\HangulFlowTest\Run"  # a scratch key, never the real Run key
    try:
        assert not startup.is_enabled(key)
        assert startup.set_enabled(True, key) and startup.is_enabled(key)
        assert "main.py" in startup.launch_command() or startup.launch_command().endswith('.exe"')
        assert startup.set_enabled(False, key) and not startup.is_enabled(key)
        assert startup.set_enabled(False, key)  # disabling twice is fine
    finally:
        import winreg

        for path in (key, r"Software\HangulFlowTest"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass
