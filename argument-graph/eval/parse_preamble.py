"""Labels from the final rule: the preamble's "Summary of Public Comments and the EPA's Response"
blocks, cut into the points the agency summarised. Deterministic, no model.

Input: the GPO text of the final rule as rule-passages collected it,
DATA_DIR/raw/federal_register/<docket>/<document_number>.txt (HTML-in-<pre>, 72-column lines,
paragraphs start with four spaces, headings sit at column 0).

Steps:
  1. Strip the <pre> wrapper, drop `[[Page N]]` lines and footnote fences, keep line offsets.
  2. Headings: an enumerator (I., A., 1., a., i.) at column 0 followed by a capital, no terminal
     period, and the next non-blank line is a four-space paragraph or another heading. Only the
     preamble is scanned (up to "List of Subjects").
  3. Blocks: headings matching "Summary of (Public )?Comments and the EPA's Response(s)", each
     spanning to the next heading of equal or higher level.
  4. Each block gets its parent chain, the sibling `a.` (what was proposed) and `c.` (what was
     finalised) texts, and the `Sec. 14[12].N` citations inside it. Blocks with no citation are
     mapped by hand in block_sections.csv.
  5. Paragraphs (four-space indent) are classified by opener: summary, response, other.
  6. Points: the sentences of a summary paragraph before the first sentence that opens like a
     response (RESPONSE_OPENER, the same pattern that classifies paragraphs: "The EPA <verb>" other
     than received, heard, proposed, requested, also after "In addition," and the like; "In the
     final rule"; "After consideration").
     A sentence that opens like a summary ("The EPA also received comments ...") is never a cut.
     The cut is heuristic; the reader pack checks 40 boundaries.
  7. has_explicit_response: the response sits in the same paragraph (response_where
     `same_paragraph`) or a response paragraph follows within the next two paragraphs with no
     summary paragraph between (`next_paragraph`); otherwise `none`.

The script prints the counts it found; none is typed in here.

Output eval/out/points.parquet (point_id, block, paragraph, section_refs, text,
has_explicit_response, response_where, catch_all), blocks.json and headings.json.

Usage: python eval/parse_preamble.py [--docket EPA-HQ-OW-2022-0801] [--document 2024-23549]
       [--data-dir ../data] [--out eval/out]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

HEADING = re.compile(
    r"^(?P<enum>[IVX]+|[A-Z]|\d{1,2}|[a-z]|i{1,3}|iv|v|vi{0,3})\.\s+(?P<text>[A-Z].*)$"
)
BLOCK_HEADING = re.compile(r"Summary of (Public )?Comments and the EPA'?s Responses?")
PREAMBLE_END = re.compile(r"^List of Subjects")
PAGE = re.compile(r"^\[\[Page \d+\]\]")
RULE = re.compile(r"^-{20,}\s*$")
SECTION_CITE = re.compile(r"Sec\.\s+(14[12]\.\d+)")
SUMMARY_OPENER = re.compile(
    r"^(The EPA (also )?(received|heard)|(Some|Many|Other|Several|A few|Most|Numerous) commenters|"
    r"One (State |Tribal |industry |water system )?commenter|Commenters|Several commenters|"
    r"A commenter)"
)
# One pattern cuts points and classifies paragraphs, so a response sentence that would start a
# response paragraph also ends the points of a mixed paragraph. "The EPA <verb>" is the agency
# speaking (agrees, disagrees, notes, has, also, intends, is retaining, ...) except when the verb
# reports what it received or heard, or what it proposed or requested comment on: those sentences
# are the summary and the background, and SUMMARY_OPENER is checked first anyway.
RESPONSE_OPENER = re.compile(
    r"^((In addition|Additionally|However|Further|Finally|Therefore), )?"
    r"[Tt]he (EPA|agency) (?!(also )?(received|heard|proposed|requested)\b)[a-z]|"
    r"^(In the final (rule|LCRI)|For the final (rule|LCRI)|After consideration)"
)
RESPONSE_LOOKAHEAD = 2  # paragraphs after a summary paragraph that may hold its response
SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z(\"'])")
# Blocks whose points are not about one provision: the economic analysis and the state records
# block. Scored separately.
CATCH_ALL_PARENTS = ("Economic Analysis", "State Recordkeeping", "Recordkeeping Requirements")

LEVELS = {"roman": 0, "upper": 1, "digit": 2, "lower": 3, "roman_lower": 4}


class Leveller:
    """Which outline level an enumerator is. The outline runs I. > A. > 1. > a. > i., and "I", "V",
    "X", "i" and "v" are letters or numerals depending on what came before: "I." after "H." is a
    letter, "i." after "a." is a numeral."""

    ROMAN = re.compile(r"[IVX]+")
    ROMAN_LOWER = re.compile(r"i{1,3}|iv|v|vi{0,3}")

    def __init__(self) -> None:
        self.last_upper: str | None = None
        self.last_lower: str | None = None

    def level(self, enum: str) -> str:
        if enum.isdigit():
            self.last_lower = None
            return "digit"
        if enum.isupper():
            self.last_lower = None
            follows = self.last_upper is not None and enum == chr(ord(self.last_upper) + 1)
            if self.ROMAN.fullmatch(enum) and not follows:
                self.last_upper = None
                return "roman"
            self.last_upper = enum
            return "upper"
        follows = self.last_lower is not None and enum == chr(ord(self.last_lower) + 1)
        if self.ROMAN_LOWER.fullmatch(enum) and not follows:
            return "roman_lower"
        self.last_lower = enum
        return "lower"


@dataclass
class Heading:
    line: int
    enum: str
    text: str
    level: str


@dataclass
class Block:
    block_id: str
    heading_line: int
    start: int  # first line after the heading
    end: int  # exclusive
    parents: list[str]
    proposed_text: str
    final_text: str
    section_refs: list[str]
    section_source: str  # citation or hand_map
    words: int
    paragraphs: int
    catch_all: bool = False
    point_ids: list[str] = field(default_factory=list)


def clean_lines(raw: str) -> list[str]:
    """Lines of the body with page markers and footnote rules blanked, offsets kept."""
    body = raw
    i = body.find("<pre>")
    if i >= 0:
        body = body[i + len("<pre>") :]
    j = body.rfind("</pre>")
    if j >= 0:
        body = body[:j]
    lines = body.split("\n")
    return ["" if PAGE.match(x) or RULE.match(x) else x for x in lines]


def preamble_range(lines: list[str]) -> tuple[int, int]:
    """Line range to scan: after the table of contents (the first heading's second appearance)
    and before "List of Subjects"."""
    end = len(lines)
    for i, x in enumerate(lines):
        if PREAMBLE_END.match(x):
            end = i
            break
    first = next((i for i, x in enumerate(lines[:end]) if HEADING.match(x)), 0)
    start = next(
        (i for i in range(first + 1, end) if lines[i].rstrip() == lines[first].rstrip()), first
    )
    return start, end


def heading_at(lines: list[str], i: int, end: int) -> str | None:
    """The heading text starting at line i, joined with one wrapped continuation line, or None."""
    m = HEADING.match(lines[i])
    if not m:
        return None
    text = lines[i].rstrip()
    j = i + 1
    # A long heading wraps once onto a column-0 line that is neither a paragraph nor a heading.
    if (
        j < end
        and lines[j].strip()
        and not lines[j].startswith(" ")
        and not HEADING.match(lines[j])
        and len(text) >= 60
    ):
        text = f"{text} {lines[j].strip()}"
        j += 1
    if text.endswith("."):
        return None
    while j < end and lines[j].strip() == "":
        j += 1
    nxt = lines[j] if j < end else ""
    if not (nxt.startswith("    ") or HEADING.match(nxt)):
        return None
    return text


def find_headings(lines: list[str]) -> list[Heading]:
    start, end = preamble_range(lines)
    out: list[Heading] = []
    leveller = Leveller()
    for i in range(start, end):
        text = heading_at(lines, i, end)
        if text is None:
            continue
        m = HEADING.match(text)
        if m is None:
            continue
        level = leveller.level(m.group("enum"))
        out.append(Heading(i, m.group("enum"), m.group("text").strip(), level))
    return out


FOOTNOTE = re.compile(r"^\s{4}\\\d+\\")


def paragraphs_of(lines: list[str], start: int, end: int) -> list[str]:
    """Body paragraphs between two line offsets, joined into single lines.

    A paragraph starts with exactly four spaces and continues on column-0 lines. Lines indented
    further are table cells, and a footnote body (four spaces, then the note number between
    backslashes) is dropped."""
    paras: list[list[str]] = []
    open_para = False
    for x in lines[start:end]:
        if x.startswith("    ") and not x.startswith("     "):
            if FOOTNOTE.match(x):
                open_para = False
                continue
            paras.append([x.strip()])
            open_para = True
        elif x.startswith(" ") or not x.strip() or HEADING.match(x):
            open_para = False
        elif open_para:
            paras[-1].append(x.strip())
    return [" ".join(p) for p in paras]


def classify(paragraph: str) -> str:
    if SUMMARY_OPENER.match(paragraph):
        return "summary"
    if RESPONSE_OPENER.match(paragraph):
        return "response"
    return "other"


def is_response_sentence(sentence: str) -> bool:
    return not SUMMARY_OPENER.match(sentence) and bool(RESPONSE_OPENER.match(sentence))


def points_of(paragraph: str) -> tuple[list[str], bool]:
    """The summary sentences before the first response sentence, and whether one followed."""
    sentences = [s.strip() for s in SENTENCE_END.split(paragraph.strip())]
    head, explicit = [], False
    for sentence in sentences:
        if is_response_sentence(sentence):
            explicit = True
            break
        head.append(sentence)
    return [s for s in head if len(s.split()) >= 6], explicit


def response_follows(classes: list[str], i: int) -> bool:
    """A response paragraph within RESPONSE_LOOKAHEAD after paragraph i, no summary between."""
    for cls in classes[i + 1 : i + 1 + RESPONSE_LOOKAHEAD]:
        if cls == "response":
            return True
        if cls == "summary":
            return False
    return False


def cut_blocks(lines: list[str], headings: list[Heading]) -> list[tuple[int, Heading, int]]:
    """(index into headings, heading, end line) for every comment-summary heading."""
    out = []
    for k, h in enumerate(headings):
        if not BLOCK_HEADING.search(h.text):
            continue
        end = len(lines)
        for h2 in headings[k + 1 :]:
            if LEVELS[h2.level] <= LEVELS[h.level]:
                end = h2.line
                break
        out.append((k, h, end))
    return out


def parent_chain(headings: list[Heading], k: int) -> list[str]:
    chain: list[str] = []
    level = LEVELS[headings[k].level]
    for h in reversed(headings[:k]):
        if LEVELS[h.level] < level:
            chain.append(f"{h.enum}. {h.text}")
            level = LEVELS[h.level]
        if level == 0:
            break
    return list(reversed(chain))


def sibling_text(lines: list[str], headings: list[Heading], k: int, enum: str) -> str:
    """Text under the sibling heading with this enumerator (`a` proposed, `c` final)."""
    h = headings[k]
    level = LEVELS[h.level]
    rng = range(k - 1, -1, -1) if enum < h.enum else range(k + 1, len(headings))
    for j in rng:
        if LEVELS[headings[j].level] < level:
            break
        if headings[j].level == h.level and headings[j].enum == enum:
            end = headings[j + 1].line if j + 1 < len(headings) else len(lines)
            return " ".join(paragraphs_of(lines, headings[j].line + 1, end))
    return ""


def hand_map(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {r["block_id"]: r["section_refs"].split(";") for r in csv.DictReader(f)}


def to_ref(number: str) -> str:
    part = number.split(".")[0]
    return f"PART {part}/§ {number}"


def parse(raw: str, hand: dict[str, list[str]]) -> tuple[list[Heading], list[Block], list[dict]]:
    lines = clean_lines(raw)
    headings = find_headings(lines)
    blocks: list[Block] = []
    points: list[dict] = []
    for n, (k, h, end) in enumerate(cut_blocks(lines, headings), start=1):
        bid = f"B{n:02d}"
        paras = paragraphs_of(lines, h.line + 1, end)
        text = " ".join(paras)
        cites = sorted(set(SECTION_CITE.findall(text)), key=lambda s: tuple(map(int, s.split("."))))
        parents = parent_chain(headings, k)
        catch_all = any(any(c in p for c in CATCH_ALL_PARENTS) for p in parents)
        if cites:
            refs, source = [to_ref(c) for c in cites], "citation"
        else:
            refs = [to_ref(c) for c in hand.get(bid, []) if c.strip()]
            source = "hand_map"
        block = Block(
            block_id=bid, heading_line=h.line + 1, start=h.line + 2, end=end + 1, parents=parents,
            proposed_text=sibling_text(lines, headings, k, "a"),
            final_text=sibling_text(lines, headings, k, "c"), section_refs=refs,
            section_source=source, words=len(text.split()), paragraphs=len(paras),
            catch_all=catch_all,
        )  # fmt: skip
        classes = [classify(p) for p in paras]
        for p_i, para in enumerate(paras):
            if classes[p_i] != "summary":
                continue
            sentences, in_paragraph = points_of(para)
            where = (
                "same_paragraph" if in_paragraph
                else "next_paragraph" if response_follows(classes, p_i)
                else "none"
            )  # fmt: skip
            for s_i, sentence in enumerate(sentences):
                pid = f"{bid}-{p_i:02d}-{s_i:02d}"
                block.point_ids.append(pid)
                points.append(
                    {"point_id": pid, "block": bid, "paragraph": p_i, "section_refs": refs,
                     "text": sentence, "has_explicit_response": where != "none",
                     "response_where": where, "catch_all": catch_all}
                )  # fmt: skip
        blocks.append(block)
    return headings, blocks, points


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--document", default="2024-23549")
    ap.add_argument("--data-dir", default=str(HERE.parents[1] / "data"))
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    path = Path(a.data_dir) / "raw" / "federal_register" / a.docket / f"{a.document}.txt"
    raw = path.read_text(encoding="utf-8", errors="replace")
    headings, blocks, points = parse(raw, hand_map(HERE / "block_sections.csv"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "headings.json").write_text(json.dumps([asdict(h) for h in headings], indent=1))
    (out / "blocks.json").write_text(json.dumps([asdict(b) for b in blocks], indent=1))
    import pandas as pd

    pd.DataFrame(points).to_parquet(out / "points.parquet", index=False)
    unmapped = [b.block_id for b in blocks if not b.section_refs]
    where = {k: sum(p["response_where"] == k for p in points)
             for k in ("same_paragraph", "next_paragraph", "none")}  # fmt: skip
    print(
        f"{len(headings)} headings, {len(blocks)} comment blocks, "
        f"{sum(b.paragraphs for b in blocks)} paragraphs, {len(points)} points "
        f"({sum(p['has_explicit_response'] for p in points)} with an explicit response: "
        f"{where}; {sum(p['catch_all'] for p in points)} catch-all); "
        f"blocks without a section: {unmapped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
