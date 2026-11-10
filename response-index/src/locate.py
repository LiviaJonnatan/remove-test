"""Find where an agency's excerpt of a comment sits in our text of that comment.

The excerpt and our extraction differ in line breaks, hyphenation, quote marks and footnote markers,
so both are compared with only letters and digits kept. The excerpt is cut into 8-word chunks; the
span runs from the first chunk found to the end of the last, in the original letter's characters.
"""

from __future__ import annotations

import re

CHUNK_WORDS = 8
MAX_CHUNKS = 40
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def normalize(text: str) -> tuple[str, list[int]]:
    """Lowercased letters and digits only, with each kept character's offset in the original."""
    chars, offsets = [], []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            offsets.append(i)
    return "".join(chars), offsets


def chunks(excerpt: str) -> list[str]:
    words = WORD.findall(excerpt)
    if len(words) <= CHUNK_WORDS:
        out = [" ".join(words)] if words else []
    else:
        starts = list(range(0, len(words) - CHUNK_WORDS + 1, CHUNK_WORDS))
        if starts[-1] != len(words) - CHUNK_WORDS:
            starts.append(len(words) - CHUNK_WORDS)  # the last chunk ends where the excerpt ends
        out = [" ".join(words[j : j + CHUNK_WORDS]) for j in starts]
    if len(out) > MAX_CHUNKS:
        step = len(out) / MAX_CHUNKS
        out = [out[int(k * step)] for k in range(MAX_CHUNKS - 1)] + [out[-1]]
    return out


def locate(excerpt: str, letter: str, norm: tuple[str, list[int]] | None = None) -> dict:
    """Share of the excerpt's chunks found in the letter, and the span they cover."""
    text, offsets = norm or normalize(letter)
    parts = [normalize(c)[0] for c in chunks(excerpt)]
    parts = [p for p in parts if len(p) >= 12]
    if not parts or not text:
        return {"chunks": len(parts), "found": 0, "share": 0.0, "start": None, "end": None}
    hits, cursor = [], 0
    for p in parts:
        k = text.find(p, cursor)
        if k < 0:
            k = text.find(p)
        if k >= 0:
            hits.append((k, k + len(p)))
            cursor = k + len(p)
    share = len(hits) / len(parts)
    if not hits:
        return {"chunks": len(parts), "found": 0, "share": 0.0, "start": None, "end": None}
    first = min(h[0] for h in hits)
    last = max(h[1] for h in hits)
    return {
        "chunks": len(parts),
        "found": len(hits),
        "share": round(share, 4),
        "start": offsets[first],
        "end": offsets[last - 1] + 1,
    }
