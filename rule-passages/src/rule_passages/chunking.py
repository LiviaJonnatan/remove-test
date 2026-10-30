"""Turn Federal Register text into retrieval chunks.

The text arrives as GPO plain text wrapped in HTML: hard-wrapped lines, `[[Page N]]` markers that
can fall in the middle of a sentence, a table of contents that repeats every heading, and
`` quote marks. A chunk is a run of paragraphs from one section, about `max_words` long, that
remembers its heading path and the Federal Register page it starts on. Splitting on sections
keeps a chunk about one topic, and the heading path lets a hand label say "III/G" (wetlands)
instead of naming a page range.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from .collect import RuleDocument

Line = tuple[str, int | None]  # a line of text and the page it is on
Block = tuple[str, bool, int | None]  # joined text, whether it starts indented, its page
Part = tuple[str, str]  # a piece of a chunk and the separator written before it

PAGE_MARKER = re.compile(r"^\[\[Page (\d+)\]\]\s*$")
LINE_BREAK = re.compile(r"<(?:br|/p|/div|/li)\b[^>]*>", re.IGNORECASE)
# A tag starts with a letter right after "<" or "</". Rule text also uses bare "<" and ">" as
# less-than and greater-than ("systems serving <1,000 people", "P90 > 0.010 mg/L"). A pattern that
# took any text between "<" and ">" read those as one tag and deleted everything in between, about a
# fifth of the lead and copper proposal.
TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
# GPO's markup for symbols, kept as the symbol rather than dropped with the tags.
GPO_SYMBOLS = {"<bullet>": "•", "<ls-thn-eq>": "≤", "<gr-thn-eq>": "≥"}
GPO_SYMBOL = re.compile("|".join(re.escape(k) for k in GPO_SYMBOLS), re.IGNORECASE)
# The body starts at the first of these labels; everything before is the cover page.
BODY_START = re.compile(r"^(AGENCY|ACTION|SUMMARY):")
# "SUMMARY: text" and "DATES: text": an all-caps label that opens a preamble section.
PREAMBLE_LABEL = re.compile(r"^([A-Z][A-Z ]{2,}[A-Z]):\s*(.*)$", re.S)
SKIP_LABELS = {"AGENCY", "ACTION"}  # who is proposing and what, not content
DROP_LINE = re.compile(r"^(BILLING CODE|\[FR Doc|-{5,}$|0$)")  # 0 is a GPO bullet glyph
PART = re.compile(r"^PART\s+(\d+)\s*--")  # PART 328--DEFINITION OF WATERS ...
SECTION = re.compile(r"^Sec\.\s+([\d.]+[a-z]?)\s+\S")  # Sec. 328.3 Definitions.
MARKER = re.compile(r"^([IVX]+|[A-Z]|\d{1,2})\.\s+\S")  # II. / G. / 1. before a title
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}
ABBREVIATIONS = {
    "no.", "nos.", "sec.", "secs.", "v.", "vs.", "inc.", "co.", "corp.", "dr.", "mr.", "ms.",
    "fed.", "reg.", "st.", "pub.", "l.", "stat.", "seq.", "al.", "approx.", "dep't.",
}  # fmt: skip
SENTENCE_END = re.compile(r"([.!?][”\"’')\]]*)\s+(?=[A-Z“\"(\[])")
DOTTED_ABBREVIATION = re.compile(r"^\(?(?:[A-Za-z]\.){2,}$")
INITIAL = re.compile(r"^[A-Z]\.$")
MIN_WORDS = 25  # a trailing piece shorter than this joins the previous chunk
# Sections about how to take part, not about what the rule says. Letters quote them ("I submit
# this comment on Docket ID ...") without arguing about them, so retrieval skips them by default.
PREAMBLE_REFS = {"SUMMARY", "DATES", "ADDRESSES", "FOR FURTHER INFORMATION CONTACT"}
PROCEDURAL_HEADING = re.compile(
    r"general information|public hearing|how (can|should|do) i|submit comments|copies of this",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Heading:
    level: int
    ref: str
    title: str


@dataclass(frozen=True)
class Paragraph:
    text: str
    path: tuple[Heading, ...]
    page: int | None


@dataclass(frozen=True)
class Chunk:
    id: str
    docket_id: str
    document_number: str
    doc_title: str
    citation: str
    url: str
    publication_date: str
    index: int
    text: str
    heading: str
    section_ref: str
    page: int | None
    procedural: bool = False

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def embed_text(self) -> str:
        """What gets embedded and searched: the heading path followed by the passage."""
        return f"{self.heading}\n{self.text}" if self.heading else self.text


def is_procedural(path: tuple[Heading, ...]) -> bool:
    """True for sections that tell the reader how to take part rather than what the rule does."""
    return any(h.ref in PREAMBLE_REFS or PROCEDURAL_HEADING.search(h.title) for h in path)


def clean_markup(raw: str) -> str:
    """Strip HTML tags (line breaks become newlines) and turn LaTeX-style quotes into real ones."""
    raw = GPO_SYMBOL.sub(lambda m: GPO_SYMBOLS[m.group(0).lower()], raw)
    text = html.unescape(TAG.sub("", LINE_BREAK.sub("\n", raw)))
    return text.replace("``", "“").replace("''", "”")


def _body_lines(text: str) -> list[Line]:
    """Lines of the document body paired with their page, page markers removed.

    A page marker sits between blank lines even when it interrupts a sentence. If the next
    line is not indented, a paragraph is still running, so the blank lines around the marker
    are dropped and the paragraph stays in one piece.
    """
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if BODY_START.match(line)), 0)
    out: list[Line] = []
    markers = [m for line in lines[:start] if (m := PAGE_MARKER.match(line))]
    page: int | None = int(markers[-1].group(1)) if markers else None
    i = start
    while i < len(lines):
        line = lines[i]
        marker = PAGE_MARKER.match(line)
        if not marker:
            if not DROP_LINE.match(line):
                out.append((line, page))
            i += 1
            continue
        page = int(marker.group(1))
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        continues = j < len(lines) and not lines[j].startswith((" ", "\t"))
        # A heading after a sentence that ended is a new section, not the paragraph running on.
        before = next((t for t, _ in reversed(out) if t.strip()), "")
        if continues and _ends_sentence(before) and _looks_like_heading(lines[j]):
            continues = False
        if continues and out and not out[-1][0].strip():
            out.pop()
        elif not continues and (not out or out[-1][0].strip()):
            out.append(("", page))
        i = j if continues else i + 1
    return _drop_table_of_contents(out)


def _ends_sentence(text: str) -> bool:
    return text.rstrip().rstrip("”\"’')]").endswith((".", "?", "!", ":"))


def _looks_like_heading(line: str) -> bool:
    """The first line of a heading: a PART, Sec. or outline marker, not ending a sentence."""
    text = line.strip()
    if PART.match(text) or SECTION.match(text):
        return True
    return bool(MARKER.match(text)) and text.rstrip("”\"’'")[-1] not in ".:;,"


def _drop_table_of_contents(lines: list[Line]) -> list[Line]:
    """Drop the table of contents, which repeats every heading of the body.

    Some documents title it "Table of Contents" and end it with a blank line. Others start it
    right after "SUPPLEMENTARY INFORMATION:" with no title, and a page marker can split it. There
    the list runs until its first entry appears again as the body's first heading.
    """
    for i, (line, _) in enumerate(lines):
        if line.strip() == "Table of Contents":
            j = i + 1
            while j < len(lines) and not lines[j][0].strip():
                j += 1
            while j < len(lines) and lines[j][0].strip():
                j += 1
            return lines[:i] + lines[j:]
    for i, (line, _) in enumerate(lines):
        if line.startswith("SUPPLEMENTARY INFORMATION:") and not line.split(":", 1)[1].strip():
            first = next((k for k in range(i + 1, len(lines)) if lines[k][0].strip()), None)
            if first is None or not _looks_like_heading(lines[first][0]):
                return lines
            entry = lines[first][0].strip()
            later = range(first + 1, len(lines))
            end = next((k for k in later if lines[k][0].strip() == entry), None)
            # Keep a blank line so the label does not run into the first heading.
            return lines if end is None else lines[: i + 1] + [("", lines[end][1])] + lines[end:]
    return lines


def _blocks(lines: list[Line]) -> list[Block]:
    """Group lines into (text, starts_indented, page). Blank lines and indents start blocks."""
    blocks: list[Block] = []
    cur: list[str] = []
    indented, page = False, None

    def flush() -> None:
        if cur:
            blocks.append((" ".join(" ".join(cur).split()), indented, page))
            cur.clear()

    for line, line_page in lines:
        if not line.strip():
            flush()
            continue
        if line.startswith((" ", "\t")):
            flush()
        if not cur:
            indented, page = line.startswith((" ", "\t")), line_page
        cur.append(line)
    flush()
    return blocks


@dataclass
class _Numbering:
    """Which roman numeral and capital letter came last, to tell roman I from letter I."""

    roman: int = 0
    letter: int = 0


def _roman_value(marker: str) -> int | None:
    if not set(marker) <= set(ROMAN_VALUES):
        return None
    total = 0
    for char, nxt in zip(marker, marker[1:] + " ", strict=True):
        value = ROMAN_VALUES[char]
        total += -value if nxt in ROMAN_VALUES and ROMAN_VALUES[nxt] > value else value
    return total


def _heading(text: str, numbering: _Numbering) -> Heading | None:
    """Classify a short, unindented block as a heading, or None if it reads as a sentence."""
    if m := PART.match(text):
        return Heading(1, f"PART {m.group(1)}", text)
    if m := SECTION.match(text):
        return Heading(2, f"§ {m.group(1)}", text)
    m = MARKER.match(text)
    if not m or text.rstrip("”\"’'")[-1] in ".:;,":
        return None
    marker = m.group(1)
    if marker.isdigit():
        return Heading(3, marker, text)
    # II or IV can only be a numeral. A lone I, V or X is the next numeral or the next letter,
    # whichever the numbering so far expects: "I. Summary" after "H." is a letter.
    as_roman = _roman_value(marker)
    if as_roman is not None and (as_roman == numbering.roman + 1 or len(marker) > 1):
        numbering.roman, numbering.letter = as_roman, 0
        return Heading(1, marker, text)
    if len(marker) == 1:
        numbering.letter = ord(marker) - 64
        return Heading(2, marker, text)
    return None


def parse_paragraphs(raw: str) -> list[Paragraph]:
    """Paragraphs of the document body, each with its heading path and starting page."""
    blocks = _blocks(_body_lines(clean_markup(raw)))
    numbering = _Numbering()
    path: tuple[Heading, ...] = ()
    out: list[Paragraph] = []
    for text, indented, page in blocks:
        short = not indented and len(text) <= 220
        if short and (h := _heading(text, numbering)):
            path = path[: h.level - 1] + (h,)
            continue
        label = None if indented else PREAMBLE_LABEL.match(text)
        if label and label.group(1) not in SKIP_LABELS:
            path = (Heading(1, label.group(1), label.group(1).title()),)
            text = label.group(2)
        elif label:
            continue
        if text.strip():
            out.append(Paragraph(text.strip(), path, page))
    return out


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, but not after abbreviations such as U.S.C. or No."""
    out, start = [], 0
    for m in SENTENCE_END.finditer(text):
        last = text[start : m.end(1)].split()[-1]
        if last.lower() in ABBREVIATIONS or DOTTED_ABBREVIATION.match(last) or INITIAL.match(last):
            continue
        out.append(text[start : m.end(1)].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def _segments(paragraph: Paragraph, max_words: int) -> list[str]:
    """A paragraph whole if it fits, else its sentences, else windows of words."""
    if len(paragraph.text.split()) <= max_words:
        return [paragraph.text]
    out: list[str] = []
    for sentence in split_sentences(paragraph.text):
        words = sentence.split()
        out.extend(" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words))
    return out


def _tail(text: str, overlap_words: int) -> list[str]:
    """The last whole sentences of a chunk, up to overlap_words, to open the next chunk."""
    kept: list[str] = []
    total = 0
    for sentence in reversed(split_sentences(text)):
        total += len(sentence.split())
        if total > overlap_words:
            break
        kept.append(sentence)
    return kept[::-1]


def pack(
    paragraphs: list[Paragraph], max_words: int, overlap_words: int
) -> list[tuple[str, int | None]]:
    """Pack the paragraphs of one section into (text, page) chunks of about max_words.

    A chunk after the first opens with the closing sentences of the one before it, so a passage
    cut at a boundary still appears whole in one of the two. A short remainder is folded into
    the previous chunk rather than left as a stub, so a chunk can run MIN_WORDS over max_words.
    Pieces of one paragraph are joined with spaces and paragraphs with newlines.
    """
    chunks: list[tuple[list[Part], int | None]] = []
    new: list[Part] = []
    new_words = 0
    head: list[Part] = []
    page: int | None = None

    def words(parts: list[Part]) -> int:
        return sum(len(text.split()) for text, _ in parts)

    for paragraph in paragraphs:
        for position, seg in enumerate(_segments(paragraph, max_words)):
            n = len(seg.split())
            if new and words(head) + new_words + n > max_words:
                chunks.append((head + new, page))
                tail = [(sentence, " ") for sentence in _tail(_join(new), overlap_words)]
                head = tail if words(tail) + n <= max_words else []
                new, new_words = [], 0
            if not new:
                page = paragraph.page
            new.append((seg, "\n" if position == 0 else " "))
            new_words += n
    if new:
        if chunks and new_words < MIN_WORDS:
            prev, prev_page = chunks[-1]
            chunks[-1] = (prev + new, prev_page)
        else:
            chunks.append((head + new, page))
    return [(_join(parts), p) for parts, p in chunks]


def _join(parts: list[Part]) -> str:
    return "".join(sep + text for text, sep in parts).lstrip()


def chunk_document(doc: RuleDocument, max_words: int = 200, overlap_words: int = 40) -> list[Chunk]:
    """Chunks of one document in reading order, with ids `<document_number>:<index>`."""
    sections: list[tuple[tuple[Heading, ...], list[Paragraph]]] = []
    for paragraph in parse_paragraphs(doc.raw_text):
        if sections and sections[-1][0] == paragraph.path:
            sections[-1][1].append(paragraph)
        else:
            sections.append((paragraph.path, [paragraph]))
    chunks: list[Chunk] = []
    for path, paragraphs in sections:
        for text, page in pack(paragraphs, max_words, overlap_words):
            index = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{doc.document_number}:{index:04d}",
                    docket_id=doc.docket_id,
                    document_number=doc.document_number,
                    doc_title=doc.title,
                    citation=doc.citation,
                    url=doc.url,
                    publication_date=doc.publication_date,
                    index=index,
                    text=text,
                    heading=" > ".join(h.title for h in path),
                    section_ref="/".join(h.ref for h in path),
                    page=page,
                    procedural=is_procedural(path),
                )
            )
    return chunks
