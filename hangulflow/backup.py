"""Automatic daily backups of the SQLite database.

Uses SQLite's online backup API, so a consistent copy is made even while the
app is running. One backup per day is kept for the last KEEP days.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

KEEP = 14
PREFIX = "hangulflow-"


def backup_path(folder: Path, day: date) -> Path:
    return folder / f"{PREFIX}{day.isoformat()}.db"


def daily_backup(conn: sqlite3.Connection, folder: Path, today: date | None = None, keep: int = KEEP) -> Path | None:
    """Create today's backup if it doesn't exist yet, then prune old ones."""
    today = today or date.today()
    folder.mkdir(parents=True, exist_ok=True)
    target = backup_path(folder, today)
    if target.exists():
        return None
    tmp = target.with_suffix(".tmp")
    try:
        dest = sqlite3.connect(tmp)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        tmp.replace(target)
    except (sqlite3.Error, OSError):
        log.exception("Daily backup failed")
        tmp.unlink(missing_ok=True)
        return None
    log.info("Backup written: %s", target.name)
    _prune(folder, keep)
    return target


def _prune(folder: Path, keep: int) -> None:
    backups = sorted(folder.glob(f"{PREFIX}*.db"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            log.warning("Could not delete old backup %s", old.name)
