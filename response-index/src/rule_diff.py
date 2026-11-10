"""What changed in the regulatory text between the proposed and the final rule.

Federal Register text puts the amended regulation after "PART 141--...", one "Sec.  141.84  Title."
heading per section, each paragraph on a line indented four spaces. Between sections sit
amendatory instructions ("0", "8. Revise Sec.  141.84 to read as follows:") and "* * * * *" for
text left as it was; neither is regulation text, so both are dropped.

Paragraphs of a section are aligned in order: identical paragraphs match, and inside a run that
differs a paragraph pairs with its most similar counterpart if they share at least half their
words. The rest are additions or removals. A paragraph the proposal did not print ("* * *") reads
as added, so "added" means new to the printed text, not new to the CFR.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

PART = re.compile(r"^PART 14\d--", re.MULTILINE)
SECTION = re.compile(r"^Sec\.\s+(\d{3}\.\d+)\s{2,}(\S.*)$")  # a reference has one space
PAGE = re.compile(r"^\[\[Page \d+\]\]$")
INSTRUCTION = re.compile(r"^\d+\.\s+(Amend|Revise|Add|Remove|Redesignate)\b")
TAG = re.compile(r"</?(?:html|head|title|body|pre|a)\b[^>]*>")  # not "< 0.015 mg/L"
MARKER = re.compile(r"^((?:\([A-Za-z0-9]+\))+)")
PLACEHOLDER = re.compile(r"^(?:\([A-Za-z0-9]+\)\s*)*\* \* \*$")  # "(a) * * *"
PAIR = 0.5


@dataclass
class Change:
    section: str
    title: str
    op: str  # unchanged, modified, added, removed
    marker: str | None
    proposed: str | None
    final: str | None
    similarity: float
    diff: str | None


def sections(raw: str) -> dict[str, tuple[str, list[str]]]:
    """Section number to (title, paragraphs), from the regulatory text of one document."""
    m = PART.search(raw)
    if not m:
        return {}
    out: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    para: list[str] = []
    skipping = False

    def flush():
        text = " ".join(" ".join(para).split())
        if current is not None and text and not PLACEHOLDER.match(text):
            out[current][1].append(text)
        para.clear()

    for line in TAG.sub("", raw[m.start() :]).split("\n"):
        stripped = line.strip()
        if PAGE.match(stripped) or stripped.startswith("[FR Doc"):
            continue
        s = SECTION.match(stripped)
        if s:
            flush()
            current, skipping = s.group(1), False
            title = s.group(2).strip()
            if current not in out:
                out[current] = (title, [])
            continue
        if stripped == "0" or INSTRUCTION.match(stripped) or PART.match(stripped):
            flush()
            skipping = True  # instructions run until the next section heading
            continue
        if current is None or skipping:
            continue
        if not stripped or stripped.startswith("* * *"):
            flush()
            continue
        if line.startswith("    ") and para:
            flush()
        para.append(stripped)
        if stripped.endswith("* * *"):
            flush()
    flush()
    return out


def marker(paragraph: str | None) -> str | None:
    m = MARKER.match(paragraph or "")
    return m.group(1) if m else None


def word_diff(a: str, b: str) -> str:
    """Final text with deletions as [-old-] and insertions as {+new+}."""
    wa, wb = a.split(), b.split()
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "equal":
            out.extend(wa[i1:i2])
            continue
        if op in ("delete", "replace"):
            out.append("[-" + " ".join(wa[i1:i2]) + "-]")
        if op in ("insert", "replace"):
            out.append("{+" + " ".join(wb[j1:j2]) + "+}")
    return " ".join(out)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def align(section: str, title: str, old: list[str], new: list[str]) -> list[Change]:
    rows: list[Change] = []

    def add(op, a, b, sim):
        diff = word_diff(a, b) if op == "modified" else None
        rows.append(Change(section, title, op, marker(b or a), a, b, round(sim, 4), diff))

    norm = lambda ps: [" ".join(p.split()).casefold() for p in ps]
    matcher = difflib.SequenceMatcher(None, norm(old), norm(new), autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for a, b in zip(old[i1:i2], new[j1:j2], strict=True):
                add("unchanged", a, b, 1.0)
            continue
        olds, news = list(range(i1, i2)), list(range(j1, j2))
        used: set[int] = set()
        paired: dict[int, tuple[int, float]] = {}
        for j in news:
            best = max(
                ((similarity(old[i], new[j]), i) for i in olds if i not in used), default=None
            )
            if best and best[0] >= PAIR:
                used.add(best[1])
                paired[j] = (best[1], best[0])
        # A removed paragraph is listed before whatever comes after its proposed position, so rows
        # keep the order of the text.
        removed = [i for i in olds if i not in used]
        for j in news:
            later = [paired[k][0] for k in news if k >= j and k in paired]
            bound = later[0] if later else len(old)
            while removed and removed[0] < bound:
                add("removed", old[removed.pop(0)], None, 0.0)
            if j in paired:
                i, sim = paired[j]
                add("modified", old[i], new[j], sim)
            else:
                add("added", None, new[j], 0.0)
        for i in removed:
            add("removed", old[i], None, 0.0)
    return rows


def diff(proposed_raw: str, final_raw: str) -> list[Change]:
    old, new = sections(proposed_raw), sections(final_raw)
    rows: list[Change] = []
    for sec in sorted(set(old) | set(new), key=lambda s: tuple(int(x) for x in s.split("."))):
        title = (new.get(sec) or old.get(sec))[0]
        rows += align(sec, title, old.get(sec, ("", []))[1], new.get(sec, ("", []))[1])
    return rows
