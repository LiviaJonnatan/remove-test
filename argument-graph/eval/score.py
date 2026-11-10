"""Metrics for the argument graph against the final rule's summarised points. Every number is
computed from files on disk; none is typed in. The frozen linker's test top-5 is read from the
linker-train metrics file (--linker-metrics).

Inputs: a graph folder (claims, issues, claim_issues, review, summary), eval/out/points.parquet,
eval/out/<name>/matches.parquet and points_scored.parquet for the pipeline and each baseline, and
optionally the passages folder for the length baseline.

  block recall          blocks with >= 1 point matched by >= 1 issue, over the blocks with points
  point recall          top3: points matched by any of the three nearest candidate issues
                        top2: points matched by either of the two nearest
                        catch-all points (blocks about no single provision) reported apart
  intervals             95% percentile bootstrap over blocks, 1,000 draws: a draw resamples blocks
                        with replacement and takes every point of each drawn block, since the
                        points of one block share a section and a candidate pool. The same draws
                        score every system, so the paired difference of each baseline against the
                        pipeline gets an interval too
  compression           issues / claims / passages per section
  significance recall   points with an explicit response (in the same paragraph or the next)
                        matched by a flagged issue, against flag-all, top-k by n_letters and top-k
                        by passage words (k = flagged)
  linker agreement      claims whose cited section is in the frozen linker's top 5
  review load           two readings: rows / claims (a claim with two reasons counts twice, an
                        issue-level row once) and distinct claims named in a row / claims. Both are
                        reported against the 20% bar
  cost                  from summary.json

Usage: python eval/score.py --graph-dir ../data/derived/graph/EPA-HQ-OW-2022-0801
       [--matches eval/out] [--passages ../data/derived/passages/EPA-HQ-OW-2022-0801]
       [--out eval/out] [--seed 215] [--boot 1000] [--systems pipeline,B0,B1,B2]
       [--linker-metrics ../docs/evidence/linker-train/in-pre/metrics.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REVIEW_FAIL_SHARE = 0.20
LINKER_METRICS = HERE.parents[1] / "docs" / "evidence" / "linker-train" / "in-pre" / "metrics.json"

LIMITS = """## Limits

- The labels are summary level. The preamble says what commenters said and what the EPA did, with
  no excerpt and no commenter id, so a point is matched to an issue by meaning, judged by a model
  and checked by two readers on a sample.
- The EPA chose what to summarise. Comments it judged insignificant are not in the preamble, so
  point recall is a recall label only and says nothing about what else the commenters said.
- One rule, one agency. Nothing here was scored outside EPA-HQ-OW-2022-0801.
- The 3,529-page Response to Comments document (EPA-HQ-OW-2022-0801-2645) is not on disk; the
  preamble is the only label source.
- Point boundaries inside paragraphs that carry both the summary and the response are heuristic.
  The reader pack's 40-item boundary check reports the error rate.
- The intervals are bootstrap percentiles over blocks. With 34 blocks and recall concentrated in a
  few of them they are wide; they say how much the sample of blocks moves the number, not whether
  the matcher is right.
