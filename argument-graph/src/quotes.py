"""Is a quote really in the passage? Deterministic, so the model's output is checked, not trusted.

The response writer will cite these quotes, so a quote has to be a contiguous span of the passage.
Models reproduce curly quotes, dashes and spacing differently from the PDF text, and OCR'd letters
carry ligatures ("clariﬁcaon"), so both sides are normalised before the substring test. The quote
itself is never altered by this stage: what the model returned is what is stored, and the check only
decides whether to keep it.

`norm()` and `verified()` are ported from the 12 Oct reading pilot (step1_extract.py), with the
ligature table from passage-stage's glyphs.py added.
"""

from __future__ import annotations

import re

# Typographic forms the model may write where the passage had plain ASCII, or the reverse.
_PUNCT = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
        "…": "...",
    }
)
# Ligatures that PDF extraction leaves in place. Same table as passage-stage/src/glyphs.py.
_LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)
_WS = re.compile(r"\s+")
_STRIP = "\"' “”‘’"

MIN_QUOTE_WORDS = 8


def norm(text: str) -> str:
    """Lowercase, one space between words, straight quotes and hyphens, ligatures spelled out."""
    text = text.translate(_PUNCT).translate(_LIGATURES)
    return _WS.sub(" ", text).strip().lower()


def verified(quote: str | None, passage_text: str) -> bool:
    """True when the normalised quote is a substring of the normalised passage."""
    if not quote:
        return False
    q = norm(quote).strip(_STRIP)
    return bool(q) and q in norm(passage_text)


def is_fragment(quote: str | None) -> bool:
    """A quote too thin to carry a point: a heading, a citation list, or fewer than 8 words.

    Every word Title Case catches headings such as "Recommendation For EPA In Exhibit 1". A span
    where fewer than half the words start with a letter is a citation list, a table row or a
    string of numbers.
    """
    if not quote:
        return True
    words = quote.split()
    if len(words) < MIN_QUOTE_WORDS:
        return True
    alpha = [w for w in words if w[:1].isalpha()]
    if len(alpha) < max(3, len(words) // 2):
        return True
    return all(w[:1].isupper() for w in alpha)
