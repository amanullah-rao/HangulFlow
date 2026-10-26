"""Merge word batches from content/batches/*.txt into the bundled word list.

    .venv\\Scripts\\python.exe tools\\build_vocabulary.py

Batch format (one item per line, fields separated by " | "):

    + korean | hanja | romanization | part of speech | English | Urdu | category | level | notes
    > Korean sentence | English | Urdu          (3 or more per word; the first is the main example)
    = korean | level | English meaning (only needed if the Korean word has several entries)
    > ...                                        (extra sentences for that existing word)
    # comment

Level: 1 beginner, 2 intermediate, 3 advanced (curated estimates, not official TOPIK levels).
The list's version goes up by one whenever something changed, so installed apps pick
it up (bundled on the next build, or downloaded by the daily online check).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "hangulflow" / "resources" / "seed_vocabulary.json"
BATCHES = ROOT / "content" / "batches"
MIN_SENTENCES = 3


def split(line: str, required: int, total: int, where: str) -> list[str]:
    """The fields after the marker character, padded with "" to `total`."""
    parts = [p.strip() for p in line[1:].split(" | ")]
    if not required <= len(parts) <= total:
        raise SystemExit(f"{where}: expected {required}-{total} fields, got {len(parts)}: {line!r}")
    return parts + [""] * (total - len(parts))


def main() -> int:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    entries: list[dict] = data["entries"]
    index = {(e["korean"], e["meaning_en"]): e for e in entries}
    before = json.dumps(entries, ensure_ascii=False, sort_keys=True)
    warnings: list[str] = []
    seen_new: set[tuple[str, str]] = set()

    for path in sorted(BATCHES.glob("*.txt")):
        current: dict | None = None
        sentences: list[dict] = []

        def flush() -> None:
            if current is None:
                return
            new = [s for s in sentences if s["ko"] not in {current.get("example_ko")} | {x["ko"] for x in current.get("examples", [])}]
            if not current.get("example_ko") and new:
                main = new.pop(0)
                current.update(example_ko=main["ko"], example_en=main["en"], example_ur=main["ur"])
            if new:
                current.setdefault("examples", []).extend(new)
            total = bool(current.get("example_ko")) + len(current.get("examples", []))
            if total < MIN_SENTENCES:
                warnings.append(f"{path.name}: {current['korean']} has only {total} sentence(s)")

        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            where = f"{path.name}:{number}"
            if not line or line.startswith("#"):
                continue
            if line[0] in "+=":
                flush()
                sentences = []
            if line[0] == "+":
                ko, hanja, rom, pos, en, ur, cat, level, notes = split(line, 8, 9, where)
                key = (ko, en)
                if key in seen_new:
                    raise SystemExit(f"{where}: {ko} ({en}) is added twice")
                seen_new.add(key)
                if key in index:
                    # Never overwrite an earlier word by accident; edit it in place instead.
                    warnings.append(f"{where}: {ko} ({en}) already exists; skipped")
                    current = {"korean": ko, "meaning_en": en}  # throwaway: its sentences are ignored
                else:
                    current = {"korean": ko, "meaning_en": en}
                    entries.append(current)
                    index[key] = current
                    if any(k == ko for k, _ in index if (k, _) != key):
                        warnings.append(f"{where}: {ko} also exists with another meaning")
                current.update(
                    hanja=hanja, romanization=rom, part_of_speech=pos, meaning_ur=ur,
                    notes=notes, category=cat, difficulty=int(level),
                )
                for field in ("example_ko", "example_en", "example_ur"):
                    current.setdefault(field, "")
            elif line[0] == "=":
                ko, level, en = split(line, 1, 3, where)
                matches = [e for (k, m), e in index.items() if k == ko and (not en or m == en)]
                if len(matches) != 1:
                    raise SystemExit(f"{where}: {len(matches)} existing words match {ko} {en}".rstrip())
                current = matches[0]
                if level:
                    current["difficulty"] = int(level)
            elif line[0] == ">":
                if current is None:
                    raise SystemExit(f"{where}: sentence before any word")
                ko, en, ur = split(line, 3, 3, where)
                if not (ko and en and ur):
                    raise SystemExit(f"{where}: sentence needs Korean, English and Urdu")
                sentences.append({"ko": ko, "en": en, "ur": ur})
            else:
                raise SystemExit(f"{where}: unknown line {line!r}")
            if current is not None and current.get("difficulty") not in (1, 2, 3):
                raise SystemExit(f"{where}: level must be 1, 2 or 3")
        flush()

    changed = json.dumps(entries, ensure_ascii=False, sort_keys=True) != before
    if changed:
        data["version"] = int(data["version"]) + 1
        data["source_note"] = (
            "Curated by the HangulFlow project. Levels (1 beginner, 2 intermediate, 3 advanced) are "
            "editorial estimates, NOT official TOPIK level assignments."
        )
        body = ",\n".join("    " + json.dumps(e, ensure_ascii=False) for e in entries)
        head = json.dumps({k: v for k, v in data.items() if k != "entries"}, ensure_ascii=False, indent=2)[:-2]
        SEED.write_text(f'{head},\n  "entries": [\n{body}\n  ]\n}}\n', encoding="utf-8")

    sentences = sum(bool(e.get("example_ko")) + len(e.get("examples", [])) for e in entries)
    levels = Counter(e["difficulty"] for e in entries)
    print(f"{'Updated to' if changed else 'Unchanged:'} version {data['version']}: {len(entries)} words, "
          f"{sentences} sentences; beginner {levels[1]}, intermediate {levels[2]}, advanced {levels[3]}")
    for w in warnings:
        print("warning:", w)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