"""


def load_matches(root: Path, name: str) -> pd.DataFrame | None:
    p = root / name / "matches.parquet"
    return pd.read_parquet(p) if p.exists() else None


def hit_sets(matches: pd.DataFrame) -> tuple[set[str], set[str]]:
    """Points matched by any of the top-3 candidates, and by either of the top-2."""
    hits = matches[matches["match"] == True]  # noqa: E712
    return set(hits["point_id"]), set(hits[hits["rank"] <= 2]["point_id"])


def per_block(points: pd.DataFrame, top3: set[str], top2: set[str]) -> pd.DataFrame:
    """One row per block: regular points and hits, for the bootstrap."""
    sub = points[points["catch_all"] == False]  # noqa: E712
    df = pd.DataFrame(
        {
            "points": sub.groupby("block").size(),
            "top3": sub.groupby("block")["point_id"].agg(lambda s: s.isin(top3).sum()),
            "top2": sub.groupby("block")["point_id"].agg(lambda s: s.isin(top2).sum()),
        }
    )
    # Block recall counts catch-all blocks too.
    all_blocks = points.groupby("block")["point_id"].agg(lambda s: s.isin(top3).sum())
    df = df.reindex(all_blocks.index).fillna(0).astype(int)
    df["any_hit"] = (all_blocks > 0).astype(int)
    return df


def block_draws(blocks: list[str], rng: np.random.Generator, boot: int) -> list[np.ndarray]:
    return [rng.choice(blocks, size=len(blocks), replace=True) for _ in range(boot)]


def draw_recalls(pb: pd.DataFrame, draws: list[np.ndarray]) -> dict[str, np.ndarray]:
    """Per draw: top3 and top2 point recall, block recall."""
    out = {"top3": [], "top2": [], "block": []}
    for d in draws:
        sub = pb.loc[d]
        n = sub["points"].sum()
        out["top3"].append(sub["top3"].sum() / n if n else np.nan)
        out["top2"].append(sub["top2"].sum() / n if n else np.nan)
        out["block"].append(sub["any_hit"].mean())
    return {k: np.asarray(v, dtype=float) for k, v in out.items()}


def ci95(vals: np.ndarray) -> list[float] | None:
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def recall_tables(points: pd.DataFrame, matches: pd.DataFrame, draws: list[np.ndarray]) -> dict:
    top3, top2 = hit_sets(matches)
    out: dict = {}
    for label, mask in (
        ("all", points["catch_all"] == False),  # noqa: E712
        ("catch_all", points["catch_all"] == True),  # noqa: E712
    ):
        sub = points[mask]
        n = len(sub)
        out[label] = {
            "points": int(n),
            "top3": round(sub["point_id"].isin(top3).mean(), 4) if n else None,
            "top2": round(sub["point_id"].isin(top2).mean(), 4) if n else None,
        }
    pb = per_block(points, top3, top2)
    out["block_recall"] = round(pb["any_hit"].mean(), 4)
    out["blocks"] = int(len(pb))
    out["blocks_hit"] = int(pb["any_hit"].sum())
    out["points_hit"] = int(points["point_id"].isin(top3).sum())
    if draws:
        dr = draw_recalls(pb, draws)
        out["all"]["top3_ci95"] = ci95(dr["top3"])
        out["all"]["top2_ci95"] = ci95(dr["top2"])
        out["block_recall_ci95"] = ci95(dr["block"])
        out["_draws"] = dr
    out["_top3"] = top3
    return out


def paired(points: pd.DataFrame, base: dict, other: dict) -> dict:
    """Hit counts of two systems on the regular points, and the bootstrap of their difference."""
    regular = set(points[points["catch_all"] == False]["point_id"])  # noqa: E712
    a, b = base["_top3"] & regular, other["_top3"] & regular
    out = {
        "both": len(a & b),
        "only_pipeline": len(a - b),
        "only_other": len(b - a),
        "neither": len(regular - a - b),
    }
    if "_draws" in base and "_draws" in other:
        for k in ("top3", "top2"):
            diff = other["_draws"][k] - base["_draws"][k]
            out[f"{k}_diff"] = round(other["all"][k] - base["all"][k], 4)
            out[f"{k}_diff_ci95"] = ci95(diff)
    return out


def significance_recall(points: pd.DataFrame, matches: pd.DataFrame, issues: pd.DataFrame,
                        claims: pd.DataFrame, claim_issues: pd.DataFrame,
                        passages: pd.DataFrame | None) -> dict:  # fmt: skip
    """Points with an explicit response matched by a flagged issue, against three baselines."""
    explicit = set(points[points["has_explicit_response"]]["point_id"])
    hits = matches[(matches["match"] == True) & matches["point_id"].isin(explicit)]  # noqa: E712
    k = int(issues["significant"].sum())
    out: dict = {"explicit_points": len(explicit), "flagged": k}
    if "response_where" in points:
        out["explicit_by_where"] = {
            w: int((points["response_where"] == w).sum()) for w in ("same_paragraph",
                                                                  "next_paragraph", "none")
        }  # fmt: skip
    if not explicit or k == 0:
        return out

    def recall_for(flagged: set[str]) -> float:
        got = set(hits[hits["issue_id"].isin(flagged)]["point_id"])
        return round(len(got) / len(explicit), 4)

    out["rule"] = recall_for(set(issues[issues["significant"]]["issue_id"]))
    out["flag_all"] = recall_for(set(issues["issue_id"]))
    by_letters = issues.sort_values(["n_letters", "n_claims"], ascending=False).head(k)
    out["top_k_by_n_letters"] = recall_for(set(by_letters["issue_id"]))
    if passages is not None:
        words = dict(zip(passages["passage_id"], passages["n_words"], strict=True))
        cw = claims.assign(words=claims["passage_id"].map(words).fillna(0))
        iw = (
            claim_issues.merge(cw[["claim_id", "words"]], on="claim_id")
            .groupby("issue_id")["words"]
            .sum()
        )
        out["top_k_by_passage_words"] = recall_for(
            set(iw.sort_values(ascending=False).head(k).index)
        )
    return out


def review_load(review: pd.DataFrame, claims: pd.DataFrame, summary: dict) -> dict:
    n = len(claims)
    named = review["claim_id"].dropna() if "claim_id" in review else pd.Series(dtype=str)
    rows_share = len(review) / n if n else None
    claims_share = named.nunique() / n if n else None
    return {
        "rows": int(len(review)),
        "claims": int(n),
        "share_rows": round(rows_share, 4) if rows_share is not None else None,
        "fails_20pct_rows": bool(rows_share is not None and rows_share > REVIEW_FAIL_SHARE),
        "claims_distinct": int(named.nunique()),
        "claims_with_two_rows": int((named.value_counts() > 1).sum()),
        "issue_rows": int(review["claim_id"].isna().sum()) if "claim_id" in review else 0,
        "share_claims": round(claims_share, 4) if claims_share is not None else None,
        "fails_20pct_claims": bool(claims_share is not None and claims_share > REVIEW_FAIL_SHARE),
        "by_reason": summary.get("review_rows_by_reason"),
    }


def linker_test_top5(path: Path) -> float | None:
    if not path.exists():
        return None
    m = json.loads(path.read_text())
    return m["test"]["acc@5"][0]


def strip_private(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-dir", required=True)
    ap.add_argument("--matches", default=str(HERE / "out"))
    ap.add_argument("--points", default=str(HERE / "out" / "points.parquet"))
    ap.add_argument("--passages", default=None)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--seed", type=int, default=215)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--systems", default="pipeline,B0,B1,B2")
    ap.add_argument("--linker-metrics", default=str(LINKER_METRICS))
    a = ap.parse_args()
    g = Path(a.graph_dir)
    claims = pd.read_parquet(g / "claims.parquet")
    issues = pd.read_parquet(g / "issues.parquet")
    claim_issues = pd.read_parquet(g / "claim_issues.parquet")
    review = pd.read_parquet(g / "review.parquet")
    summary = json.loads((g / "summary.json").read_text())
    points = pd.read_parquet(a.points)
    passages = pd.read_parquet(Path(a.passages) / "passages.parquet") if a.passages else None
    rng = np.random.default_rng(a.seed)
    root = Path(a.matches)
    # match.py --sample scores a seeded subset. Systems are compared on the points every one of
    # them scored, so the denominators here are that intersection, not every point the parser found.
    # A point the parser no longer emits drops out here even if a system once scored it.
    systems = [x for x in a.systems.split(",") if x]
    keep: set[str] | None = None
    for name in systems:
        scored = root / name / "points_scored.parquet"
        if scored.exists() and load_matches(root, name) is not None:
            ids = set(pd.read_parquet(scored)["point_id"])
            keep = ids if keep is None else keep & ids
    if keep is not None:
        points = points[points["point_id"].isin(keep)].reset_index(drop=True)

    regular = int((points["catch_all"] == False).sum())  # noqa: E712
    results: dict = {"docket_id": summary["docket_id"], "systems": {},
                     "points_scored": int(len(points)), "points_scored_regular": regular,
                     "bootstrap": {"unit": "block", "draws": a.boot, "seed": a.seed}}  # fmt: skip
    draws = block_draws(sorted(points["block"].unique()), rng, a.boot) if a.boot else []
    tables: dict[str, dict] = {}
    for name in systems:
        m = load_matches(root, name)
        if m is None:
            continue
        m = m[m["point_id"].isin(set(points["point_id"]))]
        tables[name] = recall_tables(points, m, draws)
        results["systems"][name] = strip_private(tables[name])
        results["systems"][name]["all"] = strip_private(tables[name]["all"])
    if "pipeline" in tables:
        results["paired_vs_pipeline"] = {
            name: paired(points, tables["pipeline"], t) for name, t in tables.items()
            if name != "pipeline"
        }  # fmt: skip
    pipeline_matches = load_matches(root, "pipeline")
    if pipeline_matches is not None:
        pm = pipeline_matches[pipeline_matches["point_id"].isin(set(points["point_id"]))]
        results["significance"] = significance_recall(
            points, pm, issues, claims, claim_issues, passages
        )
    per_section = claims.groupby("section_ref").size().rename("claims").to_frame()
    per_section["issues"] = issues.groupby("section_ref").size()
    per_section["passages"] = claims.groupby("section_ref")["passage_id"].nunique()
    results["compression"] = {
        "issues_per_claim": round(len(issues) / len(claims), 4) if len(claims) else None,
        "issues_per_passage": round(len(issues) / summary["passages_extracted"], 4)
        if summary.get("passages_extracted")
        else None,
        "by_section": per_section.fillna(0).astype(int).to_dict(orient="index"),
    }
    metrics = Path(a.linker_metrics)
    results["linker_agreement"] = {
        "checked": summary.get("linker_checked"),
        "agree_share": summary.get("linker_agree_share"),
        "frozen_test_top5": linker_test_top5(metrics),
        "frozen_test_top5_source": str(metrics.relative_to(HERE.parents[1]))
        if metrics.exists() and metrics.is_relative_to(HERE.parents[1])
        else None,
    }
    results["review_load"] = review_load(review, claims, summary)
    results["cost"] = {
        k: summary.get(k)
        for k in (
            "usd_total",
            "usd_by_step",
            "calls_by_step",
            "cache_read_tokens",
            "cache_write_tokens",
            "output_tokens",
            "wall_clock_s",
            "model_id",
            "backend",
            "effort",
        )
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    (out / "results.md").write_text(render_md(results))
    print(json.dumps({k: results[k] for k in ("systems", "paired_vs_pipeline", "significance",
                                              "review_load") if k in results},
                     indent=2, default=str))  # fmt: skip
    return 0


def fmt_ci(ci: list[float] | None) -> str:
    return f" [{ci[0]}, {ci[1]}]" if ci else ""


def render_md(r: dict) -> str:
    lines = [f"# Eval: argument graph on {r['docket_id']}", "",
             f"{r['points_scored']} points scored by every system ({r['points_scored_regular']} "
             f"regular). Intervals: 95% percentile bootstrap over blocks, "
             f"{r['bootstrap']['draws']} draws, seed {r['bootstrap']['seed']}.", ""]  # fmt: skip
    lines += ["| System | Block recall | Point recall (top-3) | Point recall (top-2) | "
              "Catch-all (top-3) |",
              "|---|---|---|---|---|"]  # fmt: skip
    for name, s in r["systems"].items():
        lines.append(
            f"| {name} | {s['block_recall']}{fmt_ci(s.get('block_recall_ci95'))} "
            f"({s['blocks_hit']} of {s['blocks']} blocks) | "
            f"{s['all']['top3']}{fmt_ci(s['all'].get('top3_ci95'))} | "
            f"{s['all']['top2']}{fmt_ci(s['all'].get('top2_ci95'))} | "
            f"{s['catch_all']['top3']} ({s['catch_all']['points']} points) |"
        )
    if r.get("paired_vs_pipeline"):
        lines += ["", "| Against the pipeline, regular points | Both hit | Pipeline only | "
                  "Other only | Neither | Top-3 difference |",
                  "|---|---|---|---|---|---|"]  # fmt: skip
        for name, p in r["paired_vs_pipeline"].items():
            lines.append(
                f"| {name} | {p['both']} | {p['only_pipeline']} | {p['only_other']} | "
                f"{p['neither']} | {p.get('top3_diff')}{fmt_ci(p.get('top3_diff_ci95'))} |"
            )
    if "significance" in r:
        sg = r["significance"]
        lines += ["", f"| Significance (k = {sg['flagged']}) | Recall on the "
                  f"{sg['explicit_points']} points with an explicit response |",
                  "|---|---|"]  # fmt: skip
        for k in ("rule", "flag_all", "top_k_by_n_letters", "top_k_by_passage_words"):
            if k in sg:
                lines.append(f"| {k} | {sg[k]} |")
        if "explicit_by_where" in sg:
            lines.append(f"\nResponse location of the scored points: {sg['explicit_by_where']}.")
    c = r["compression"]
    lines += ["", f"Compression: {c['issues_per_claim']} issues per claim, "
              f"{c['issues_per_passage']} issues per passage."]  # fmt: skip
    rl = r["review_load"]
    lines += ["", f"Review load, rows over claims: {rl['rows']} / {rl['claims']} = "
              f"{rl['share_rows']}, fails the 20% bar: {rl['fails_20pct_rows']}. Distinct claims "
              f"named in a row: {rl['claims_distinct']} / {rl['claims']} = {rl['share_claims']}, "
              f"fails the 20% bar: {rl['fails_20pct_claims']} ({rl['claims_with_two_rows']} claims "
              f"carry two rows, {rl['issue_rows']} rows are issue-level). "
              f"By reason: {rl['by_reason']}"]  # fmt: skip
    la = r["linker_agreement"]
    lines += ["", f"Linker agreement: {la['agree_share']} (frozen test top-5: "
              f"{la['frozen_test_top5']}, from {la['frozen_test_top5_source']}); "
              f"checked: {la['checked']}."]  # fmt: skip
    lines += ["", f"Cost: {r['cost']}", "", LIMITS]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
