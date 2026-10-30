"""The methods the 11 Oct linking test already scored, on the same frozen test passages.

Ranks are recomputed from each method's saved top-10 against each passage's own label, so the one
passage drawn twice with two labels is scored once per label, as in the adaptation follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path

MISS = 99  # outside the saved list

# Names in rankings.json, and what the README and the 11 Oct report call them.
SAVED = {
    "bm25": "BM25",
    "bge": "bge-small, untuned",
    "hybrid": "Hybrid (BM25 + bge-small, RRF)",
    "sup_lodo_generic_gbm": "Feature reranker A (held-out docket)",
    "sup_lodo_knn_gbm": "Feature reranker B (held-out docket + its own labels)",
    "sup_in_knn_gbm": "Feature reranker C (held-out comments)",
}
LLM = {"sonnet": "frontier_raw.jsonl", "haiku": "haiku_raw.jsonl"}


def rank_in(top: list[str], label: str) -> int:
    return top.index(label) + 1 if label in top else MISS


def saved_ranks(root: str | Path, passages: list[dict]) -> dict[str, list[int | None]]:
    """method -> one rank per passage (None where that method has no answer)."""
    base = Path(root) / "baselines"
    rankings = json.loads((base / "rankings.json").read_text())
    out: dict[str, list[int | None]] = {m: [] for m in SAVED}
    for p in passages:
        r = rankings.get(p["qid"], {}).get("sec_top10", {})
        for m in SAVED:
            out[m].append(rank_in(r[m], p["section"]) if m in r else None)
    for m, fname in LLM.items():
        answers: dict[str, dict] = {}
        for line in (base / fname).read_text().splitlines():
            a = json.loads(line)
            if a.get("sections"):
                answers[a["qid"]] = a  # a retry overwrites the failed call
        out[m] = [
            rank_in(answers[p["qid"]]["sections"], p["section"]) if p["qid"] in answers else None
            for p in passages
        ]
        out[f"{m}_cost"] = [answers[p["qid"]]["cost"] if p["qid"] in answers else None for p in passages]
    return out
