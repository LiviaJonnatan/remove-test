"""Backtest: can the record predict how EPA answers an ask it has not seen?

For every ask, hide EPA's answer and predict it four ways:

  majority    always "declined", the most common verdict
  knn         vote of the 10 most similar asks from other topics (embeddings, no model)
  llm_blind   Sonnet sees the ask, its topic and who argued it, nothing from the record
  llm_record  the same, plus the 10 most similar asks from other topics with EPA's verdict and
              EPA's own sentence on each

Asks in the same topic are never used as evidence, because they share EPA's summary text. The gap
between llm_blind and llm_record is what the record adds over the model's own judgment.

Labels are scored three ways: moved (adopted or partly), declined, no change (explained or already
in the rule). Each model call is cached in eval/cache/, so a rerun only pays for what is missing.

    uv run python eval/backtest.py --docket EPA-HQ-OW-2022-0801
    uv run python eval/backtest.py --train EPA-HQ-OW-2017-0300 --docket EPA-HQ-OW-2022-0801
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from store import Store  # noqa: E402

CACHE = HERE / "cache"
K = 10
BATCH = 24
CLASSES = ("moved", "declined", "no_change")
COLLAPSE = {
    "adopted": "moved", "partly_adopted": "moved", "declined": "declined",
    "clarified": "no_change", "already_required": "no_change",
}  # fmt: skip

SYSTEM = """You predict how a US federal agency answered public comments on a drinking water \
rule. For each ask, give the probability of each outcome:
  moved      the agency adopted the ask, fully or partly, in the final rule
  declined   the agency kept its approach or refused
  no_change  no rule change: the agency explained, promised guidance, or said the rule already \
