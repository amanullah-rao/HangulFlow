"""Database backups: automatic daily copies, manual backups and restore.

Uses SQLite's online backup API, so a consistent copy is made even while the
app is running. Daily backups are kept for the last KEEP days; manual and
"before restore" backups are never deleted automatically.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .database import migrate

log = logging.getLogger(__name__)

KEEP = 14
DAILY_GLOB = "hangulflow-????-??-??.db"


def backup_path(folder: Path, day: date) -> Path:
    return folder / f"hangulflow-{day.isoformat()}.db"


def _copy(conn: sqlite3.Connection, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    try:
        dest = sqlite3.connect(tmp)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def daily_backup(conn: sqlite3.Connection, folder: Path, today: date | None = None, keep: int = KEEP) -> Path | None:
    """Create today's backup if it doesn't exist yet, then prune old daily ones."""
    target = backup_path(folder, today or date.today())
    if target.exists():
        return None
    try:
        _copy(conn, target)
    except (sqlite3.Error, OSError):
        log.exception("Daily backup failed")
        return None
    log.info("Backup written: %s", target.name)
    for old in sorted(folder.glob(DAILY_GLOB))[:-keep]:
        try:
            old.unlink()
        except OSError:
            log.warning("Could not delete old backup %s", old.name)
    return target


def manual_backup(conn: sqlite3.Connection, folder: Path, label: str = "manual") -> Path:
    target = folder / f"{label}-{datetime.now():%Y%m%d-%H%M%S}.db"
    _copy(conn, target)
    log.info("Backup written: %s", target.name)
    return target


def list_backups(folder: Path) -> list[Path]:
    """All backups, newest first."""
    if not folder.exists():
        return []
    return sorted(folder.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def restore(conn: sqlite3.Connection, source: Path, folder: Path) -> Path:
    """Replace the live database contents with a backup.

    A safety copy of the current state is written first and returned, so a
    restore can itself be undone. The live connection stays usable.
    """
    check = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("The backup file is damaged.")
        check.execute("SELECT COUNT(*) FROM vocabulary").fetchone()
        safety = manual_backup(conn, folder, label="before-restore")
        check.backup(conn)
    finally:
        check.close()
    migrate(conn)  # a backup from an older version gets the newer schema
    log.info("Restored database from %s (previous state saved as %s)", source.name, safety.name)
    return safety
