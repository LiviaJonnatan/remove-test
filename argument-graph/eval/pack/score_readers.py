"""Agreement and rates from the two readers' locked sheets. Pre-adjudication numbers only.

For each sheet: exact agreement, Cohen's kappa on the first answer column, the rate of each value
per reader, median seconds per item, and a 95% bootstrap interval on the headline rate (over items,
seed 215). Disagreements are listed for the two readers to settle together.

Usage: python eval/pack/score_readers.py --dir eval/pack/returned [--out <scores.json>]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANSWER = {"claims": "faithful", "issues": "clean", "flagged": "carries", "matches": "match",
          "boundaries": "boundary"}  # fmt: skip
HEADLINE = {"claims": "faithful", "issues": "clean", "flagged": "yes", "matches": "yes",
            "boundaries": "ok"}  # fmt: skip


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(HERE / "returned"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=215)
    a = ap.parse_args()
    d = Path(a.dir)
    rng = np.random.default_rng(a.seed)
    report: dict = {}
    for sheet, col in ANSWER.items():
        pa, pb = d / f"{sheet}_A.csv", d / f"{sheet}_B.csv"
        if not (pa.exists() and pb.exists()):
            continue
        A = pd.read_csv(pa, dtype=str).fillna("")
        B = pd.read_csv(pb, dtype=str).fillna("")
        key = A.columns[0]
        merged = A.merge(B, on=key, suffixes=("_a", "_b"))
        xa = merged[f"{col}_a"].str.strip().str.lower().tolist()
        xb = merged[f"{col}_b"].str.strip().str.lower().tolist()
        agree = [x == y for x, y in zip(xa, xb, strict=True)]
        head = HEADLINE[sheet]
        both = np.array([x == head and y == head for x, y in zip(xa, xb, strict=True)])
        boots = [rng.choice(both, size=len(both), replace=True).mean() for _ in range(1000)]
        secs = pd.to_numeric(pd.concat([merged["seconds_a"], merged["seconds_b"]]), errors="coerce")
        report[sheet] = {
            "items": len(merged),
            "agreement": round(float(np.mean(agree)), 4) if agree else None,
            "kappa": kappa(xa, xb),
            "rates_a": dict(Counter(xa)),
            "rates_b": dict(Counter(xb)),
            f"both_{head}": round(float(both.mean()), 4) if len(both) else None,
            f"both_{head}_ci95": [
                round(float(np.percentile(boots, 2.5)), 4),
                round(float(np.percentile(boots, 97.5)), 4),
            ],  # fmt: skip
            "median_seconds": float(secs.median()) if secs.notna().any() else None,
            "disagreements": merged.loc[[not x for x in agree], key].tolist(),
        }
    out = Path(a.out) if a.out else d / "scores.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