does it
Probabilities sum to 1. Judge from the ask itself and any evidence given. Do not use knowledge of \
how this specific rule turned out.
Reply with JSON only: {"p": {"<id>": {"moved": 0.2, "declined": 0.6, "no_change": 0.2}, ...}}"""


def ask_rows(s: Store) -> list[dict]:
    rows = []
    for nid, n in s.nodes.items():
        if n["kind"] != "ask":
            continue
        groups = Counter()
        for other, e in s.adj.get(nid, []):
            if e.get("kind") in ("supports", "opposes") and s.nodes[other]["kind"] == "org":
                groups[(e["kind"], s.nodes[other].get("stakeholder") or "other")] += 1
        rows.append({
            "id": nid, "code": n["code"], "ask": n["label"], "verdict": n["verdict"],
            "label": COLLAPSE[n["verdict"]],
            "topic": s.nodes[f"topic:{n['code']}"]["label"],
            "for": n.get("for", 0), "against": n.get("against", 0),
            "argued_by": ", ".join(f"{g} ({c})" for (k, g), c in groups.most_common(4) if k == "supports"),
            "quote": s.details.get(nid, {}).get("quote"),
        })  # fmt: skip
    return sorted(rows, key=lambda r: r["id"])


def embed(s: Store, texts: list[str]) -> np.ndarray:
    v = np.array(list(s._embedder.embed(texts, batch_size=64)), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def neighbors(test: list[dict], tv: np.ndarray, pool: list[dict], pv: np.ndarray, same_docket: bool):
    """For each test ask, the K most similar pool asks, never from the same topic."""
    sims = tv @ pv.T
    out = []
    for i, r in enumerate(test):
        order = np.argsort(-sims[i])
        picked = []
        for j in order:
            if same_docket and pool[j]["code"] == r["code"]:
                continue
            picked.append((pool[j], float(sims[i, j])))
            if len(picked) == K:
                break
        out.append(picked)
    return out


def knn_probs(nb) -> dict[str, float]:
    w = Counter()
    for r, sim in nb:
        w[r["label"]] += max(sim, 0) ** 2
    tot = sum(w.values()) or 1
    return {c: w[c] / tot for c in CLASSES}


def claude(prompt: str, model: str) -> dict:
    key = hashlib.sha1((SYSTEM + model + prompt).encode()).hexdigest()[:16]
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", SYSTEM,
           "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence"]  # fmt: skip
    for _ in range(3):
        res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
        try:
            out = json.loads(res.stdout)
            m = re.search(r"\{.*\}", out["result"], re.DOTALL)
            parsed = json.loads(m.group(0))["p"]
        except Exception:  # noqa: BLE001
            continue
        rec = {"p": parsed, "usd": out.get("total_cost_usd", 0)}
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(rec))
        return rec
    return {"p": {}, "usd": 0}


def item(r: dict, nb=None) -> dict:
    x = {"id": r["id"], "ask": r["ask"], "topic": r["topic"],
         "comment_excerpts_for": r["for"], "against": r["against"]}  # fmt: skip
    if r["argued_by"]:
        x["argued_by"] = r["argued_by"]
    if nb is not None:
        x["similar_past_asks"] = [
            {"ask": p["ask"], "topic": p["topic"], "outcome": p["label"],
             "agency_said": (p["quote"] or "")[:240]} for p, _ in nb[:K]
        ]  # fmt: skip
    return x


def llm_probs(test, nbs, model, with_record, workers=6) -> tuple[dict, float]:
    batches = [list(range(i, min(i + BATCH, len(test)))) for i in range(0, len(test), BATCH)]

    def run(b):
        items = [item(test[i], nbs[i] if with_record else None) for i in b]
        return claude("Asks:\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in items), model)

    probs, usd = {}, 0.0
    with ThreadPoolExecutor(workers) as ex:
        for rec in ex.map(run, batches):
            usd += rec["usd"]
            for k, v in rec["p"].items():
                try:
                    vals = {c: float(v.get(c, 0)) for c in CLASSES}
                except (AttributeError, TypeError, ValueError):
                    continue
                tot = sum(vals.values()) or 1
                probs[k] = {c: vals[c] / tot for c in CLASSES}
    return probs, usd


def auc(scores: list[float], pos: list[bool]) -> float:
    """Probability a random positive outranks a random negative (ties count half)."""
    order = np.argsort(scores)
    ranks = np.empty(len(scores))
    s = np.array(scores)[order]
    i = 0
    while i < len(s):  # average ranks over ties
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    p = np.array(pos)
    n1, n0 = p.sum(), (~p).sum()
    return float((ranks[p].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


def score(test, probs: dict) -> dict:
    rows = [(r, probs[r["id"]]) for r in test if r["id"] in probs]
    pred = [max(p, key=p.get) for _, p in rows]
    gold = [r["label"] for r, _ in rows]
    acc = float(np.mean([a == b for a, b in zip(pred, gold, strict=True)]))
    per = {}
    for c in CLASSES:
        tp = sum(a == c and b == c for a, b in zip(pred, gold, strict=True))
        fp = sum(a == c and b != c for a, b in zip(pred, gold, strict=True))
        fn = sum(a != c and b == c for a, b in zip(pred, gold, strict=True))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        per[c] = {"precision": round(pr, 3), "recall": round(rc, 3),
                  "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0}  # fmt: skip
    return {
        "n": len(rows), "accuracy": round(acc, 3),
        "macro_f1": round(float(np.mean([per[c]["f1"] for c in CLASSES])), 3),
        "moved_auc": round(auc([p["moved"] for _, p in rows], [r["label"] == "moved" for r, _ in rows]), 3),
        "per_class": per,
    }  # fmt: skip


def bootstrap_gap(test, a: dict, b: dict, n=2000, seed=0) -> tuple[float, float, float]:
    """Accuracy of b minus a, with a 95% interval from resampling topics (asks in a topic move together)."""
    rng = np.random.default_rng(seed)
    ids = [r for r in test if r["id"] in a and r["id"] in b]
    hit = lambda p, r: max(p[r["id"]], key=p[r["id"]].get) == r["label"]  # noqa: E731
    by_code: dict[str, list[tuple[int, int]]] = {}
    for r in ids:
        by_code.setdefault(r["code"], []).append((hit(a, r), hit(b, r)))
    codes = list(by_code)
    gaps = []
    for _ in range(n):
        pick = rng.choice(len(codes), len(codes))
        pairs = [x for k in pick for x in by_code[codes[k]]]
        gaps.append(np.mean([y - x for x, y in pairs]))
    pairs = [x for v in by_code.values() for x in v]
    return (round(float(np.mean([y - x for x, y in pairs])), 3),
            round(float(np.percentile(gaps, 2.5)), 3), round(float(np.percentile(gaps, 97.5)), 3))  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801", help="the rule whose asks are predicted")
    ap.add_argument("--train", help="use only these other dockets (comma-separated) as the record")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--limit", type=int, help="first N asks only, for a quick run")
    a = ap.parse_args()

    test_store = Store(a.docket)
    test = ask_rows(test_store)[: a.limit]
    if a.train:
        pool = []
        for d in a.train.split(","):
            ps = Store(d)
            pool += [{**r, "topic": f"{ps.short}: {r['topic']}"} for r in ask_rows(ps)]
    else:
        pool = ask_rows(test_store)
    tv = embed(test_store, [r["ask"] for r in test])
    pv = tv if not a.train and not a.limit else embed(test_store, [r["ask"] for r in pool])
    nbs = neighbors(test, tv, pool, pv, same_docket=not a.train)

    base = Counter(r["label"] for r in pool).most_common(1)[0][0]
    probs = {
        "majority": {r["id"]: {c: float(c == base) for c in CLASSES} for r in test},
        "knn": {r["id"]: knn_probs(nb) for r, nb in zip(test, nbs, strict=True)},
    }
    usd = {}
    probs["llm_blind"], usd["llm_blind"] = llm_probs(test, nbs, a.model, with_record=False)
    probs["llm_record"], usd["llm_record"] = llm_probs(test, nbs, a.model, with_record=True)

    out = {
        "docket": a.docket, "record": a.train or f"{a.docket} (other topics)", "model": a.model,
        "labels": dict(Counter(r["label"] for r in test)),
        "methods": {m: score(test, p) for m, p in probs.items()},
        "record_minus_blind_accuracy": bootstrap_gap(test, probs["llm_blind"], probs["llm_record"]),
        "record_minus_knn_accuracy": bootstrap_gap(test, probs["knn"], probs["llm_record"]),
        "usd": {k: round(v, 2) for k, v in usd.items()},
    }  # fmt: skip
    name = f"backtest_{a.docket}" + (f"_from_{a.train.replace(',', '+')}" if a.train else "") + ".json"
    (HERE / name).write_text(json.dumps(out, indent=2) + "\n")
    (HERE / name.replace(".json", "_preds.json")).write_text(json.dumps(
        {r["id"]: {"gold": r["label"], **{m: probs[m].get(r["id"]) for m in probs}} for r in test}))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
