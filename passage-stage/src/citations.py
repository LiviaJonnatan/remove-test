"""Find citations of rule sections in comment text.

The patterns are the ones measured in the linking test: on 80 sampled citations, 6 (7.5%) were not
about a section of the proposal. Four families:

  R1_sign     a section sign:                    § 141.84(b)(2), §§ 141.84 and 141.85
  R1_section  the word section, any case:        Section 141.85, SEC. 141.84, sections 141.84-141.86
  R2_cfr      a CFR reference:                   40 CFR 141.85, 40 C.F.R. § 141.2
  R3_bare     a bare number with a paragraph:    141.84(a), only when 141.84 is a section of the rule

A list after the first number ("Sections 141.84 and 141.85") gives one citation per number. A later
number counts only if it has the same CFR part as the first or is a section of the rule, so
"40 CFR 141.80(c) to 0.010 mg/L" is one citation, not two. A number that follows "-", "–",
"through" or "to" ends a range, and is marked so the caller can fill in the sections between.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUM = r"\d{1,4}[a-z]?\.\d{1,5}[a-z]{0,2}(?:-\d{1,2})?(?![\d%])"
DESIG = r"(?:\s?\((?:[a-z]{1,4}|[A-Z]{1,2}|\d{1,3})\)){0,6}"
PREFIX = (
    r"(?:§\s?§|§|(?i:\bsections?\b|\bsecs?\.)|"
    r"\b\d{1,2}\s?C\.?\s?F\.?\s?R\.?\s?(?:[Pp]arts?\s|§\s?§?|[Ss]ections?\s|[Ss]ec\.\s)?)"
)
SEPARATOR = r"(?:,|;|and|or|through|to|–|-|&|,\s?and|,\s?or)"
CONT = r"(?:\s?" + SEPARATOR + r"\s?(?:§\s?§?\s?)?" + NUM + DESIG + r")*"
CITE = re.compile(r"(?P<prefix>" + PREFIX + r")\s{0,3}(?P<body>" + NUM + DESIG + CONT + r")")
ONE = re.compile(r"(?P<num>" + NUM + r")(?P<des>" + DESIG + r")")
BARE = re.compile(
    r"(?<![\w.$§])(?P<num>" + NUM + r")(?P<des>(?:\s?\((?:[a-z]{1,4}|[A-Z]{1,2}|\d{1,3})\)){1,6})"
)
# What sits between two numbers of a list when the second ends a range.
RANGE_SEPARATOR = re.compile(r"^\s*(?:-|–|through|to)\s*(?:§\s?§?\s?)?$")


@dataclass(frozen=True)
class Citation:
    start: int  # where the citation starts in the text
    end: int  # where it ends, so a caller can mask it
    number: str  # the section number, e.g. "141.84"
    raw: str  # the citation as written, e.g. "§ 141.84(b)(2)"
    family: str  # R1_sign, R1_section, R2_cfr or R3_bare
    range_end: bool = False  # True when this number closes a range opened by the one before it


def part_of(number: str) -> str:
    return number.split(".")[0]


def find_citations(text: str, rule_sections: set[str] | None = None) -> list[Citation]:
    """Every section citation in the text, in order. R3 fires only for sections of the rule."""
    rule_sections = rule_sections or set()
    found: list[Citation] = []
    taken: list[tuple[int, int]] = []
    for m in CITE.finditer(text):
        prefix = m.group("prefix")
        if re.search(r"C\.?\s?F\.?\s?R", prefix):
            family = "R2_cfr"
        elif prefix.startswith("§"):
            family = "R1_sign"
        else:
            family = "R1_section"
        body, body_start = m.group("body"), m.start("body")
        first_part = None
        previous_end = 0
        for k, one in enumerate(ONE.finditer(body)):
            number = one.group("num")
            between = body[previous_end : one.start()]
            previous_end = one.end()
            if k == 0:
                first_part = part_of(number)
            elif part_of(number) != first_part and number not in rule_sections:
                continue  # "to 0.010 mg/L" is a measurement, not a section
            start = m.start() if k == 0 else body_start + one.start()
            end = body_start + one.end()
            found.append(
                Citation(
                    start=start,
                    end=end,
                    number=number,
                    raw=text[start:end].strip(),
                    family=family,
                    range_end=k > 0 and bool(RANGE_SEPARATOR.match(between)),
                )
            )
        taken.append((m.start(), m.end()))
    if rule_sections:
        for m in BARE.finditer(text):
            inside = any(a <= m.start() < b for a, b in taken)
            if m.group("num") in rule_sections and not inside:
                found.append(
                    Citation(m.start(), m.end(), m.group("num"), m.group(0).strip(), "R3_bare")
                )
    return sorted(found, key=lambda c: c.start)


TOKEN = "[citation removed]"


def mask(
    text: str, citations: list[Citation], rule_sections: set[str] | None = None, token: str = TOKEN
) -> str:
    """The text with every given citation replaced by `token`, for scoring without the answer.

    With `rule_sections`, any other bare mention of one of them is replaced too, paragraph letters
    included. Text extracted from PDFs can garble the word before a number ("Sec\ufffdon 141.2"),
    so the citation reader misses it; hiding a little too much costs a scorer nothing, while one
    leaked number hands it the answer.
    """
    for cite in sorted(citations, key=lambda c: c.start, reverse=True):
        text = text[: cite.start] + token + text[cite.end :]
    if rule_sections:
        numbers = "|".join(re.escape(n) for n in sorted(rule_sections, key=len, reverse=True))
        bare = re.compile(r"(?<![\w.$])(?:" + numbers + r")(?:\s?\([a-z0-9]{1,4}\))*(?![\w.]?\d)")
        text = bare.sub(token, text)
    return text
