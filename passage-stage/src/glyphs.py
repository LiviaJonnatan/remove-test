"""Repair letter pairs that PDF text extraction lost.

Word documents set in Calibri join some letter pairs into one glyph: "ti", "ft", "tti" and "tf".
Saved as PDF, those glyphs map to the wrong characters, and pypdf (data-processor) writes U+FFFD
for all of them: "Associa�on", "a�er". In the 40-record lead and copper sample one letter
has 1,336 such words.

The letters file keeps the text as extracted. This stage repairs it before splitting, so the passages,
the citations read from them ("Sec�on 141.84" is a citation) and the text people read are whole.
For each damaged word it tries each pair and keeps the one that makes a word the docket's letters
use elsewhere, "ti" when none does, since it is by far the most common. A letter is repaired only
when most of its damaged words come out as words the letters use (1,273 of 1,336 in that letter):
otherwise the lost glyph is probably something else, a lost apostrophe or another font's "fi", and
"EPA�s" must not become "EPAtis". Checked against an exact
decoding of that letter word by word, 1,333 of the 1,336 come out right. Two misses are words no
other letter spells out ("submitting", "straightforward"); the third is "tie", read as "fte" because
the letters use FTE and never "tie".

Typographic ligatures that did decode ("ﬁ" for fi, "ﬀ" for ff) are spelled out too, so a
search for "definition" finds "deﬁnition". Word's bullets in the Symbol and Wingdings fonts come
out as private-use characters (U+F0B7 and others) that other fonts draw as boxes or bars, so they
become "•". Only the code points seen as bullets or letterhead separators in the docket's 408 PDFs
are mapped: the same range also holds letters and math signs in Symbol (U+F06D is μ, U+F0B3 is ≥),
and "15 μg/L" must not become "15 •g/L".
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Iterable

LOST = "�"
# Most common first: the fallback when no candidate is a known word.
PAIRS = ("ti", "ft", "tti", "tf")
BULLETS = (0xF06C, 0xF073, 0xF09F, 0xF0A1, 0xF0A7, 0xF0B7, 0xF0FB, 0xF0FC)
LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
     "ﬅ": "st", "ﬆ": "st"}
    # Symbol and Wingdings bullets as Word writes them, private use. Only those seen in the docket.
    | {chr(code): "•" for code in BULLETS}
)  # fmt: skip
# A run of letters and lost glyphs. A lost glyph with no letter beside it is left alone: it was
# a bullet or a symbol, not part of a word.
WORD = re.compile(rf"[A-Za-z{LOST}]*[A-Za-z][A-Za-z{LOST}]*|[A-Za-z{LOST}]*{LOST}[A-Za-z]+")
# More lost glyphs than this in one word is not ligature damage; leave it.
MAX_LOST = 3


def spell_out_ligatures(text: str) -> str:
    return text.translate(LIGATURES)


def vocabulary(texts: Iterable[str]) -> Counter[str]:
    """How often each undamaged word appears, lowercased."""
    words: Counter[str] = Counter()
    for text in texts:
        for word in re.findall(rf"[A-Za-z{LOST}]+", spell_out_ligatures(text)):
            if LOST not in word:
                words[word.lower()] += 1
    return words


def best_fill(word: str, known: Counter[str]) -> tuple[str, bool]:
    """The word with its lost glyphs filled, and whether that makes a word the letters use."""
    holes = word.count(LOST)
    if not holes or holes > MAX_LOST:
        return word, False
    pieces = word.split(LOST)

    def fill(choice: tuple[str, ...]) -> str:
        return pieces[0] + "".join(pair + piece for pair, piece in zip(choice, pieces[1:]))

    choices = list(itertools.product(PAIRS, repeat=holes))
    # The best-known word wins; ties go to the most common pairs, which come first in PAIRS.
    best = fill(max(choices, key=lambda c: (known[fill(c).lower()], [-PAIRS.index(p) for p in c])))
    return best, known[best.lower()] > 0


def repair_word(word: str, known: Counter[str]) -> str:
    return best_fill(word, known)[0]


def repair(text: str, known: Counter[str]) -> tuple[str, int]:
    """The text with ligatures spelled out and lost pairs restored, and how many words changed.

    Lost pairs are restored only when most damaged words in the text resolve to known words; when
    they do not, the glyphs were probably not Calibri ligatures and are left as they are.
    """
    text = spell_out_ligatures(text)
    if LOST not in text:
        return text, 0
    damaged = [w for w in WORD.findall(text) if 0 < w.count(LOST) <= MAX_LOST]
    if 2 * sum(best_fill(w, known)[1] for w in damaged) <= len(damaged):
        return text, 0
    changed = 0

    def fix(match: re.Match) -> str:
        nonlocal changed
        word = match.group(0)
        fixed = repair_word(word, known)
        changed += fixed != word
        return fixed

    return WORD.sub(fix, text), changed
