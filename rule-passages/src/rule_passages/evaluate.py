"""Score retrievers against hand-mapped campaigns.

A label file is JSON Lines, one campaign per line:

    {"campaign_id": "EPA-HQ-OW-2018-0149-4291", "query_file": "letters/4291.txt",
     "gold": ["2019-00791:III/G"]}

The letter is either inline as `query` or in a file named by `query_file`, relative to the label
file. `gold` lists the rule sections the campaign argues about. An entry is
`<document>:<section_ref>` or just `<section_ref>`, and covers that section and everything under
it, so "III/G" accepts a hit in "III/G/1". A query counts as a hit at k if any of the top k chunks
falls in a gold section. A campaign labeled with no section (the letter argues about nothing
specific) has an empty `gold` and is left out of the score.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .retrieve import Hit, Retriever


@dataclass(frozen=True)
class LabeledQuery:
    campaign_id: str
    query: str
    gold: tuple[str, ...]


def load_labels(path: Path) -> list[LabeledQuery]:
    """Labeled campaigns that name at least one gold section, in file order."""
    labels = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row["gold"]:
            continue
        query = (
            row["query"]
            if "query" in row
            else (path.parent / row["query_file"]).read_text(encoding="utf-8")
        )
        labels.append(LabeledQuery(row["campaign_id"], query, tuple(row["gold"])))
    return labels


def in_section(hit: Hit, gold: str) -> bool:
    """True if the hit's chunk is in the gold section or one of its subsections."""
    document, _, ref = gold.rpartition(":") if ":" in gold else ("", "", gold)
    if document and hit.chunk.document_number != document:
        return False
    return hit.chunk.section_ref == ref or hit.chunk.section_ref.startswith(ref + "/")


def top_k_accuracy(
    retriever: Retriever, labels: Sequence[LabeledQuery], ks: Sequence[int] = (1, 3)
) -> dict[int, float]:
    """Share of labeled campaigns with a gold section among the top k results, for each k."""
    deepest = max(ks)
    hits_at = dict.fromkeys(ks, 0)
    for label in labels:
        hits = retriever.search(label.query, deepest)
        for k in ks:
            if any(in_section(h, g) for h in hits[:k] for g in label.gold):
                hits_at[k] += 1
    return {k: hits_at[k] / len(labels) for k in ks}


def format_table(rows: list[tuple[str, dict[int, float]]]) -> str:
    ks = sorted(rows[0][1])
    head = f"{'':32s}" + "".join(f"top-{k:<5d}" for k in ks)
    body = [f"{name:32s}" + "".join(f"{acc[k]:<9.2f}" for k in ks) for name, acc in rows]
    return "\n".join([head, *body])
