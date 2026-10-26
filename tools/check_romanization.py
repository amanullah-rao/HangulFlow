"""List words whose romanization differs from a rule-based Revised Romanization.

    .venv\\Scripts\\python.exe tools\\check_romanization.py

A review aid, not an authority: Revised Romanization follows pronunciation, and
some words have irregular pronunciations (for example tensing that RR ignores,
or ㅎ that RR keeps in nouns), so every difference needs a human look.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "hangulflow" / "resources" / "seed_vocabulary.json"

INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
VOWELS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
# Final consonant index -> (consonant kept before a vowel, its sound before a consonant/end)
FINALS = [None, "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
INITIAL_JAMO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
NEUTRAL = {"ㄱ": "ㄱ", "ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄳ": "ㄱ", "ㄺ": "ㄱ", "ㄴ": "ㄴ", "ㄵ": "ㄴ", "ㄶ": "ㄴ",
           "ㄷ": "ㄷ", "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ", "ㅊ": "ㄷ", "ㅌ": "ㄷ", "ㅎ": "ㄷ",
           "ㄹ": "ㄹ", "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ", "ㅀ": "ㄹ", "ㄻ": "ㅁ", "ㅁ": "ㅁ",
           "ㅂ": "ㅂ", "ㅍ": "ㅂ", "ㅄ": "ㅂ", "ㄿ": "ㅂ", "ㅇ": "ㅇ"}
FINAL_ROMAN = {"ㄱ": "k", "ㄴ": "n", "ㄷ": "t", "ㄹ": "l", "ㅁ": "m", "ㅂ": "p", "ㅇ": "ng", "": ""}
# Two-consonant finals split before a vowel: first part stays, second moves on.
SPLIT = {"ㄳ": ("ㄱ", "ㅅ"), "ㄵ": ("ㄴ", "ㅈ"), "ㄺ": ("ㄹ", "ㄱ"), "ㄻ": ("ㄹ", "ㅁ"), "ㄼ": ("ㄹ", "ㅂ"),
         "ㄽ": ("ㄹ", "ㅅ"), "ㄾ": ("ㄹ", "ㅌ"), "ㄿ": ("ㄹ", "ㅍ"), "ㅄ": ("ㅂ", "ㅅ"), "ㄲ": ("", "ㄲ"), "ㅆ": ("", "ㅆ")}
ASPIRATE = {"ㄱ": "ㅋ", "ㄷ": "ㅌ", "ㅂ": "ㅍ", "ㅈ": "ㅊ"}


def decompose(text: str) -> list[list[str]]:
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append([INITIAL_JAMO[code // 588], VOWELS[(code % 588) // 28], FINALS[code % 28] or ""])
    return out


def romanize_word(word: str) -> str:
    syl = decompose(word)
    for i in range(len(syl) - 1):
        final, nxt = syl[i][2], syl[i + 1]
        if not final:
            continue
        if nxt[0] == "ㅇ":  # liaison: the final moves to the next syllable
            if final in ("ㅎ", "ㄶ", "ㅀ"):
                syl[i][2], nxt[0] = "", {"ㅎ": "ㅇ", "ㄶ": "ㄴ", "ㅀ": "ㄹ"}[final]
            elif final == "ㅇ":
                pass
            elif final in SPLIT:
                syl[i][2], nxt[0] = SPLIT[final]
            else:
                moved = final
                if nxt[1] == "i" and final in ("ㄷ", "ㅌ"):
                    moved = {"ㄷ": "ㅈ", "ㅌ": "ㅊ"}[final]
                syl[i][2], nxt[0] = "", moved
            continue
        if final in ("ㅎ", "ㄶ", "ㅀ") and nxt[0] in ASPIRATE:  # ㅎ + ㄱ/ㄷ/ㅈ -> aspirated
            nxt[0] = ASPIRATE[nxt[0]]
            syl[i][2] = {"ㅎ": "", "ㄶ": "ㄴ", "ㅀ": "ㄹ"}[final]
            continue
        sound = NEUTRAL.get(final, final)
        if nxt[0] == "ㅎ" and sound in ASPIRATE:  # ㄱ/ㄷ/ㅂ + ㅎ -> aspirated
            nxt[0] = "ㅊ" if sound == "ㄷ" and nxt[1] == "i" else ASPIRATE[sound]
            syl[i][2] = "ㄹ" if final in ("ㄺ", "ㄼ") else ""
            continue
        if final == "ㄺ" and nxt[0] == "ㄱ":  # 읽기 -> il-gi
            sound = "ㄹ"
        if nxt[0] in ("ㄴ", "ㅁ"):  # nasalization
            sound = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}.get(sound, sound)
            if sound == "ㄹ" and nxt[0] == "ㄴ":
                nxt[0] = "ㄹ"
        elif nxt[0] == "ㄹ":
            if sound == "ㄴ":
                sound = "ㄹ"
            elif sound in ("ㅁ", "ㅇ"):
                nxt[0] = "ㄴ"
            elif sound in ("ㄱ", "ㄷ", "ㅂ"):
                sound = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}[sound]
                nxt[0] = "ㄴ"
        syl[i][2] = sound
    parts = []
    for i, (ini, vow, fin) in enumerate(syl):
        r = INITIALS[INITIAL_JAMO.index(ini)]
        if ini == "ㄹ" and i > 0 and syl[i - 1][2] == "ㄹ":
            r = "l"
        parts.append(r + vow + FINAL_ROMAN[NEUTRAL.get(fin, fin) if fin else ""])
    return "".join(parts)


def romanize(text: str) -> str:
    return re.sub(r"[가-힣]+", lambda m: romanize_word(m.group()), text)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    entries = json.loads(SEED.read_text(encoding="utf-8"))["entries"]
    diffs = 0
    for e in entries:
        if e["part_of_speech"] == "grammar":
            continue
        expected = romanize(e["korean"]).replace(" ", "")
        given = e["romanization"].replace(" ", "").replace("-", "").lower()
        # RR keeps ㅎ after ㄱ/ㄷ/ㅂ in 하다 verbs and nouns, so "kh"/"ph"/"th" spellings are fine.
        relaxed = re.sub(r"(k|p|t)h", lambda m: m.group(1), given)
        if e["korean"].count(" ") != e["romanization"].strip().count(" "):
            diffs += 1
            print(f"{e['korean']}	given={e['romanization']}	spacing differs from the Korean")
            continue
        if expected not in (given, relaxed) and expected.replace("kk", "k") != given:
            diffs += 1
            print(f"{e['korean']}\tgiven={e['romanization']}\trule={romanize(e['korean'])}")
    print(f"{diffs} differences in {len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
