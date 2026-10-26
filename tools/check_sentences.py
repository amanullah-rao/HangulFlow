"""Flag example sentences that may not contain their word.

    .venv\\Scripts\\python.exe tools\\check_sentences.py content\\batches\\33-*.txt

Only the word's first syllable is looked for, so conjugated forms that change the
stem (듣다 -> 들어요, 춥다 -> 추워요) show up too: a review aid, not a rule.
"""

from __future__ import annotations

import glob
import re
import sys


def main(patterns: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    flagged = 0
    for path in sorted({p for pattern in patterns for p in glob.glob(pattern)}):
        word = None
        for line in open(path, encoding="utf-8"):
            if line.startswith(("+ ", "= ")):
                fields = [f.strip() for f in line[2:].split("|")]
                is_grammar = line.startswith("+ ") and len(fields) > 3 and fields[3] == "grammar"
                word = None if is_grammar or fields[0].startswith("-") else re.sub(r"[^가-힣]", "", fields[0])
            elif line.startswith("> ") and word:
                sentence = line[2:].split("|")[0]
                if word[0] not in sentence:
                    flagged += 1
                    print(f"{path}: {word}: {sentence.strip()}")
    print(f"{flagged} sentences to review")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["content/batches/*.txt"]))
