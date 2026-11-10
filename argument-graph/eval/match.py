"""Match the agency's summarised points (parse_preamble.py) to the issues the graph built.

Per point: embed the point text with the same bge-small the pipeline uses, take the top-3 issues
whose section is among the point's sections (every section for a catch-all point, or a point whose
block cites no section), and ask the model whether a response written to the issue would also
answer the point. Points go to the model in batches (--per-call, default 10) so the pilot stays
inside its budget; each point is judged on its own inside the call, and every (point, candidate)
pair must come back exactly once.

Writes eval/out/<name>/matches.parquet (point_id, issue_id, rank, cosine, match),
points_scored.parquet (the point set this system was scored on) and graph_eval.json with
`response` nodes (the points) and `issue_response` edges (the matches). The pipeline's own
graph.json never carries these: the final rule does not exist when the analyst writes.

The same script scores a baseline's issue table: --issues eval/out/baselines/B1/issues.parquet
--name B1. --sample N draws the same seeded, block-stratified N points for every system, so
systems are compared on one point set.

Caching: a batch's tag is match_<name>_<sha1 of its point ids>, and raw/<tag>.json also stores the
prompt's hash, so a rerun over the same points and candidates makes no call. --reuse keeps the
point set of the previous run (points_scored.parquet, minus points the parser no longer emits) and
the previous verdicts for every point whose candidate list is unchanged; only points with new
candidates go to the model. That is how a parser or candidate-rule fix is scored without paying
for the unchanged points again.

Usage: python eval/match.py --graph-dir ../data/derived/graph/EPA-HQ-OW-2022-0801
       [--issues <issues.parquet>] [--name pipeline] [--points eval/out/points.parquet] [--k 3]
       [--sample 200] [--seed 215] [--per-call 10] [--threads 8] [--reuse] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from config import Config  # noqa: E402
from llm import LLM, BudgetExceeded, CallFailed  # noqa: E402
from pairs import embedder  # noqa: E402
from templates import render  # noqa: E402

MATCH_SCHEMA = json.loads((HERE.parent / "schemas" / "match.json").read_text())
PROMPT = (HERE / "prompts" / "match.md").read_text().strip()
SYSTEM = (HERE.parent / "prompts" / "system.md").read_text().strip()


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)


def candidates_for(point, issues: pd.DataFrame, ivecs: np.ndarray, pvec: np.ndarray, k: int):
    refs = list(point.section_refs) if len(point.section_refs) else []
    widen = bool(point.catch_all) or not refs
    mask = np.ones(len(issues), bool) if widen else issues["section_ref"].isin(refs).to_numpy()
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    cos = ivecs[idx] @ pvec
    order = idx[np.argsort(-cos, kind="stable")[:k]]
    return [(issues.iloc[i]["issue_id"], float(ivecs[i] @ pvec)) for i in order]


def sample_points(points: pd.DataFrame, n: int | None, seed: int) -> pd.DataFrame:
    """The same seeded, block-stratified sample for every system."""
    if n is None or len(points) <= n:
        return points.reset_index(drop=True)
    rng = np.random.default_rng(seed)
    picked = []
    for _block, g in points.groupby("block", sort=True):
        quota = max(1, round(n * len(g) / len(points)))
        take = min(len(g), quota)
        picked.append(g.iloc[np.sort(rng.choice(len(g), size=take, replace=False))])
    out = pd.concat(picked)
    if len(out) > n:
        out = out.iloc[np.sort(rng.choice(len(out), size=n, replace=False))]
    return out.sort_values("point_id").reset_index(drop=True)


def batch_tag(name: str, batch: list) -> str:
    ids = ",".join(p.point_id for p, _ in batch)
    return f"match_{name}_{hashlib.sha1(ids.encode()).hexdigest()[:10]}"


def reusable(previous: pd.DataFrame | None, point_id: str, cands: list) -> list[dict] | None:
    """The previous run's rows for a point whose candidates are the same, in the same order, and
    all judged; None when the point has to go to the model."""
    if previous is None:
        return None
    rows = previous[previous["point_id"] == point_id].sort_values("rank")
    if len(rows) != len(cands) or rows["match"].isna().any():
        return None
    if list(rows["issue_id"]) != [iid for iid, _ in cands]:
        return None
    return rows.to_dict(orient="records")


def render_point(point, cands, by_issue: pd.DataFrame) -> str:
    blocks = "\n".join(
        f"--- ISSUE {iid} (§ {by_issue.loc[iid, 'section_ref'].split('§ ')[-1]}) ---\n"
        f"{by_issue.loc[iid, 'label']}"
        for iid, _ in cands
    )
    return f"=== POINT {point.point_id} ===\n{point.text}\n{blocks}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-dir", required=True)
    ap.add_argument("--issues", default=None, help="an issues.parquet to score instead")
    ap.add_argument("--name", default="pipeline")
    ap.add_argument("--points", default=str(HERE / "out" / "points.parquet"))
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--sample", type=int, default=None, help="seeded stratified point sample")
    ap.add_argument("--seed", type=int, default=215)
    ap.add_argument("--per-call", type=int, default=10)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--reuse", action="store_true",
                    help="keep the previous point set and verdicts where candidates are unchanged")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would go to the model, call nothing, write nothing")
    a = ap.parse_args()

    graph_dir = Path(a.graph_dir)
    issues = pd.read_parquet(a.issues or graph_dir / "issues.parquet")
    out = Path(a.out) / a.name
    out.mkdir(parents=True, exist_ok=True)
    all_points = pd.read_parquet(a.points)
    previous = None
    if a.reuse and (out / "matches.parquet").exists():
        previous = pd.read_parquet(out / "matches.parquet")
        scored = set(pd.read_parquet(out / "points_scored.parquet")["point_id"])
        points = all_points[all_points["point_id"].isin(scored)].reset_index(drop=True)
    else:
        points = sample_points(all_points, a.sample, a.seed)
    cfg = Config.from_env()
    llm = LLM(cfg, out)  # ledger and raw/ live beside the matches

    embed = embedder(cfg)
    ivecs = unit(np.asarray(embed(issues["label"].fillna("").tolist()), dtype=np.float32))
    pvecs = unit(np.asarray(embed(points["text"].tolist()), dtype=np.float32))
    by_issue = issues.set_index("issue_id")

    work = []  # (point, cands) with at least one candidate
    kept: dict[tuple[str, str], bool] = {}  # verdicts carried over under --reuse
    n_reused = 0
    for i, point in enumerate(points.itertuples()):
        cands = candidates_for(point, issues, ivecs, pvecs[i], a.k)
        if not cands:
            continue
        old_rows = reusable(previous, point.point_id, cands)
        if old_rows is not None:
            n_reused += 1
            kept.update({(r["point_id"], r["issue_id"]): bool(r["match"]) for r in old_rows})
        work.append((point, cands))
    to_judge = [(p, c) for p, c in work if (p.point_id, c[0][0]) not in kept]
    batches = [to_judge[i : i + a.per_call] for i in range(0, len(to_judge), a.per_call)]
    if a.dry_run:
        print(
            f"{a.name}: {len(points)} points, {len(work)} with candidates, {n_reused} reused, "
            f"{len(to_judge)} to judge in {len(batches)} batches: "
            f"{sorted(p.point_id for p, _ in to_judge)}"
        )
        return 0

    def run_batch(batch: list) -> dict[tuple[str, str], bool]:
        tag = batch_tag(a.name, batch)
        user = render(PROMPT, points="\n".join(render_point(p, c, by_issue) for p, c in batch))
        expected = {(p.point_id, iid) for p, c in batch for iid, _ in c}
        try:
            res = llm.call(tag, "match", SYSTEM, "", user, MATCH_SCHEMA)
        except (CallFailed, BudgetExceeded):
            return {}
        got = {
            (m["point_id"], m["issue_id"]): bool(m["match"])
            for m in res["matches"]
            if (m["point_id"], m["issue_id"]) in expected
        }
        missing = expected - set(got)
        if missing:
            fb = (
                f"{user}\n\nYOUR PREVIOUS ANSWER LEFT OUT PAIRS. Previous answer:\n"
                f"{json.dumps(res)}\n\nMissing (point_id, issue_id) pairs: {sorted(missing)}. "
                "Return every pair exactly once."
            )
            try:
                res = llm.call(f"{tag}_fix1", "match", SYSTEM, "", fb, MATCH_SCHEMA)
                for m in res["matches"]:
                    key = (m["point_id"], m["issue_id"])
                    if key in missing:
                        got[key] = bool(m["match"])
            except (CallFailed, BudgetExceeded):
                pass
        return got

    with ThreadPoolExecutor(max(1, a.threads)) as pool:
        results = list(pool.map(run_batch, batches))
    verdict: dict[tuple[str, str], bool] = dict(kept)
    for r in results:
        verdict.update(r)

    rows = []
    for point, cands in work:
        for rank, (iid, cos) in enumerate(cands, start=1):
            rows.append(
                {"point_id": point.point_id, "block": point.block, "issue_id": iid,
                 "rank": rank, "cosine": round(cos, 4),
                 "match": verdict.get((point.point_id, iid)),
                 "catch_all": bool(point.catch_all),
                 "has_explicit_response": bool(point.has_explicit_response)}
            )  # fmt: skip
    matches = pd.DataFrame(rows)
    matches.to_parquet(out / "matches.parquet", index=False)
    points[["point_id"]].to_parquet(out / "points_scored.parquet", index=False)
    hits = matches[matches["match"] == True]  # noqa: E712
    graph_eval = {
        "nodes": {
            "response": [
                {
                    "point_id": p.point_id,
                    "block": p.block,
                    "text": p.text,
                    "section_refs": list(p.section_refs),
                    "catch_all": bool(p.catch_all),
                }
                for p in points.itertuples()
            ]  # fmt: skip
        },
        "edges": {
            "issue_response": [
                {"issue_id": h.issue_id, "point_id": h.point_id, "rank": int(h.rank)}
                for h in hits.itertuples()
            ]
        },
    }
    (out / "graph_eval.json").write_text(json.dumps(graph_eval, indent=1))
    matched_points = hits["point_id"].nunique()
    unanswered = int(matches["match"].isna().sum())
    print(
        f"{a.name}: {len(points)} points, {len(work)} with candidates, {n_reused} reused from the "
        f"previous run, {len(batches)} batches, {len(matches)} candidate pairs ({unanswered} "
        f"unanswered), {matched_points} points matched by at least one issue, ledger total "
        f"${llm.spent:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
