"""passage-stage: split each distinct letter into passages and read the rule sections it cites.

For each docket in DOCKET_IDS it reads the processor's letters and the grouper's assignments, reads
each campaign's shared text once (see distinct_letters), splits each letter into passages, and finds
citations of the proposed rule's sections. Section numbers are resolved to rule-passages'
`section_ref`, so the API, the rule page and the baseline table use one key.

Writes to DATA_DIR/derived/passages/<docket>/:
  passages.parquet   one row per passage: passage_id, letter_id, docket_id, index, text,
                     text_masked (every citation replaced, for scoring without the answer),
                     n_words, n_citations
  links.parquet      one row per (passage, cited section): passage_id, letter_id, docket_id,
                     section_ref (null when the cited number is not a section of the rule),
                     citation_raw, source ("citation"). A range such as "§ 141.80-141.93" also
                     links every section of the rule between its two ends.
  summary.json       counts, words repaired (glyphs.py), and the sha256 of the letters file read

Needs rule-passages to have collected the rule text under DATA_DIR/raw/federal_register/. A rule with
no numbered sections (some preambles-only documents) still gets passages, with every link unresolved.

Environment:
  DOCKET_IDS   comma-separated, default EPA-HQ-OW-2018-0149
  DATA_DIR     default /app/data
  RULE_DOCUMENTS, RULE_DOC_TYPES   as for rule-passages, so both pick the same document. The stage
               reads the rule of each docket in DOCKET_IDS, even when RULE_DOCKETS is set.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from citations import Citation, find_citations, mask, part_of
from glyphs import repair, vocabulary
from passages import MAX_WORDS, MIN_WORDS, TARGET_WORDS, sentences, split_passages

SECTION_NUMBER = re.compile(r"§\s*(\d{1,4}[a-z]?\.\d{1,5}[a-z]{0,2})$")
# CFR parts run from 1 up. A letter's own outline ("see section 2.4 above") uses the same shape with a
# small first number, so an unresolved "section N.N" with N below this is read as the letter's own
# numbering and dropped. Only the word "section" is filtered: a section sign or "CFR" always means
# the CFR, so "§ 60.5740(a)" is kept.
LOWEST_CFR_PART_KEPT = 100


def is_own_numbering(number: str, family: str) -> bool:
    """True for "section 2.4" style references to the letter's own outline, not to the CFR."""
    part = int(re.match(r"\d+", number).group(0))
    return family == "R1_section" and part < LOWEST_CFR_PART_KEPT


def range_between(previous: Citation, end: Citation, ordered: list[str]) -> list[str]:
    """The rule's section numbers strictly between the two ends of a range, in reading order.

    "§ 141.80-141.93" gives 141.81 to 141.92 as far as the rule has them. Both ends must be sections
    of the rule in the same part, and the range must run forward; otherwise nothing is filled in.
    """
    if not end.range_end or part_of(previous.number) != part_of(end.number):
        return []
    if previous.number not in ordered or end.number not in ordered:
        return []
    i, j = ordered.index(previous.number), ordered.index(end.number)
    return ordered[i + 1 : j] if i < j else []


def section_refs_by_number(section_refs: list[str]) -> dict[str, str]:
    """Section number -> section_ref, for the refs that name one regulatory section.

    "PART 141/§ 141.84" gives "141.84" -> "PART 141/§ 141.84". Preamble refs such as "V/E" have no
    section number and are left out: commenters cite the regulatory text far more often.
    """
    out: dict[str, str] = {}
    for ref in section_refs:
        m = SECTION_NUMBER.search(ref.split("/")[-1].strip())
        if m:
            out.setdefault(m.group(1), ref)
    return out


def rule_section_refs(docket: str, data_dir: Path) -> tuple[list[str], list[str]]:
    """The section_refs of the document this docket's comments answered, as rule-passages chunks it.

    Returns (section_refs in reading order, document numbers used).
    """
    from rule_passages.chunking import chunk_document
    from rule_passages.collect import load_documents
    from rule_passages.config import Settings

    settings = Settings.from_env()
    rule_dir = data_dir / "raw" / "federal_register"
    refs: list[str] = []
    used: list[str] = []
    for doc in load_documents(docket, rule_dir):
        if settings.wanted(docket, doc.document_number, doc.doc_type):
            used.append(doc.document_number)
            for chunk in chunk_document(doc, settings.max_words, settings.overlap_words):
                if chunk.section_ref not in refs:
                    refs.append(chunk.section_ref)
    return refs, used


