"""Reading and writing vocabulary files (CSV and JSON) for import/export.

CSV is written as UTF-8 with a BOM so Excel shows Korean and Urdu correctly.
JSON uses the same {"entries": [...]} layout as the bundled word list, so a
JSON export can be re-imported or shared.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .repository import WORD_FIELDS

COLUMNS = (*WORD_FIELDS, "starred")


def write_file(entries: list[dict], path: Path) -> None:
    if path.suffix.lower() == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for entry in entries:
                writer.writerow({c: entry.get(c, "") for c in COLUMNS})
    else:
        payload = {"format": "HangulFlow vocabulary", "version": 1, "entries": entries}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def read_file(path: Path) -> list[dict]:
    """Entries from a CSV or JSON file. Raises ValueError for unreadable files."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "korean" not in reader.fieldnames or "meaning_en" not in reader.fieldnames:
                raise ValueError("The CSV needs at least the columns 'korean' and 'meaning_en'.")
            return [dict(row) for row in reader]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from None
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ValueError("Expected a list of words, or an object with an 'entries' list.")
    return entries
