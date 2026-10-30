"""The U-28 baseline: how often BM25, embeddings and the two combined find the rule section a
comment passage cites.

The test set is every passage the passage stage linked to a section of the rule by citation
(`data/derived/passages/<docket>/`). The query is the passage with its citations masked
(`text_masked`), so no retriever can match on the section number, and the answer is the section
it cited. Nothing is trained or tuned on these passages.

A passage is found at k if one of the top k results is in a section it cites (some cite more than
one). Results come from the whole rule, preamble and regulatory text, with procedural sections
left out as in the app. The "regulatory text only" columns drop every result outside the
regulatory text (sections under PART) before taking the top k. Every answer is in the regulatory
text, because the passage stage only resolves § numbers.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from .chunking import Chunk
from .evaluate import in_section
from .retrieve import BM25Retriever, DenseRetriever, FusedRetriever, Hit, Retriever
from .store import PassageStore

KS = (1, 3)


@dataclass(frozen=True)
class CitedPassage:
    passage_id: str
    letter_id: str
    query: str
    gold: tuple[str, ...]


@dataclass(frozen=True)
class Scored:
    """One method's results: the rank of the first hit in a cited section for each passage (None
    if it is not in the top 3), over the whole rule and over the regulatory text only."""

    label: str
    key: str
    whole_rule: list[int | None]
    regulatory: list[int | None]
    seconds: float


def load_cited_passages(passages_dir: Path) -> list[CitedPassage]:
    """Passages with at least one citation resolved to a section of the rule, in file order."""
    gold: dict[str, set[str]] = defaultdict(set)
    for link in pq.read_table(passages_dir / "links.parquet").to_pylist():
        if link["section_ref"]:
            gold[link["passage_id"]].add(link["section_ref"])
    return [
        CitedPassage(
            row["passage_id"],
            row["letter_id"],
            row["text_masked"],
            tuple(sorted(gold[row["passage_id"]])),
        )
        for row in pq.read_table(passages_dir / "passages.parquet").to_pylist()
        if row["passage_id"] in gold
    ]


def first_hit(hits: list[Hit], gold: tuple[str, ...]) -> int | None:
    """Rank of the first result in a cited section, or None if none of them is."""
    for hit in hits:
        if any(in_section(hit, g) for g in gold):
            return hit.rank
    return None


def is_regulatory(hit: Hit) -> bool:
    return hit.chunk.section_ref.startswith("PART ")


class RegulatoryTextOnly:
    """A retriever with every result outside the regulatory text dropped.

    It reads the retriever's whole ranking (`depth` is the number of chunks searched), so the
    regulatory chunks keep the order the retriever gave them, renumbered from 1.
    """

    def __init__(self, retriever: Retriever, depth: int):
        self.retriever = retriever
        self.depth = depth
        self.name = retriever.name

    def search(self, query: str, k: int) -> list[Hit]:
        kept = [h for h in self.retriever.search(query, self.depth) if is_regulatory(h)]
        return [Hit(rank, h.score, h.retriever, h.chunk) for rank, h in enumerate(kept[:k], 1)]


def methods(
    chunks: list[Chunk], store: PassageStore, docket_id: str
) -> list[tuple[str, Retriever, Retriever]]:
    """(label, whole-rule retriever, regulatory-text-only retriever) for each method, searching
    only this docket's rule."""
    bm25 = BM25Retriever(chunks, docket_id=docket_id)
    dense = DenseRetriever(store, docket_id=docket_id)
    depth = len(bm25.chunks)  # every searchable chunk of this docket's rule
    bm25_reg = RegulatoryTextOnly(bm25, depth)
    dense_reg = RegulatoryTextOnly(dense, depth)
    return [
        ("BM25", bm25, bm25_reg),
        ("Embeddings (bge-small)", dense, dense_reg),
        (
            "BM25 + embeddings, rank fusion",
            FusedRetriever([bm25, dense]),
            FusedRetriever([bm25_reg, dense_reg]),
        ),
    ]


def ranks(retriever: Retriever, passages: list[CitedPassage]) -> tuple[list[int | None], float]:
    """First-hit rank within the top 3 for each passage, and the seconds the searches took."""
    retriever.search(passages[0].query, max(KS))  # warm-up, so the timing leaves out start-up
    start = time.perf_counter()
    found = [first_hit(retriever.search(p.query, max(KS)), p.gold) for p in passages]
    return found, time.perf_counter() - start


