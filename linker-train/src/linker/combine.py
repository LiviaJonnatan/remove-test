"""A trained run's section scores plus the two signals in extras.py, with weights picked on validation.

    score(section) = encoder score + w_pre * best preamble window for the section
                                   + w_cite * [the letter cites the section elsewhere]

Weights are chosen two ways, never on the passages they are scored on:
- on the run's validation passages (held-out training comments). These share text with training, so
  the encoder is surer of them than of test passages, and they undervalue any second signal;
- cross-fitted on the test set: chosen on half the comments, scored on the other half, both ways, as
  the cascade is in report.py. This is the number reported as the combined model's.
Each signal is also scored alone, so the gain of each is separable. The output is a run folder like
any other, with the cross-fitted scores as its test predictions, so report.py and the cascade read it.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

from linker import data as D
from linker.encoder import SectionScorer, max_by_section, rank_of
from linker.extras import load_extras
from linker.metrics import accuracy, by_docket

W_PRE = [round(x, 2) for x in np.arange(0.0, 1.01, 0.1)]
W_CITE = [round(x, 3) for x in np.arange(0.0, 0.101, 0.01)]


def preamble_scores(model, rule: D.Rule, windows: list[dict], Q: np.ndarray) -> np.ndarray:
    """n_passages x n_sections: each section's best preamble window. A section the preamble never
    discusses gets the row's lowest covered score, so a missing discussion is not a penalty."""
    out = np.full((Q.shape[0], len(rule.sections)), np.nan, dtype=np.float32)
    idx = {s: i for i, s in enumerate(rule.sections)}
    keep = [w for w in windows if any(s in idx for s in w["sections"])]
    if not keep:
        return np.zeros_like(out)
    V = model.encode(
        [w["text"] for w in keep], batch_size=64, normalize_embeddings=True, convert_to_numpy=True
    )
    S = Q @ V.T
    for j, w in enumerate(keep):
        for s in w["sections"]:
            if s in idx:
                k = idx[s]
                out[:, k] = np.fmax(out[:, k], S[:, j])
    low = np.nanmin(out, axis=1, keepdims=True)
    return np.where(np.isnan(out), low, out)


def matrices(model, data: D.LinkingSet, pre: dict, cites: dict, passages: list[dict]) -> list[dict]:
    scorer = SectionScorer(model)
    rows: list[dict] = [{} for _ in passages]
    by: dict[str, list[int]] = {}
    for i, p in enumerate(passages):
        by.setdefault(p["docket"], []).append(i)
    for d, idx in by.items():
        rule = data.rules[d]
        ps = [passages[i] for i in idx]
        Q = scorer.query_vectors(ps)
        reg = max_by_section(Q @ scorer.window_vectors(rule).T, rule)
        pm = preamble_scores(model, rule, pre.get(d, []), Q)
        for r, i in enumerate(idx):
            p = passages[i]
            cited = set(cites.get(p["qid"], []))
            rows[i] = {
                "rule": rule,
                "label": rule.sections.index(p["section"]),
                "reg": reg[r],
                "pre": pm[r],
                "cite": np.array([1.0 if s in cited else 0.0 for s in rule.sections], dtype=np.float32),
            }
    return rows


def ranks(rows: list[dict], w_pre: float, w_cite: float) -> list[int]:
    return [rank_of(r["reg"] + w_pre * r["pre"] + w_cite * r["cite"], r["label"]) for r in rows]


def top1(rows, w_pre, w_cite) -> float:
    return float(np.mean([x == 1 for x in ranks(rows, w_pre, w_cite)]))


def pick(rows: list[dict], grid_pre: list[float], grid_cite: list[float]) -> tuple[float, float]:
    """Best validation top-1; ties go to the smaller weights."""
    best = max(itertools.product(grid_pre, grid_cite), key=lambda w: (top1(rows, *w), -w[0], -w[1]))
    return float(best[0]), float(best[1])


def prediction_rows(passages, rows, w_pre, w_cite, split) -> list[dict]:
    out = []
    for p, r in zip(passages, rows, strict=True):
        s = r["reg"] + w_pre * r["pre"] + w_cite * r["cite"]
        order = np.argsort(-s, kind="stable")
        srt = s[order]
        out.append({
            "qid": p["qid"], "docket": p["docket"], "comment": p["comment"], "split": split,
            "label": p["section"], "rank": rank_of(s, r["label"]),
            "top10": [r["rule"].sections[j] for j in order[:10]],
            "margin": round(float(srt[0] - srt[1]), 5), "top_score": round(float(srt[0]), 5),
        })  # fmt: skip
    return out


