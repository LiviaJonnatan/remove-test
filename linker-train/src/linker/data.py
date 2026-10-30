"""The frozen linking set: cited comment passages, their masked text, and the rule each one answers.

Built by the 11 Oct linking test and versioned under data/linking/. A passage's label is the section of
the proposed rule its author cited; every citation, section number and heading is masked out of the
text a model sees, so the label has to be read from what the passage argues.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# WOTUS has one section in its regulatory text, so it is scored at paragraph level only and is left out
# of section-level training and scoring.
SINGLE_SECTION = {"EPA-HQ-OW-2018-0149": "328.3"}
MASK_TOKENS = re.compile(r"\[(CITATION|NUM|PARA|PART|HEADING)\]")
# Same instruction rule-passages puts in front of a query, so a tuned model drops into serving as is.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
QUERY_MAX_WORDS = 300
WINDOW_WORDS, WINDOW_STEP, WINDOW_SPLIT_ABOVE = 220, 180, 240


def clean(text: str) -> str:
    """Drop the mask tokens and collapse whitespace. What a model reads of a passage."""
    return re.sub(r"\s+", " ", MASK_TOKENS.sub(" ", text)).strip()


def query_text(passage: dict) -> str:
    return QUERY_PREFIX + " ".join(clean(passage["masked"]).split()[:QUERY_MAX_WORDS])


@dataclass
class Window:
    section: str
    chunk_id: str
    text: str


@dataclass
class Rule:
    docket: str
    sections: list[str]
    windows: list[Window]
    headings: dict[str, str] = field(default_factory=dict)

    @property
    def window_section(self) -> list[int]:
        idx = {s: i for i, s in enumerate(self.sections)}
        return [idx[w.section] for w in self.windows]


def windows(rule: dict) -> list[Window]:
    """Rule chunks as the linking test cut them: a chunk over 240 words becomes 220-word windows
    every 180 words, each opened by its heading."""
    out = []
    for c in rule["chunks"]:
        words = c["text"].split()
        if len(words) > WINDOW_SPLIT_ABOVE:
            parts = [" ".join(words[i : i + WINDOW_WORDS]) for i in range(0, len(words), WINDOW_STEP)]
        else:
            parts = [c["text"]]
        for p in parts:
            out.append(Window(c["section"], c["id"], (c["heading"] + ". " + p).strip()))
    return out


def load_rule(root: Path, docket: str) -> Rule:
    raw = json.loads((root / "rules" / f"{docket}.json").read_text())
    if docket in SINGLE_SECTION:
        keep = SINGLE_SECTION[docket]
        raw["chunks"] = [c for c in raw["chunks"] if c["section"] == keep]
    ws = windows(raw)
    sections: list[str] = []
    for w in ws:
        if w.section not in sections:
            sections.append(w.section)
    headings = {s["section"]: s["heading"] for s in raw["sections"]}
    return Rule(docket, sections, ws, headings)


@dataclass
class LinkingSet:
    root: Path
    train: list[dict]
    test: list[dict]
    uncited: list[dict]
    rules: dict[str, Rule]

    @property
    def multi_section_dockets(self) -> list[str]:
        return sorted(d for d, r in self.rules.items() if len(r.sections) > 1)


def load(root: str | Path) -> LinkingSet:
    root = Path(root)
    train = json.loads((root / "train.json").read_text())
    test = json.loads((root / "test.json").read_text())
    uncited = json.loads((root / "uncited.json").read_text())
    dockets = sorted({p["docket"] for p in train + test})
    rules = {d: load_rule(root, d) for d in dockets}
    return LinkingSet(root, train, test, uncited, rules)


def scored(passages: list[dict], rules: dict[str, Rule]) -> list[dict]:
    """Passages that can be scored at section level: a multi-section rule and a label it contains."""
    return [
        p
        for p in passages
        if len(rules[p["docket"]].sections) > 1 and p.get("section") in rules[p["docket"]].sections
    ]


def split_by_comment(passages: list[dict], share: float, seed: int) -> tuple[list[dict], list[dict]]:
    """Hold out whole comments, so no letter is on both sides of a split."""
    import random

    comments = sorted({p["comment"] for p in passages})
    rng = random.Random(seed)
    rng.shuffle(comments)
    held = set(comments[: max(1, round(len(comments) * share))])
    return [p for p in passages if p["comment"] not in held], [p for p in passages if p["comment"] in held]