def score(
    chunks: list[Chunk], store: PassageStore, docket_id: str, passages: list[CitedPassage]
) -> list[Scored]:
    rows = []
    for label, whole, regulatory in methods(chunks, store, docket_id):
        found, seconds = ranks(whole, passages)
        found_regulatory, _ = ranks(regulatory, passages)
        rows.append(Scored(label, whole.name, found, found_regulatory, seconds))
    return rows


def found_at(found: list[int | None], k: int) -> int:
    return sum(r is not None and r <= k for r in found)


def percent(count: int, total: int) -> str:
    return f"{100 * count / total:.1f}%"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def format_report(
    docket_id: str,
    passages_dir: Path,
    passages: list[CitedPassage],
    chunks: list[Chunk],
    rows: list[Scored],
) -> str:
    n = len(passages)
    letters = sorted({p.letter_id for p in passages})
    sections = {g for p in passages for g in p.gold}
    searched = [c for c in chunks if c.docket_id == docket_id and not c.procedural]
    regulatory = [c for c in searched if c.section_ref.startswith("PART ")]
    documents = sorted({c.document_number for c in searched})
    lines = [
        f"# Baseline: finding the cited rule section ({docket_id})",
        "",
        f"Built {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `python src/main.py baseline` "
        "(rule-passages).",
        "",
        f"**Test set.** {n} passages from {len(letters)} letters that cite at least one section of "
        f"the rule ({', '.join(documents)}), {len(sections)} sections in all. The query is the "
        "passage with its citations masked; the answer is the section or sections it cites.",
        "",
        f"- `passages.parquet` sha256 `{sha256(passages_dir / 'passages.parquet')}`",
        f"- `links.parquet` sha256 `{sha256(passages_dir / 'links.parquet')}`",
        "",
        f"**Searched.** {len(searched)} chunks of the rule, procedural sections left out; "
        f"{len(regulatory)} of them are regulatory text.",
        "",
        "**Scoring.** Found at k: one of the top k results is in a cited section. Regulatory text "
        "only: results outside the regulatory text are dropped before taking the top k. Seconds "
        "per 1,000 passages is search time on the machine that built this file, including "
        "embedding the query.",
        "",
        "| Method | Top-1 | Top-3 | Top-1, regulatory text only | Top-3, regulatory text only "
        "| Seconds per 1,000 passages |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = [percent(found_at(row.whole_rule, k), n) for k in KS]
        cells += [percent(found_at(row.regulatory, k), n) for k in KS]
        cells.append(f"{1000 * row.seconds / n:.1f}")
        lines.append(f"| {row.label} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## By letter",
        "",
        "Passages found at top-1 / top-3, whole rule.",
        "",
        "| Letter | Passages | " + " | ".join(row.label for row in rows) + " |",
        "|---|---|" + "---|" * len(rows),
    ]
    for letter in letters:
        mine = [i for i, p in enumerate(passages) if p.letter_id == letter]
        cells = [
            " / ".join(str(found_at([row.whole_rule[i] for i in mine], k)) for k in KS)
            for row in rows
        ]
        lines.append(f"| {letter} | {len(mine)} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def run(data_dir: Path, docket_id: str, chunks: list[Chunk], store: PassageStore) -> str:
    """Score every method on one docket's cited passages, write the report and the per-passage
    ranks to data/derived/baseline/<docket>/, and return the report."""
    passages_dir = data_dir / "derived" / "passages" / docket_id
    passages = load_cited_passages(passages_dir)
    if not passages:
        raise RuntimeError(
            f"[{docket_id}] no passage cites a section of the rule; nothing to score"
        )
    rows = score(chunks, store, docket_id, passages)
    report = format_report(docket_id, passages_dir, passages, chunks, rows)

    out = data_dir / "derived" / "baseline" / docket_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.md").write_text(report, encoding="utf-8")
    with (out / "ranks.jsonl").open("w", encoding="utf-8") as stream:
        for i, p in enumerate(passages):
            line = {"passage_id": p.passage_id, "letter_id": p.letter_id, "gold": list(p.gold)}
            for row in rows:
                line[row.key] = row.whole_rule[i]
                line[f"{row.key}_regulatory"] = row.regulatory[i]
            stream.write(json.dumps(line) + "\n")
    return report
