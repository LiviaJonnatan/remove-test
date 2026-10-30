"""Accuracy at k with intervals from resampling comments, and paired differences between methods.

Passages from one letter are not independent, so every interval resamples whole comments.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

KS = (1, 3, 5, 10)


def _by_comment(comments: list[str]) -> tuple[list[str], np.ndarray]:
    names = sorted(set(comments))
    idx = {c: i for i, c in enumerate(names)}
    return names, np.array([idx[c] for c in comments])


def _resample_counts(groups: np.ndarray, n_groups: int, draws: int, seed: int) -> np.ndarray:
    """draws x n_passages weights: how many times each passage's comment was drawn."""
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n_groups, size=(draws, n_groups))
    per_group = np.zeros((draws, n_groups))
    for d in range(draws):
        per_group[d] = np.bincount(picks[d], minlength=n_groups)
    return per_group[:, groups]


def accuracy(
    ranks: list[int], comments: list[str], ks=KS, draws: int = 2000, seed: int = 0
) -> dict:
    """Share of passages whose labelled section is ranked k or better, with a 95% interval."""
    r = np.asarray(ranks)
    names, groups = _by_comment(comments)
    w = _resample_counts(groups, len(names), draws, seed)
    out = {"n": int(len(r)), "comments": len(names)}
    for k in ks:
        hit = (r <= k).astype(float)
        boot = (w @ hit) / w.sum(axis=1)
        out[f"acc@{k}"] = [round(float(hit.mean()), 4), *np.round(np.percentile(boot, [2.5, 97.5]), 4)]
    out["mrr"] = round(float((1.0 / r).mean()), 4)
    return out


def paired(
    ranks_a: list[int], ranks_b: list[int], comments: list[str], k: int = 1, draws: int = 2000,
    seed: int = 0,
) -> list[float]:
    """Accuracy at k of A minus B on the same passages, in points, with a 95% interval."""
    a = (np.asarray(ranks_a) <= k).astype(float)
    b = (np.asarray(ranks_b) <= k).astype(float)
    names, groups = _by_comment(comments)
    w = _resample_counts(groups, len(names), draws, seed)
    boot = (w @ (a - b)) / w.sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return [round(100 * float((a - b).mean()), 1), round(100 * float(lo), 1), round(100 * float(hi), 1)]


def by_docket(ranks: list[int], comments: list[str], dockets: list[str], **kw) -> dict:
    groups: dict[str, tuple[list[int], list[str]]] = defaultdict(lambda: ([], []))
    for r, c, d in zip(ranks, comments, dockets, strict=True):
        groups[d][0].append(r)
        groups[d][1].append(c)
    return {d: accuracy(rs, cs, **kw) for d, (rs, cs) in sorted(groups.items())}
