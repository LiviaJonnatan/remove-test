"""Two signals the frozen set leaves out, built from files the 11 Oct linking test already downloaded.

1. The preamble. A proposed rule opens with the agency's own discussion, section by section, written in
   the language commenters argue in. Every preamble paragraph under a heading that names a section, or
   that names one itself, becomes a window labelled with that section. Section numbers are masked, as
   in the comments. No human labels: the preamble ships with the rule.
2. The letter's other citations. A letter that cites § A in one place often argues about § A elsewhere.
   For each passage, the sections cited by the other blocks of the same letter. The passage's own
   block is left out, so its masked citation never leaks. At serving time these come from the explicit
   citations in the letter, which the pipeline already extracts.

    python src/main.py extras --src ~/Harvard/ac215/undersigned2/linking/data --out ../data/linking-extra
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from linker.data import WINDOW_SPLIT_ABOVE, WINDOW_STEP, WINDOW_WORDS

SECTION_REF = re.compile(r"(?:§§?|\bSections?)\s*(\d+\.\d+[a-z]?)", re.I)
BARE_NUMBER = re.compile(r"\b\d+\.\d+[a-z]?\b")
CITE_MASK = re.compile(
    r"(?:§§?|\bSections?)\s*\d+\.\d+[a-z]?(?:\s*\([a-z0-9]+\))*|\b\d+\.\d+[a-z]?(?:\([a-z0-9]+\))*", re.I
)
TAG = re.compile(r"<[^>]+>")
MIN_WORDS = 15


def plain(xml: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", xml)).strip()


def mask(text: str) -> str:
    return re.sub(r"\s+", " ", CITE_MASK.sub(" [CITATION] ", text)).strip()


def cut(text: str) -> list[str]:
    words = text.split()
    if len(words) <= WINDOW_SPLIT_ABOVE:
        return [text]
    return [" ".join(words[i : i + WINDOW_WORDS]) for i in range(0, len(words), WINDOW_STEP)]


def preamble_windows(xml: str, sections: set[str]) -> list[dict]:
    """Preamble paragraphs in order. A paragraph takes the sections it names; one that names none takes
    the sections of the last heading that named any."""
    end = xml.find("<SECTNO>")
    pre = xml[:end] if end > 0 else xml
    current: set[str] = set()
    out = []
    for hd, htext, ptext in re.findall(r"<(HD) SOURCE=\"HD\d\">(.*?)</HD>|<P>(.*?)</P>", pre, flags=re.S):
        if hd:
            named = set(SECTION_REF.findall(plain(htext))) | set(BARE_NUMBER.findall(plain(htext)))
            current = named & sections
            continue
        text = plain(ptext)
        if len(text.split()) < MIN_WORDS:
            continue
        named = (set(SECTION_REF.findall(text)) | set(BARE_NUMBER.findall(text))) & sections
        assigned = named or current
        if not assigned:
            continue
        for part in cut(mask(text)):
            out.append({"text": part, "sections": sorted(assigned)})
    return out


def letter_citations(passages: list[dict], blocks: dict[str, list[dict]]) -> dict[str, list[str]]:
    """qid -> sections cited by the letter's other blocks. A passage is matched to its own block(s) by
    text; one that matches no block gets nothing rather than a guess."""
    out = {}
    for p in passages:
        bs = blocks.get(p["comment"], [])
        head = p["raw"].strip()[:60]
        own = [i for i, b in enumerate(bs) if head and head in b["text"]]
        if not own:
            out[p["qid"]] = []
            continue
        out[p["qid"]] = sorted({b["section"] for i, b in enumerate(bs) if i not in own})
    return out


def build(src: Path, root: Path, out: Path) -> dict:
    """src: the 11 Oct linking test's data folder. root: the frozen set. out: where the extras go."""
    from linker.data import load

    data = load(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "preamble").mkdir(exist_ok=True)
    summary: dict = {"preamble": {}, "letter_citations": {}}
    for d, rule in data.rules.items():
        raw = json.loads((root / "rules" / f"{d}.json").read_text())
        (doc,) = {s["doc"] for s in raw["sections"]}
        wins = preamble_windows((src / "rules" / f"{doc}.xml").read_text(), set(rule.sections))
        (out / "preamble" / f"{d}.json").write_text(json.dumps(wins))
        single = sum(len(w["sections"]) == 1 for w in wins)
        covered = len({s for w in wins for s in w["sections"]})
        summary["preamble"][d] = {
            "windows": len(wins),
            "single_section": single,
            "sections_covered": covered,
            "sections": len(rule.sections),
        }

    blocks: dict[str, list[dict]] = defaultdict(list)
    for d in data.rules:
        for line in (src / d / "pairs.jsonl").read_text().splitlines():
            b = json.loads(line)
            blocks[b["comment"]].append({"section": b["section"], "text": b["text"]})
    cites = {}
    for name, ps in (("train", data.train), ("test", data.test), ("uncited", data.uncited)):
        c = letter_citations(ps, blocks)
        cites.update(c)
        summary["letter_citations"][name] = {
            "passages": len(ps),
            "with_other_citations": sum(bool(c[p["qid"]]) for p in ps),
            "label_among_them": sum(p.get("section") in c[p["qid"]] for p in ps),
        }
    (out / "letter_citations.json").write_text(json.dumps(cites))
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def load_extras(path: str | Path | None) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """(docket -> preamble windows, qid -> letter's other cited sections); empty when path is None."""
    if not path or not Path(path).exists():
        return {}, {}
    path = Path(path)
    pre = {f.stem: json.loads(f.read_text()) for f in sorted((path / "preamble").glob("*.json"))}
    return pre, json.loads((path / "letter_citations.json").read_text())
