"""Pair judge: which claims in a section would the agency answer in one paragraph?

Embeddings propose, the model decides. Every claim's `ask` (or its quote when there is no ask) is
embedded with bge-small, the encoder the rest of the project serves. Within a section, pairs with
cosine at or above GRAPH_PAIR_MIN, at most GRAPH_PAIR_K neighbours per claim, deduplicated by sorted
pair (the 12 Oct collide filter), go to the judge in chunks of GRAPH_PAIRS_PER_CALL. Tags are
judge_<section>_<chunk>.

Verdicts: same_ask and same_issue_opposite_side become edges for issues.py; different and unsure
do not. A pair the model left out of its answer after one re-ask defaults to different and is
logged `missing_from_output`; an `unsure` pair is logged `judge_unsure`.

The baseline this has to beat (eval/baselines.py B1) is cosine clustering over the same embeddings
with no model call.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import Config, Embed, short_ref
from llm import LLM, BudgetExceeded, CallFailed
from templates import prompt, render, schema, split_static

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
PAIR_COLUMNS = ["pair_id", "claim_a", "claim_b", "section_ref", "cosine", "verdict", "tag"]
EDGE_VERDICTS = {"same_ask", "same_issue_opposite_side"}


def embedder(cfg: Config) -> Embed:
    """Tests inject cfg.embed; otherwise bge-small through fastembed (ONNX, CPU)."""
    if cfg.embed is not None:
        return cfg.embed
    from fastembed import TextEmbedding

    model = TextEmbedding(EMBED_MODEL)

    def embed(texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in model.embed(texts, batch_size=32)]

    return embed


def claim_text(row) -> str:
    return row.ask if isinstance(row.ask, str) and row.ask.strip() else (row.quote or "")


def embed_claims(claims: pd.DataFrame, embed: Embed) -> np.ndarray:
    """One unit-length row per claim, in claims' row order."""
    if claims.empty:
        return np.zeros((0, 1), dtype=np.float32)
    vecs = np.asarray(embed([claim_text(r) for r in claims.itertuples()]), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    return vecs


def candidates(claims: pd.DataFrame, vecs: np.ndarray, cfg: Config) -> pd.DataFrame:
    """Candidate pairs within each section: cosine >= pair_min, k neighbours per claim, deduped."""
    rows: list[dict] = []
    ids = claims["claim_id"].to_numpy()
    for ref, idx in claims.groupby("section_ref").indices.items():
        if len(idx) < 2:
            continue
        sub = vecs[idx]
        cos = sub @ sub.T
        np.fill_diagonal(cos, -1.0)
        seen: set[tuple[str, str]] = set()
        for i in range(len(idx)):
            order = np.argsort(-cos[i], kind="stable")[: cfg.pair_k]
            for j in order:
                if cos[i, j] < cfg.pair_min:
                    break
                a, b = sorted((ids[idx[i]], ids[idx[j]]))
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                rows.append(
                    {"claim_a": a, "claim_b": b, "section_ref": ref, "cosine": float(cos[i, j])}
                )
    out = pd.DataFrame(rows, columns=["claim_a", "claim_b", "section_ref", "cosine"])
    out = out.sort_values(["section_ref", "cosine", "claim_a"], ascending=[True, False, True])
    if cfg.max_pairs is not None:
        out = out.sort_values("cosine", ascending=False).head(cfg.max_pairs)
        out = out.sort_values(["section_ref", "cosine", "claim_a"], ascending=[True, False, True])
    out = out.reset_index(drop=True)
    out.insert(0, "pair_id", [f"P{i + 1:06d}" for i in range(len(out))])
    return out


@dataclass
class Chunk:
    section_ref: str
    index: int
    pairs: pd.DataFrame

    @property
    def tag(self) -> str:
        return f"judge_{short_ref(self.section_ref)}_{self.index:03d}"


@dataclass
class ChunkResult:
    verdicts: dict[str, str] = field(default_factory=dict)
    review: list[dict] = field(default_factory=list)
    failed: bool = False
    fix_calls: int = 0


def chunks(cands: pd.DataFrame, size: int) -> list[Chunk]:
    out = []
    for ref, group in cands.groupby("section_ref", sort=True):
        for i in range(0, len(group), size):
            out.append(Chunk(ref, i // size, group.iloc[i : i + size]))
    return out


def render_pairs(pairs: pd.DataFrame, claims: pd.DataFrame) -> str:
    by_id = claims.set_index("claim_id")

    def side(label: str, cid: str) -> str:
        c = by_id.loc[cid]
        return f"{label}: stance={c['stance']} ask={c['ask']}\n   quote: {c['quote']}"

    return "\n".join(
        f"--- PAIR {p.pair_id} ---\n{side('A', p.claim_a)}\n{side('B', p.claim_b)}\n"
        for p in pairs.itertuples()
    )


class Judge:
    def __init__(self, cfg: Config, llm: LLM, ctx: dict[str, dict], claims: pd.DataFrame):
        self.cfg, self.llm, self.ctx, self.claims = cfg, llm, ctx, claims
        self.system = prompt("system")
        self.static_tpl, self.user_tpl = split_static(prompt("judge"), "{pairs}")
        self.budget_hit = False

    def run_chunk(self, chunk: Chunk) -> ChunkResult:
        res = ChunkResult()
        ids = list(chunk.pairs["pair_id"])
        if self.budget_hit:
            res.failed = True
            return res
        c = self.ctx.get(chunk.section_ref, {})
        static = render(
            self.static_tpl, section_ref=short_ref(chunk.section_ref), heading=c.get("heading", "")
        )
        user = render(self.user_tpl, pairs=render_pairs(chunk.pairs, self.claims))
        try:
            out = self.llm.call(chunk.tag, "judge", self.system, static, user, schema("judge"))
            verdicts = {p["pair_id"]: p["verdict"] for p in out["pairs"] if p["pair_id"] in ids}
            missing = [i for i in ids if i not in verdicts]
            if missing:
                res.fix_calls = 1
                fb = (
                    f"{user}\n\nYOUR PREVIOUS ANSWER LEFT OUT PAIRS. Previous answer:\n"
                    f"{json.dumps(out)}\n\nMissing pair ids: {missing}. Return every one of the "
                    f"{len(ids)} pair ids exactly once."
                )
                out = self.llm.call(
                    f"{chunk.tag}_fix1", "judge", self.system, static, fb, schema("judge")
                )
                for p in out["pairs"]:
                    if p["pair_id"] in ids and p["pair_id"] not in verdicts:
                        verdicts[p["pair_id"]] = p["verdict"]
        except BudgetExceeded:
            self.budget_hit = True
            res.failed = True
            return res
        except CallFailed as e:
            res.failed = True
            res.review.append(
                {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                 "detail": {"tag": chunk.tag, "pairs": ids, "error": str(e)[:300]}}
            )  # fmt: skip
            return res
        for i in ids:
            if i not in verdicts:
                verdicts[i] = "different"
                res.review.append(
                    {"claim_id": None, "issue_id": None, "reason": "missing_from_output",
                     "detail": {"pair_id": i, "tag": chunk.tag}}
                )  # fmt: skip
        pairs_by_id = chunk.pairs.set_index("pair_id")
        for i, v in verdicts.items():
            if v == "unsure":
                res.review.append(
                    {"claim_id": pairs_by_id.loc[i, "claim_a"], "issue_id": None,
                     "reason": "judge_unsure",
                     "detail": {"pair_id": i, "claim_b": pairs_by_id.loc[i, "claim_b"]}}
                )  # fmt: skip
        res.verdicts = verdicts
        return res


def run(
    claims: pd.DataFrame, ctx: dict[str, dict], llm: LLM, cfg: Config,
    vecs: np.ndarray | None = None,
) -> tuple[pd.DataFrame, list[dict], dict]:  # fmt: skip
    """pairs.parquet rows, review rows and stats. `vecs` lets issues.py reuse the embeddings."""
    if vecs is None:
        vecs = embed_claims(claims, embedder(cfg))
    cands = candidates(claims, vecs, cfg)
    judge = Judge(cfg, llm, ctx, claims)
    work = chunks(cands, cfg.pairs_per_call)
    with ThreadPoolExecutor(max(1, cfg.threads)) as pool:
        results = list(pool.map(judge.run_chunk, work))
    verdicts: dict[str, str] = {}
    tags: dict[str, str] = {}
    for chunk, res in zip(work, results, strict=True):
        for i in chunk.pairs["pair_id"]:
            tags[i] = chunk.tag
        verdicts.update(res.verdicts)
    cands["verdict"] = cands["pair_id"].map(verdicts)  # NaN where the call failed
    cands["tag"] = cands["pair_id"].map(tags)
    pairs = cands[PAIR_COLUMNS]
    judged = pairs["verdict"].notna()
    stats = {
        "pairs_proposed": int(len(pairs)),
        "pairs_judged": int(judged.sum()),
        "verdicts": {k: int(v) for k, v in pairs.loc[judged, "verdict"].value_counts().items()},
        "judge_calls": len(work),
        "judge_fix_calls": sum(r.fix_calls for r in results),
        "judge_batches_failed": sum(1 for r in results if r.failed),
        "budget_exceeded": judge.budget_hit,
    }
    review = [row for r in results for row in r.review]
    return pairs, review, stats
