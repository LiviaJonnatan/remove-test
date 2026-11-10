"""Read an agency's response-to-comments document into codes and commenter entries.

The LCRI document (EPA 815-R-24-029) files comments under topic codes ("5.9.2 Action Level"). Each
code opens with "EPA Response to Comment Code 5.9.2", a summary answer, and then lists commenter
entries: "Organization (Doc. #1118, SBC-051937)", the commenter's excerpt, and usually
"EPA Response:" with the answer to that entry. Doc #1118 is regulations.gov record <docket>-1118.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOC_LINE = re.compile(r"^\s*(\d{1,2}(?:\.\d+){0,3})\s+(.+?)\s*\.{5,}\s*\d+-\d+\s*$")
CODE_LINE = re.compile(r"^\s*EPA Response to Comment Code\s+(\d{1,2}(?:\.\d+){0,3})\s*$")
ENTRY_LINE = re.compile(r"^(.*?)\s*\(Doc\.\s*#\s*(\d+)(?:\.(\d+))?(?:,\s*SBC-\s*([\d-]*))?\)?\s*$")
OPEN_HEADER = re.compile(r"\(Doc\.(?:\s*#\s*[\d.]*)?,?(?:\s*SBC-\s*[\d-]*)?\s*$")
RESPONSE_START = re.compile(r"^\s*EPA Response:\s*")
RUNNING_HEAD = re.compile(r"^\s*Response to Public Comments on .+\b(?:19|20)\d\d\s*$")
TOPIC_FOOT = re.compile(r"^\s*Topic \d+\..*?(\d+-\d+)\s*$")
PAGE_ONLY = re.compile(r"^\s*(?:[ivxlc]+|\d+-\d+)\s*$")
CODE_REF = re.compile(
    r"comment codes?\s+((?:\d{1,2}(?:\.\d+){1,3})(?:\s*(?:,|and|,\s*and)\s*\d{1,2}(?:\.\d+){1,3})*)",
    re.IGNORECASE,
)
ONE_CODE = re.compile(r"\d{1,2}(?:\.\d+){1,3}")
SECTION_REF = re.compile(
    r"section\s+(\d{1,2}(?:\.\d+){1,3})\s+(?:of|in)\s+this\s+Response to Comments", re.IGNORECASE
)


@dataclass
class Code:
    code: str
    title: str
    page: str | None
    summary: list[str] = field(default_factory=list)


@dataclass
class Entry:
    code: str | None
    organization: str
    doc_number: int
    part: int | None
    sbc: str | None
    page: str | None
    excerpt: list[str] = field(default_factory=list)
    response: list[str] | None = None


def clean(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def toc(lines: list[str]) -> dict[str, str]:
    """Code to title, from the table of contents (titles there are not wrapped mid-line)."""
    titles: dict[str, str] = {}
    for line in lines:
        m = TOC_LINE.match(line)
        if m and m.group(1) not in titles:
            titles[m.group(1)] = " ".join(m.group(2).split())
    return titles


def strip_furniture(lines: list[str]) -> list[tuple[str, str | None]]:
    """Drop running heads, topic footers and page numbers; tag each kept line with its page."""
    kept, page = [], None
    for line in lines:
        line = line.replace("\f", "")
        if RUNNING_HEAD.match(line) or PAGE_ONLY.match(line):
            continue
        m = TOPIC_FOOT.match(line)
        if m:
            page = m.group(1)
            continue
        if kept and OPEN_HEADER.search(kept[-1][0]):
            # "... (Doc. #0777, SBC-" wrapped; the rest of the header starts this line.
            kept[-1] = (kept[-1][0].rstrip() + line.strip(), kept[-1][1])
            continue
        kept.append((line, page))
    return kept


def organization(name: str, previous: str | None) -> str:
    """Rejoin a name the layout wrapped: "... Association (PA-" then "AWWA) (Doc. #0800 ...)"."""
    name = name.strip()
    if previous:
        prev = previous.strip()
        unbalanced = name.count(")") > name.count("(") or prev.count("(") > prev.count(")")
        if prev and (unbalanced or prev.endswith("-")):
            joiner = "" if prev.endswith("-") else " "
            name = prev + joiner + name
    return " ".join(name.split())


def heading(line: str, titles: dict[str, str]) -> bool:
    """A section heading ("5.9.2   Action Level"), which belongs to no entry."""
    m = re.match(r"^\s*(\d{1,2}(?:\.\d+){0,3})\s+(.+?)\s*$", line)
    if not m or m.group(1) not in titles:
        return False
    title = " ".join(m.group(2).split()).casefold()
    expected = titles[m.group(1)].casefold()
    return bool(title) and (expected.startswith(title) or title.startswith(expected))


def parse(text: str) -> tuple[list[Code], list[Entry]]:
    lines = text.split("\n")
    titles = toc(lines)
    rows = strip_furniture(lines)
    start = next((i for i, (line, _) in enumerate(rows) if CODE_LINE.match(line)), len(rows))

    codes: list[Code] = []
    entries: list[Entry] = []
    code: Code | None = None
    entry: Entry | None = None
    for i in range(start, len(rows)):
        line, page = rows[i]
        if heading(line, titles):
            continue
        m = CODE_LINE.match(line)
        if m:
            code = Code(m.group(1), titles.get(m.group(1), ""), page)
            codes.append(code)
            entry = None
            continue
        m = ENTRY_LINE.match(line)
        if m and code is not None:
            previous = rows[i - 1][0] if i > start else None
            name = organization(m.group(1), previous)
            if previous and previous.strip() and name != " ".join(m.group(1).split()):
                # The wrapped first half of the name was read as the end of the text before it.
                if entry is None:
                    target = code.summary
                else:
                    target = entry.response if entry.response is not None else entry.excerpt
                if target and target[-1] == previous:
                    target.pop()
            entry = Entry(
                code.code, name, int(m.group(2)), int(m.group(3)) if m.group(3) else None,
                f"SBC-{m.group(4)}" if m.group(4) else None, page,
            )  # fmt: skip
            entries.append(entry)
            continue
        if entry is None:
            if code is not None:
                code.summary.append(line)
            continue
        if entry.response is None and RESPONSE_START.match(line):
            entry.response = [RESPONSE_START.sub("", line)]
        elif entry.response is not None:
            entry.response.append(line)
        else:
            entry.excerpt.append(line)
    return codes, entries


def references(text: str | None) -> list[str]:
    """Codes a response sends the reader to, in order of first mention."""
    if not text:
        return []
    found = [c for group in CODE_REF.findall(text) for c in ONE_CODE.findall(group)]
    found += SECTION_REF.findall(text)
    return list(dict.fromkeys(found))