def distinct_letters(letters: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    """The letters to read, with each campaign's shared text read once.

    An ungrouped letter is read whole, and so is the letter a group is named after. Every other
    member, in letter_id order, is read only for the sentences not already read in its group: its
    sender's own words. An exact copy has none and is skipped. Under containment grouping the
    members are personalized, and their added sentences are what this keeps.

    This ties the stage to the grouper: a wrong group changes which sentences get read, not only how
    letters are counted. Containment admits a member only if it holds at least half of the group's
    template, which bounds what a wrong group can drop.
    """
    group = dict(zip(assignments["letter_id"], assignments["campaign_id"], strict=True))
    seen: dict[str, set[str]] = {}  # campaign -> sentences already read in it
    texts = dict(zip(letters["letter_id"], letters["text"], strict=True))
    for name in sorted({c for c in group.values() if pd.notna(c)}):
        seen[name] = {sentence_key(s) for s in sentences(texts.get(name) or "")}
    keep, kept_text = [], []
    for letter_id, text in sorted(texts.items()):
        campaign = group.get(letter_id)
        if pd.isna(campaign) or campaign == letter_id:
            keep.append(letter_id)
            kept_text.append(text)
            continue
        own = []
        for sentence in sentences(text or ""):
            key = sentence_key(sentence)
            if key and key not in seen[campaign]:
                seen[campaign].add(key)
                own.append(sentence)
        if own:
            keep.append(letter_id)
            kept_text.append(" ".join(own))
    order = {letter_id: k for k, letter_id in enumerate(keep)}
    kept = letters[letters["letter_id"].isin(order)].copy()
    kept["text"] = kept["letter_id"].map(dict(zip(keep, kept_text, strict=True)))
    return kept


def sentence_key(sentence: str) -> str:
    """A sentence's words, lowercased, so spacing and punctuation do not make it new."""
    return " ".join(re.findall(r"\w+", sentence.lower()))


PASSAGE_COLUMNS = [
    "passage_id", "letter_id", "docket_id", "index", "text", "text_masked", "n_words", "n_citations",
]  # fmt: skip


def passage_links(
    passage: str,
    passage_id: str,
    letter_id: str,
    docket: str,
    cites: list[Citation],
    by_number: dict[str, str],
) -> list[dict]:
    """One link per section a passage cites, ranges filled in, each section once."""
    ordered = list(by_number)  # reading order, as rule-passages chunks the rule
    rows: list[dict] = []
    seen: set[tuple[str | None, str]] = set()

    def add(ref: str | None, number: str, raw: str) -> None:
        key = (ref, number if ref is None else "")
        if key in seen:  # the same section cited twice in one passage is one link
            return
        seen.add(key)
        rows.append(
            {
                "passage_id": passage_id,
                "letter_id": letter_id,
                "docket_id": docket,
                "section_ref": ref,
                "citation_raw": raw,
                "source": "citation",
            }
        )

    for k, cite in enumerate(cites):
        if k > 0:
            span = passage[cites[k - 1].start : cite.end]
            for number in range_between(cites[k - 1], cite, ordered):
                add(by_number[number], number, span)
        add(by_number.get(cite.number), cite.number, cite.raw)
    return rows


def build(
    letters: pd.DataFrame, docket: str, by_number: dict[str, str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Passages and citation links for the given letters."""
    passage_rows: list[dict] = []
    link_rows: list[dict] = []
    rule_numbers = set(by_number)
    for letter_id, text in zip(letters["letter_id"], letters["text"], strict=True):
        for index, passage in enumerate(split_passages(text if isinstance(text, str) else "")):
            passage_id = f"{letter_id}:p{index:03d}"
            cites = [
                c
                for c in find_citations(passage, rule_numbers)
                if c.number in rule_numbers or not is_own_numbering(c.number, c.family)
            ]
            passage_rows.append(
                {
                    "passage_id": passage_id,
                    "letter_id": letter_id,
                    "docket_id": docket,
                    "index": index,
                    "text": passage,
                    "text_masked": mask(passage, cites, rule_numbers),
                    "n_words": len(passage.split()),
                    "n_citations": len(cites),
                }
            )
            link_rows += passage_links(passage, passage_id, letter_id, docket, cites, by_number)
    passages = pd.DataFrame(
        passage_rows,
        columns=PASSAGE_COLUMNS,
    )
    links = pd.DataFrame(
        link_rows,
        columns=["passage_id", "letter_id", "docket_id", "section_ref", "citation_raw", "source"],
    ).astype({"section_ref": "string"})
    return passages, links


def build_docket(docket: str, data_dir: Path, section_refs: list[str] | None = None) -> bool:
    """Write passages, links and summary for one docket. False if an input is missing."""
    letters_path = data_dir / "derived" / "letters" / docket / "letters.parquet"
    groups_path = data_dir / "derived" / "campaigns" / docket / "assignments.parquet"
    for path, stage in ((letters_path, "data-processor"), (groups_path, "campaign-builder")):
        if not path.exists():
            print(f"[{docket}] no {path.name} at {path}; run {stage} first", file=sys.stderr)
            return False
    letters = pd.read_parquet(letters_path)
    if letters.empty:
        print(f"[{docket}] {letters_path} is empty; see the processor's report", file=sys.stderr)
        return False
    documents: list[str] = []
    if section_refs is None:
        section_refs, documents = rule_section_refs(docket, data_dir)
    if not section_refs:
        print(
            f"[{docket}] no rule text under {data_dir / 'raw' / 'federal_register'}; "
            "run rule-passages first",
            file=sys.stderr,
        )
        return False
    by_number = section_refs_by_number(section_refs)
    if not by_number:
        # Missing rule text and a rule without numbered sections are different cases. The second
        # still gets passages, so the stages after this one run.
        print(
            f"[{docket}] the rule has no numbered sections; passages are written with no links "
            "to it",
            file=sys.stderr,
        )

    groups = pd.read_parquet(groups_path)
    campaign_of = dict(zip(groups["letter_id"], groups["campaign_id"], strict=True))
    distinct = distinct_letters(letters, groups)
    # Restore letter pairs PDF extraction lost ("Sec\ufffdon"), judged by the words this
    # docket's letters use. See glyphs.py.
    known = vocabulary(t for t in letters["text"] if isinstance(t, str))
    repaired = [repair(t, known) if isinstance(t, str) else (t, 0) for t in distinct["text"]]
    distinct = distinct.assign(text=[t for t, _ in repaired])
    passages, links = build(distinct, docket, by_number)
    out = data_dir / "derived" / "passages" / docket
    out.mkdir(parents=True, exist_ok=True)
    passages.to_parquet(out / "passages.parquet", index=False)
    links.to_parquet(out / "links.parquet", index=False)

    resolved = links["section_ref"].notna()
    summary = {
        "docket_id": docket,
        "letters_read": len(letters),
        "letters_skipped_as_copies": int(len(letters) - len(distinct)),
        "words_repaired": sum(n for _, n in repaired),
        "letters_repaired": sum(n > 0 for _, n in repaired),
        "letters_read_for_own_sentences": int(
            (
                distinct["letter_id"].map(campaign_of).notna()
                & (distinct["letter_id"].map(campaign_of) != distinct["letter_id"])
            ).sum()
        ),
        "passages": len(passages),
        "passages_with_citation": int((passages["n_citations"] > 0).sum()),
        "links": len(links),
        "links_resolved": int(resolved.sum()),
        "links_unresolved": int((~resolved).sum()),
        "sections_cited": int(links.loc[resolved, "section_ref"].nunique()),
        "rule_sections_known": len(by_number),
        "rule_documents": documents,
        "passage_words": {"target": TARGET_WORDS, "max": MAX_WORDS, "min": MIN_WORDS},
        "letters_file": str(letters_path.relative_to(data_dir)),
        "letters_sha256": hashlib.sha256(letters_path.read_bytes()).hexdigest(),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[{docket}] {summary['letters_read'] - summary['letters_skipped_as_copies']} letters, "
        f"{summary['passages']} passages, {summary['passages_with_citation']} cite the rule's "
        f"sections or other CFR text, {summary['links_resolved']} links to "
        f"{summary['sections_cited']} sections of the rule, "
        f"{summary['links_unresolved']} to numbers outside it"
    )
    return True


def main() -> int:
    load_dotenv()
    dockets = [
        d.strip() for d in os.getenv("DOCKET_IDS", "EPA-HQ-OW-2018-0149").split(",") if d.strip()
    ]
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    done = [build_docket(docket, data_dir) for docket in dockets]
    return 0 if all(done) else 1


if __name__ == "__main__":
    sys.exit(main())
