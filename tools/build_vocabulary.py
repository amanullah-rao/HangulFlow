"""Build the bundled word list: content/base_vocabulary.json + content/batches/*.txt.

    .venv\\Scripts\\python.exe tools\\build_vocabulary.py [--check]   (--check validates and writes nothing)

Batch format (one item per line, fields separated by "|"):

    + korean | hanja | romanization | part of speech | English | Urdu | category | level | notes
    > Korean sentence | English | Urdu          (3 or more per word; the first is the main example)
    = korean | level | English meaning (only needed if the Korean word has several entries)
    > ...                                        (extra sentences for that existing word)
    ~ similar word, another                      (synonyms of the word above, Korean, comma-separated)
    ! opposite word                              (antonyms of the word above)
    # comment

content/relations.txt links words both ways (so each pair is written once):

    크다 ! 작다              (opposites: 크다 gets 작다 and 작다 gets 크다)
    노력 ~ 애씀, 수고        (similar words)
    배=ship ~ 선박           (=English meaning picks one of several entries with the same Korean)

Level: 1 beginner, 2 intermediate, 3 advanced (curated estimates, not official TOPIK levels).
The output is rebuilt from scratch every run, so the tool can be re-run safely. Its
version goes up by one whenever the result differs from the current file, so installed
apps pick it up (bundled on the next build, or downloaded by the daily online check).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "hangulflow" / "resources" / "seed_vocabulary.json"
BASE = ROOT / "content" / "base_vocabulary.json"
BATCHES = ROOT / "content" / "batches"
RELATIONS = ROOT / "content" / "relations.txt"
MIN_SENTENCES = 3


def split(line: str, required: int, total: int, where: str) -> list[str]:
    """The fields after the marker character, padded with "" to `total`."""
    parts = [p.strip() for p in line[1:].split("|")]
    while len(parts) > total and not parts[-1]:
        parts.pop()
    if not required <= len(parts) <= total:
        raise SystemExit(f"{where}: expected {required}-{total} fields, got {len(parts)}: {line!r}")
    return parts + [""] * (total - len(parts))


def apply_relations(entries: list[dict], warnings: list[str]) -> None:
    """Add the word pairs from content/relations.txt to both words of each pair."""
    if not RELATIONS.exists():
        return
    by_korean: dict[str, list[dict]] = {}
    for e in entries:
        by_korean.setdefault(e["korean"], []).append(e)

    def lookup(word: str, where: str) -> dict | None:
        ko, _, en = word.partition("=")
        found = [e for e in by_korean.get(ko.strip(), []) if not en or e["meaning_en"].startswith(en.strip())]
        if len(found) > 1:
            raise SystemExit(f"{where}: {ko} has {len(found)} entries; write it as {ko}=English meaning")
        return found[0] if found else None

    def link(entry: dict, field: str, word: str) -> None:
        words = [w for w in entry.get(field, "").split(", ") if w]
        if word not in words and word != entry["korean"]:
            entry[field] = ", ".join(words + [word])

    for number, raw in enumerate(RELATIONS.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        where = f"{RELATIONS.name}:{number}"
        mark = "!" if " ! " in line else "~" if " ~ " in line else None
        if mark is None:
            raise SystemExit(f"{where}: expected 'word ! opposites' or 'word ~ similar words': {raw!r}")
        left, right = (s.strip() for s in line.split(f" {mark} ", 1))
        field = "antonyms" if mark == "!" else "synonyms"
        head = lookup(left, where)
        if head is None:
            raise SystemExit(f"{where}: {left} is not in the word list")
        for word in (w.strip() for w in right.split(",") if w.strip()):
            other = lookup(word, where)
            link(head, field, word.partition("=")[0])
            if other is not None:
                link(other, field, head["korean"])
            elif mark == "!":
                warnings.append(f"{where}: opposite {word} of {left} is not in the word list (shown without meaning)")


def main(check: bool = False) -> int:
    current_seed = json.loads(SEED.read_text(encoding="utf-8"))
    data = json.loads(BASE.read_text(encoding="utf-8"))
    entries: list[dict] = data["entries"]
    index = {(e["korean"], e["meaning_en"]): e for e in entries}
    before = json.dumps(current_seed["entries"], ensure_ascii=False, sort_keys=True)
    data["version"] = int(current_seed["version"])
    warnings: list[str] = []
    homonyms: list[str] = []
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
                missing = [n for n, v in (("romanization", rom), ("part of speech", pos), ("Urdu", ur), ("category", cat)) if not v]
                if missing:
                    raise SystemExit(f"{where}: {ko} is missing {', '.join(missing)}")
                if not rom.isascii():
                    raise SystemExit(f"{where}: romanization of {ko} has non-Latin letters: {rom!r}")
                if " (" in ko and not ko.startswith("-"):
                    raise SystemExit(f"{where}: put notes in the notes field, not in the Korean word: {ko!r}")
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
                        homonyms.append(ko)
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
            elif line[0] in "~!":
                if current is None:
                    raise SystemExit(f"{where}: related words before any word")
                field = "synonyms" if line[0] == "~" else "antonyms"
                words = [w.strip() for w in line[1:].split(",") if w.strip()]
                if not words or any("|" in w or not any("가" <= ch <= "힣" for ch in w) for w in words):
                    raise SystemExit(f"{where}: {field} must be Korean words separated by commas: {line!r}")
                if current["korean"] in words:
                    raise SystemExit(f"{where}: {current['korean']} lists itself in its {field}")
                current[field] = ", ".join(dict.fromkeys(words))
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

    apply_relations(entries, warnings)

    changed = json.dumps(entries, ensure_ascii=False, sort_keys=True) != before
    if changed and not check:
        data["version"] = int(data["version"]) + 1
        data["source_note"] = (
            "Curated by the HangulFlow project. Levels (1 beginner, 2 intermediate, 3 advanced) are "
            "editorial estimates, NOT official TOPIK level assignments."
        )
        body = ",\n".join("    " + json.dumps(e, ensure_ascii=False) for e in entries)
        head = json.dumps({k: v for k, v in data.items() if k != "entries"}, ensure_ascii=False, indent=2)[:-2]
        SEED.write_text(f'{head},\n  "entries": [\n{body}\n  ]\n}}\n', encoding="utf-8", newline="\n")

    sentences = sum(bool(e.get("example_ko")) + len(e.get("examples", [])) for e in entries)
    levels = Counter(e["difficulty"] for e in entries)
    status = "Would update" if changed and check else "Updated to" if changed else "Unchanged:"
    print(f"{status} version {data['version']}: {len(entries)} words, "
          f"{sentences} sentences; beginner {levels[1]}, intermediate {levels[2]}, advanced {levels[3]}")
    if homonyms:
        print(f"{len(homonyms)} homonyms (same Korean, another meaning): {', '.join(homonyms)}")
    for w in warnings:
        print("warning:", w)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(check="--check" in sys.argv))
