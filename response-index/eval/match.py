"""Can retrieval find where EPA answered a comment? Scored against EPA's own filing.

EPA's response to comments files each commenter excerpt under a topic code and, in 75% of entries,
answers it only by pointing to a code's summary response. The answer to an entry is the summary of
the code it is filed under plus any code its own response points to. This script ranks the 138
codes for a comment and checks the rank of those answer codes.

Two inputs, both from data/derived:

- excerpt: EPA's excerpt of the comment, the passage EPA chose to answer. This is the upper bound,
  since the hard part of reading a letter, finding which passage raises which issue, is done.
- letter: our full text of the commenter's letter. The answer set is every code the letter's
  entries are filed under or pointed to. This is the task the product faces.

Methods: the most frequent codes in the training split (prior), BM25, bge-small embeddings, the
two fused by reciprocal rank, and a logistic regression ranker over those scores and the prior. A
code is split into 150-word windows of its summary; a code's score is its best window, and that
window is the paragraph returned as the answer.

The split is by campaign: a form letter campaign is one group, any other record is its own group,
and 20% of groups (by a hash of the group id) are held out. Only the ranker is fit, on train.

Run from the repo root:
    PYTHONPATH=rule-passages/src uv run --project response-index --group eval \
        python response-index/eval/match.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from rule_passages.bm25 import tokenize
from rule_passages.embedding import QUERY_PREFIX
from scipy import sparse
from sklearn.linear_model import LogisticRegression

DOCKET = "EPA-HQ-OW-2022-0801"
WINDOW, OVERLAP = 150, 30
TEST_SHARE = 5  # one group in five is held out
KS = (1, 5, 10)
RRF_K = 60
# Docket-wide codes (general comments, summary information) that answer no provision. Most letters
# have one, so the letter score is also reported without them.
GENERIC = ("1.1", "1.6", "2.1")


def windows(text: str, size: int = WINDOW, overlap: int = OVERLAP) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    starts = list(range(0, len(words) - overlap, step))
    return [" ".join(words[s : s + size]) for s in starts]


def is_test(group: str) -> bool:
    return int(hashlib.sha1(group.encode()).hexdigest(), 16) % TEST_SHARE == 0


class SparseBM25:
    """The scores of rule_passages.bm25.BM25Index (each distinct query term once), as a matrix."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        toks = [tokenize(d) for d in documents]
        self.vocab = {t: i for i, t in enumerate(sorted({t for d in toks for t in d}))}
        lengths = np.array([len(d) for d in toks], dtype=float)
        avg = lengths.mean() if len(lengths) else 0.0
        rows, cols, vals = [], [], []
        df = Counter()
        for i, d in enumerate(toks):
            norm = 1 - b + b * lengths[i] / avg
            for term, tf in Counter(d).items():
                rows.append(i)
                cols.append(self.vocab[term])
                vals.append(tf * (k1 + 1) / (tf + k1 * norm))
                df[term] += 1
        n = len(documents)
        idf = np.zeros(len(self.vocab))
        for term, j in self.vocab.items():
            idf[j] = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
        self.weights = sparse.csr_matrix((vals, (rows, cols)), shape=(n, len(self.vocab)))
        self.weights = self.weights @ sparse.diags(idf)

    def scores(self, queries: list[str]) -> np.ndarray:
        rows, cols = [], []
        for i, q in enumerate(queries):
            for term in set(tokenize(q)):
                if term in self.vocab:
                    rows.append(i)
                    cols.append(self.vocab[term])
        q = sparse.csr_matrix(
            (np.ones(len(rows)), (rows, cols)), shape=(len(queries), len(self.vocab))
        )
        return np.asarray((q @ self.weights.T).todense())


