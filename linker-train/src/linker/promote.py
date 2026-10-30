"""The gate between a training run and what the API serves.

A run is promoted only when, on the frozen test set,
1. it beats hybrid search: the lower end of the paired top-1 difference is above zero, and
2. it is at least as good as the model now served (top-1 point estimates; the served model's
   linker.json carries its own).
The decision and its numbers are written either way, so a rejected run says why.
"""

from __future__ import annotations

import json
from pathlib import Path

from linker import data as D
from linker.compare import saved_ranks
from linker.metrics import paired


def no_worse(acc: float, served_acc: float | None) -> bool:
    """linker.json stores top-1 to three decimals, so compare at that precision: 318/490 is 0.64898
    and the same model served reads 0.649."""
    return served_acc is None or round(acc, 3) >= round(served_acc, 3)


def decide(root: Path, run: Path, served: Path | None) -> dict:
    data = D.load(root)
    test = D.scored(data.test, data.rules)
    preds = {}
    for line in (run / "predictions.jsonl").read_text().splitlines():
        p = json.loads(line)
        if p["split"] == "test":
            preds[(p["qid"], p["label"])] = p["rank"]
    ranks = [preds[(p["qid"], p["section"])] for p in test]
    comments = [p["comment"] for p in test]
    hybrid = saved_ranks(root, test)["hybrid"]
    vs_hybrid = paired(ranks, hybrid, comments)
    acc = sum(r == 1 for r in ranks) / len(ranks)

    served_acc = None
    if served is not None and (served / "linker.json").exists():
        served_acc = json.loads((served / "linker.json").read_text())["test_acc@1"][0]
    checks = {
        "beats_hybrid": vs_hybrid[1] > 0,
        "not_worse_than_served": no_worse(acc, served_acc),
    }
    return {
        "run": run.name,
        "test_acc@1": round(acc, 4),
        "minus_hybrid_points": vs_hybrid,
        "served_acc@1": served_acc,
        "checks": checks,
        "promote": all(checks.values()),
    }