def crossfit(rows: list[dict], comments: list[str], grid_pre, grid_cite, seed: int = 0) -> dict:
    import random

    names = sorted(set(comments))
    random.Random(seed).shuffle(names)
    half = set(names[: len(names) // 2])
    folds = [
        [i for i, c in enumerate(comments) if c in half],
        [i for i, c in enumerate(comments) if c not in half],
    ]
    out = [0] * len(rows)
    chosen = []
    for fit_idx, score_idx in ((folds[0], folds[1]), (folds[1], folds[0])):
        w = pick([rows[i] for i in fit_idx], grid_pre, grid_cite)
        chosen.append(list(w))
        for i, r in zip(score_idx, ranks([rows[i] for i in score_idx], *w), strict=True):
            out[i] = r
    return {"ranks": out, "weights_per_fold": chosen, "folds": folds}


def val_passages(data: D.LinkingSet, run: Path) -> list[dict]:
    qids = set()
    for line in (run / "predictions.jsonl").read_text().splitlines():
        p = json.loads(line)
        if p["split"] == "val":
            qids.add(p["qid"])
    if not qids:  # a run from before val predictions were saved: rebuild its split from its config
        cfg = json.loads((run / "config.json").read_text())
        pool = D.scored(data.train, data.rules)
        if cfg.get("holdout"):
            pool = [p for p in pool if p["docket"] != cfg["holdout"]]
        return D.split_by_comment(pool, cfg["val_share"], cfg["seed"])[1]
    return [p for p in D.scored(data.train, data.rules) if p["qid"] in qids]


def combine(root: Path, extras: Path, run: Path, out: Path) -> dict:
    from sentence_transformers import SentenceTransformer

    data = D.load(root)
    pre, cites = load_extras(extras)
    cfg = json.loads((run / "config.json").read_text())
    model = SentenceTransformer(str(run / "model"), device="cpu")
    model.max_seq_length = cfg.get("max_seq_length", 384)

    test = D.scored(data.test, data.rules)
    if cfg.get("holdout"):
        test = [p for p in test if p["docket"] == cfg["holdout"]]
    unc = [p for p in D.scored(data.uncited, data.rules) if p["docket"] in {q["docket"] for q in test}]
    val = val_passages(data, run)
    R = {
        name: matrices(model, data, pre, cites, ps)
        for name, ps in (("val", val), ("test", test), ("uncited", unc))
    }

    w_pre, w_cite = pick(R["val"], W_PRE, W_CITE)
    only_pre = pick(R["val"], W_PRE, [0.0])
    only_cite = pick(R["val"], [0.0], W_CITE)
    variants = {"encoder": (0.0, 0.0), "+preamble": only_pre, "+letter": only_cite, "+both": (w_pre, w_cite)}
    comments = [p["comment"] for p in test]
    res = {
        "run": run.name,
        "weights": {"w_pre": w_pre, "w_cite": w_cite, "chosen_on": f"val, n={len(val)}"},
        "val": {k: round(top1(R["val"], *w), 4) for k, w in variants.items()},
        "test": {
            k: {"weights": list(w), **accuracy(ranks(R["test"], *w), comments)} for k, w in variants.items()
        },
    }
    from linker.metrics import paired

    base = ranks(R["test"], 0.0, 0.0)
    res["crossfit"] = {}
    for k, (gp, gc) in {
        "+preamble": (W_PRE, [0.0]),
        "+letter": ([0.0], W_CITE),
        "+both": (W_PRE, W_CITE),
    }.items():
        cf = crossfit(R["test"], comments, gp, gc)
        res["crossfit"][k] = {
            "weights_per_fold": cf["weights_per_fold"],
            **accuracy(cf["ranks"], comments),
            "minus_encoder": paired(cf["ranks"], base, comments),
        }
    # Test predictions: each fold scored with the weights the other fold chose. Uncited: their mean.
    test_rows: list[dict] = [{}] * len(test)
    for fold, w in zip(cf["folds"][::-1], cf["weights_per_fold"], strict=True):
        rows = prediction_rows([test[i] for i in fold], [R["test"][i] for i in fold], *w, "test")
        for i, row in zip(fold, rows, strict=True):
            test_rows[i] = row
    w_mean = np.mean(cf["weights_per_fold"], axis=0)
    res["weights"]["uncited"] = [round(float(x), 3) for x in w_mean]
    preds = (test_rows
             + prediction_rows(unc, R["uncited"], *w_mean, "uncited")
             + prediction_rows(val, R["val"], w_pre, w_cite, "val"))  # fmt: skip
    t = [p for p in preds if p["split"] == "test"]
    metrics = {
        "test": accuracy([p["rank"] for p in t], comments),
        "test_by_docket": by_docket([p["rank"] for p in t], comments, [p["docket"] for p in t]),
        "combine": res,
    }
    u = [p for p in preds if p["split"] == "uncited"]
    if u:
        metrics["uncited"] = accuracy([p["rank"] for p in u], [p["comment"] for p in u])
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(
        json.dumps({**cfg, "combined_from": run.name, **res["weights"]}, indent=1)
    )
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (out / "history.json").write_text("[]")
    with open(out / "predictions.jsonl", "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    return res