class Encoder:
    """bge-small through fastembed, with vectors cached on disk by text hash."""

    def __init__(self, cache: Path):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def encode(self, texts: list[str], name: str, query: bool = False) -> np.ndarray:
        inputs = [QUERY_PREFIX + t if query else t for t in texts]
        digest = hashlib.sha1("\0".join(inputs).encode()).hexdigest()[:16]
        path = self.cache / f"{name}-{digest}.npy"
        if path.exists():
            return np.load(path)
        t = time.time()
        vecs = np.array(list(self.model.embed(inputs, batch_size=32)), dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        np.save(path, vecs)
        print(f"  embedded {len(texts)} {name} texts in {time.time() - t:.0f}s", file=sys.stderr)
        return vecs


def best_window(window_scores: np.ndarray, owner: np.ndarray, n_codes: int):
    """Per query, each code's best window score and which window it was."""
    best = np.full((window_scores.shape[0], n_codes), -np.inf, dtype=np.float32)
    arg = np.zeros((window_scores.shape[0], n_codes), dtype=np.int64)
    for c in range(n_codes):
        idx = np.flatnonzero(owner == c)
        sub = window_scores[:, idx]
        k = sub.argmax(axis=1)
        best[:, c] = sub[np.arange(len(sub)), k]
        arg[:, c] = idx[k]
    return best, arg


def ranks_of(scores: np.ndarray) -> np.ndarray:
    """Rank (1 = best) of every code for every query; ties broken by code order."""
    order = np.argsort(-scores, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(len(order))[:, None], order] = np.arange(1, order.shape[1] + 1)
    return ranks


def features(bm25: np.ndarray, dense: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """Per (query, code): scores relative to the query's best, reciprocal ranks, log prior."""

    def rel(s):
        top = s.max(axis=1, keepdims=True)
        spread = s.std(axis=1, keepdims=True) + 1e-9
        return (s - top) / spread

    rb, rd = ranks_of(bm25), ranks_of(dense)
    stack = [rel(bm25), rel(dense), 1 / rb, 1 / rd, np.broadcast_to(prior, bm25.shape)]
    return np.stack(stack, axis=-1).reshape(-1, len(stack))


def metrics(ranks: np.ndarray, gold: list[set[int]]) -> dict:
    """hit@k: any answer code in the top k. recall@k: share of answer codes in the top k."""
    first = np.array([min(ranks[i, sorted(g)]) for i, g in enumerate(gold)])
    out = {f"hit@{k}": round(float((first <= k).mean()), 4) for k in KS}
    out["mrr"] = round(float((1 / first).mean()), 4)
    for k in (10, 20):
        out[f"recall@{k}"] = round(
            float(np.mean([np.mean(ranks[i, sorted(g)] <= k) for i, g in enumerate(gold)])), 4
        )
    out["n"] = len(gold)
    return out


def run(data_dir: Path, cache: Path) -> dict:
    resp = data_dir / "derived" / "responses" / DOCKET
    codes = pd.read_parquet(resp / "codes.parquet")
    entries = pd.read_parquet(resp / "entries.parquet")
    letters = pd.read_parquet(
        data_dir / "derived" / "letters" / DOCKET / "letters.parquet",
        columns=["letter_id", "record_id", "text"],
    )
    assign = pd.read_parquet(data_dir / "derived" / "campaigns" / DOCKET / "assignments.parquet")

    code_index = {c: i for i, c in enumerate(codes["code"])}
    n_codes = len(codes)
    campaign = dict(zip(assign["letter_id"], assign["campaign_id"], strict=True))
    record_letter = dict(zip(letters["record_id"], letters["letter_id"], strict=True))

    def group(record_id: str) -> str:
        c = campaign.get(record_letter.get(record_id))
        return c if isinstance(c, str) else record_id

    def answer(row) -> set[int]:
        found = {row.code, *row.response_refs}
        return {code_index[c] for c in found if c in code_index}

    entries["answer"] = entries.apply(answer, axis=1)
    entries["group"] = entries["record_id"].map(group)
    entries["test"] = entries["group"].map(is_test)

    # Code windows. A window carries its code's title, as a heading would.
    win_text, win_owner = [], []
    for i, row in codes.iterrows():
        for w in windows(row.summary_response or row.title):
            win_text.append(f"{row.title}\n{w}" if row.title else w)
            win_owner.append(i)
    win_owner = np.array(win_owner)

    prior_counts = Counter(c for a in entries.loc[~entries["test"], "answer"] for c in a)
    prior = np.log1p(np.array([prior_counts.get(i, 0) for i in range(n_codes)], dtype=float))

    enc = Encoder(cache)
    bm25 = SparseBM25(win_text)
    win_vecs = enc.encode(win_text, "code-windows")

    # Excerpts: one query per distinct excerpt, answer codes pooled over its entries.
    entries["key"] = entries["excerpt"].str.casefold().str.split().str.join(" ")
    ex = (
        entries[entries["key"].str.split().str.len() >= 5]
        .groupby("key", sort=True)
        .agg(
            excerpt=("excerpt", "first"),
            answer=("answer", lambda s: set().union(*s)),
            filed=("code", lambda s: {code_index[c] for c in s if c in code_index}),
            test=("test", "first"),
            entry_ids=("entry_id", list),
        )
        .reset_index(drop=True)
    )
    ex = ex[ex["answer"].str.len() > 0].reset_index(drop=True)
    q_vecs = enc.encode(ex["excerpt"].tolist(), "excerpts", query=True)
    ex_bm25, _ = best_window(bm25.scores(ex["excerpt"].tolist()), win_owner, n_codes)
    ex_dense, ex_arg = best_window(q_vecs @ win_vecs.T, win_owner, n_codes)

    # Letters: one query per record EPA answered, scored by its best letter window against each
    # code's best window.
    rec = (
        entries.groupby("record_id")
        .agg(answer=("answer", lambda s: set().union(*s)), test=("test", "first"))
        .reset_index()
    )
    rec = rec[rec["record_id"].isin(record_letter) & rec["test"]].reset_index(drop=True)
    text_of = dict(zip(letters["record_id"], letters["text"], strict=True))
    lw_text, lw_owner = [], []
    for i, rid in enumerate(rec["record_id"]):
        for w in windows(text_of[rid] or ""):
            lw_text.append(w)
            lw_owner.append(i)
    lw_owner = np.array(lw_owner)
    lw_vecs = enc.encode(lw_text, "letter-windows", query=True)
    lw_bm25, _ = best_window(bm25.scores(lw_text), win_owner, n_codes)
    lw_dense, _ = best_window(lw_vecs @ win_vecs.T, win_owner, n_codes)

    def per_letter(window_level: np.ndarray) -> np.ndarray:
        out = np.full((len(rec), n_codes), -np.inf, dtype=np.float32)
        np.maximum.at(out, lw_owner, window_level)
        return out

    le_bm25, le_dense = per_letter(lw_bm25), per_letter(lw_dense)

    def fused(*score_sets):
        return sum(1 / (RRF_K + ranks_of(s)) for s in score_sets)

    train = ex["test"].eq(False).to_numpy()
    x_train = features(ex_bm25[train], ex_dense[train], prior)
    y_train = np.zeros((train.sum(), n_codes))
    for i, a in enumerate(ex.loc[train, "answer"]):
        y_train[i, sorted(a)] = 1
    ranker = LogisticRegression(max_iter=2000, C=1.0).fit(x_train, y_train.ravel())

    def ranked(bm, de):
        return ranker.decision_function(features(bm, de, prior)).reshape(bm.shape)

    prior_scores = lambda n: np.broadcast_to(prior, (n, n_codes))
    test = ~train
    ex_test = ex[test]
    gold_ex = ex_test["answer"].tolist()
    gold_filed = ex_test["filed"].tolist()
    gold_le = rec["answer"].tolist()
    generic = {code_index[c] for c in GENERIC if c in code_index}
    specific = [i for i, a in enumerate(gold_le) if a - generic]
    gold_specific = [gold_le[i] - generic for i in specific]

    def without_generic(scores):
        out = np.array(scores, dtype=float)[specific]
        out[:, sorted(generic)] = -np.inf
        return out

    methods = {
        "prior": (prior_scores(test.sum()), prior_scores(len(rec))),
        "bm25": (ex_bm25[test], le_bm25),
        "bge-small": (ex_dense[test], le_dense),
        "bm25 + bge-small (RRF)": (
            fused(ex_bm25[test], ex_dense[test]),
            fused(le_bm25, le_dense),
        ),
        "ranker (logistic regression)": (
            ranked(ex_bm25[test], ex_dense[test]),
            ranked(le_bm25, le_dense),
        ),
    }
    results = {}
    for name, (s_ex, s_le) in methods.items():
        r_ex = ranks_of(np.asarray(s_ex))
        results[name] = {
            "excerpt": metrics(r_ex, gold_ex),
            "excerpt_filed_code_hit@1": round(
                float(np.mean([min(r_ex[i, sorted(g)]) == 1 for i, g in enumerate(gold_filed)])),
                4,
            ),
            "letter": metrics(ranks_of(np.asarray(s_le)), gold_le),
            "letter_specific": metrics(ranks_of(without_generic(s_le)), gold_specific),
        }

    # Unsupervised methods on every excerpt, to show the test split is not unusual.
    all_gold = ex["answer"].tolist()
    results_all = {
        "bm25": metrics(ranks_of(ex_bm25), all_gold),
        "bge-small": metrics(ranks_of(ex_dense), all_gold),
        "bm25 + bge-small (RRF)": metrics(ranks_of(fused(ex_bm25, ex_dense)), all_gold),
    }

    # Predictions for every excerpt from the ranker, with the window it would show as the answer.
    best = ranked(ex_bm25, ex_dense)
    order = np.argsort(-best, axis=1, kind="stable")[:, :20]
    preds = pd.DataFrame(
        {
            "entry_ids": ex["entry_ids"],
            "excerpt": ex["excerpt"],
            "test": ex["test"],
            "answer_codes": [sorted(codes["code"][list(a)]) for a in ex["answer"]],
            "top20_codes": [codes["code"].to_numpy()[o].tolist() for o in order],
            "top20_windows": [[win_text[ex_arg[i, c]] for c in order[i]] for i in range(len(ex))],
        }
    )
    out = resp / "match"
    out.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(out / "predictions.parquet", index=False)

    report = {
        "docket_id": DOCKET,
        "codes": n_codes,
        "code_windows": len(win_text),
        "excerpts": len(ex),
        "excerpts_test": int(test.sum()),
        "groups_test": int(entries.loc[entries["test"], "group"].nunique()),
        "groups": int(entries["group"].nunique()),
        "letters_test": len(rec),
        "letter_windows_test": len(lw_text),
        "median_answer_codes_per_letter": float(np.median([len(a) for a in gold_le])),
        "ranker_coefficients": dict(
            zip(
                ["bm25_rel", "dense_rel", "bm25_rrank", "dense_rrank", "log_prior"],
                [round(float(c), 4) for c in ranker.coef_[0]],
                strict=True,
            )
        ),
        "test_split": results,
        "all_excerpts": results_all,
        "window_words": WINDOW,
        "window_overlap": OVERLAP,
        "encoder": "BAAI/bge-small-en-v1.5 (fastembed)",
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--cache", type=Path, default=Path(".cache/response-match"))
    args = p.parse_args()
    report = run(args.data_dir, args.cache)
    print(json.dumps(report["test_split"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
