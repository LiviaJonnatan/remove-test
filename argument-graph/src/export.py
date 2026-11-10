"""The review queue, the graph export and the run summary.

review.parquet   every review row from every stage: claim_id, issue_id, reason, detail (json)
graph.json       nodes section, letter, campaign, claim, issue; edges letter_section, letter_claim,
                 claim_issue, letter_campaign. eval/match.py writes response nodes and
                 issue_response edges into graph_eval.json, never here: the final rule does not
                 exist when the analyst writes
summary.json     counts that reconcile with passages.parquet, the ledger totals by step, the
                 model, backend and prompt hashes, and the sha256 of the letters and passages read
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from config import Config

REVIEW_REASONS = [
    "quote_failed", "quote_fragment", "section_disagrees", "no_section", "linker_disagrees",
    "missing_from_output", "llm_failed", "contested_merge", "giant_issue", "judge_unsure",
]  # fmt: skip


def review_frame(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(
        [
            {"claim_id": r.get("claim_id"), "issue_id": r.get("issue_id"), "reason": r["reason"],
             "detail": json.dumps(r.get("detail") or {}, default=str)}
            for r in rows
        ],
        columns=["claim_id", "issue_id", "reason", "detail"],
    )  # fmt: skip
    return out.astype({"claim_id": "string", "issue_id": "string"})


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for rec in df.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if v is pd.NA or (isinstance(v, float) and pd.isna(v)):
                v = None
            elif hasattr(v, "tolist"):
                v = v.tolist()
            elif hasattr(v, "item"):
                v = v.item()
            clean[k] = v
        out.append(clean)
    return out


def graph(
    docket: str, letters: pd.DataFrame, campaigns: pd.DataFrame, claims: pd.DataFrame,
    issues: pd.DataFrame, claim_issues: pd.DataFrame, ctx: dict[str, dict],
) -> dict:  # fmt: skip
    used_letters = set(claims["letter_id"])
    letter_rows = letters[letters["letter_id"].isin(used_letters)]
    campaign_of = dict(zip(claims["letter_id"], claims["campaign_id"], strict=True))
    used_campaigns = {c for c in claims["campaign_id"] if isinstance(c, str) and c}
    nodes = {
        "section": [
            {"section_ref": ref, "heading": ctx.get(ref, {}).get("heading", "")}
            for ref in sorted(set(claims["section_ref"]))
        ],
        "letter": [
            {"letter_id": r.letter_id, "kind": r.kind, "state": r.state,
             "campaign_id": campaign_of.get(r.letter_id), "org_id": None}
            for r in letter_rows.itertuples()
        ],  # fmt: skip
        "campaign": _records(campaigns[campaigns["campaign_id"].isin(used_campaigns)]),
        "claim": _records(
            claims[
                ["claim_id", "letter_id", "passage_id", "section_ref", "quote", "stance", "ask",
                 "evidence_type", "needs_review", "linker_rank"]
            ]
        ),  # fmt: skip
        "issue": _records(issues),
    }
    edges = {
        "letter_section": _records(
            claims[["letter_id", "section_ref"]].drop_duplicates().reset_index(drop=True)
        ),
        "letter_claim": _records(claims[["letter_id", "claim_id"]]),
        "claim_issue": _records(claim_issues),
        "letter_campaign": [
            {"letter_id": lid, "campaign_id": cid}
            for lid, cid in campaign_of.items() if isinstance(cid, str) and cid
        ],  # fmt: skip
    }
    return {"docket_id": docket, "nodes": nodes, "edges": edges}


def ledger_totals(rows: list[dict]) -> dict:
    by_step: dict[str, dict] = {}
    for r in rows:
        s = by_step.setdefault(r["step"], {"calls": 0, "usd": 0.0, "cache_read_tokens": 0,
                                           "cache_write_tokens": 0, "output_tokens": 0,
                                           "input_tokens": 0, "secs": 0.0})  # fmt: skip
        if r.get("cached"):
            continue
        s["calls"] += 1
        s["usd"] += r.get("usd") or 0.0
        for k in ("cache_read_tokens", "cache_write_tokens", "output_tokens", "input_tokens"):
            s[k] += r.get(k) or 0
        s["secs"] += r.get("secs") or 0.0
    for s in by_step.values():
        s["usd"] = round(s["usd"], 4)
        s["secs"] = round(s["secs"], 1)
    models = sorted({r.get("model") for r in rows if r.get("model") and not r.get("cached")})
    return {
        "calls_by_step": {k: v["calls"] for k, v in by_step.items()},
        "usd_by_step": {k: v["usd"] for k, v in by_step.items()},
        "usd_total": round(sum(v["usd"] for v in by_step.values()), 4),
        "cache_read_tokens": sum(v["cache_read_tokens"] for v in by_step.values()),
        "cache_write_tokens": sum(v["cache_write_tokens"] for v in by_step.values()),
        "input_tokens": sum(v["input_tokens"] for v in by_step.values()),
        "output_tokens": sum(v["output_tokens"] for v in by_step.values()),
        "model_seconds": round(sum(v["secs"] for v in by_step.values()), 1),
        "models_seen": models,
        "calls_cached": sum(1 for r in rows if r.get("cached")),
        "calls_failed": sum(1 for r in rows if not r.get("ok")),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
    out: Path, docket: str, paths: dict[str, Path], letters: pd.DataFrame, campaigns: pd.DataFrame,
    claims: pd.DataFrame, issues: pd.DataFrame, claim_issues: pd.DataFrame,
    review_rows: list[dict], stats: dict, ledger_rows: list[dict], cfg: Config, backend: str,
    ctx: dict[str, dict], rule_context_source: str, wall_clock_s: float,
) -> dict:  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    review = review_frame(review_rows)
    review.to_parquet(out / "review.parquet", index=False)
    (out / "graph.json").write_text(
        json.dumps(graph(docket, letters, campaigns, claims, issues, claim_issues, ctx), indent=1,
                   default=str)  # fmt: skip
    )
    by_reason = {k: int(v) for k, v in review["reason"].value_counts().items()}
    totals = ledger_totals(ledger_rows)
    summary = {
        "docket_id": docket,
        "passages_in": stats.get("passages_in", 0),
        "passages_extracted": stats.get("passages_extracted", 0),
        "claims": int(len(claims)),
        "claims_first_pass": stats.get("claims_first_pass", 0),
        "quotes_verified_first_pass": stats.get("quotes_verified_first_pass", 0),
        "quotes_verified_final": stats.get("quotes_verified_final", 0),
        "claims_dropped": stats.get("claims_dropped", 0),
        "claims_needs_review": int(claims["needs_review"].sum()) if len(claims) else 0,
        "issues": stats.get("issues", int(len(issues))),
        "issues_multi_claim": stats.get("issues_multi_claim", 0),
        "flagged": stats.get("flagged", 0),
        "review_rows": int(len(review)),
        "review_rows_by_reason": {k: by_reason.get(k, 0) for k in REVIEW_REASONS},
        "review_share_of_claims": round(len(review) / len(claims), 4) if len(claims) else None,
        # Rows over claims counts a claim with two reasons twice and issue-level rows once each.
        # Distinct claims named in a row is the other reading of "review load".
        "review_claims_distinct": int(review["claim_id"].dropna().nunique()),
        "review_issue_rows": int(review["claim_id"].isna().sum()),
        "review_claims_share": round(review["claim_id"].dropna().nunique() / len(claims), 4)
        if len(claims)
        else None,
        "pairs_proposed": stats.get("pairs_proposed", 0),
        "pairs_judged": stats.get("pairs_judged", 0),
        "pair_verdicts": stats.get("verdicts", {}),
        "forced_fallbacks": by_reason.get("missing_from_output", 0),
        "extract_batches_failed": stats.get("batches_failed", 0),
        "judge_batches_failed": stats.get("judge_batches_failed", 0),
        "budget_exceeded": bool(stats.get("budget_exceeded")),
        "linker_checked": stats.get("linker_checked", False),
        "linker_agree": stats.get("linker_agree"),
        "linker_agree_share": stats.get("linker_agree_share"),
        "model": cfg.model if backend == "cli" else cfg.model_id,
        "model_id": totals["models_seen"],
        "backend": backend,
        "effort": cfg.effort if backend == "sdk" else None,
        "prompt_sha1s": {"extract": stats.get("prompt_sha1")},
        **totals,
        "wall_clock_s": round(wall_clock_s, 1),
        "rule_context": rule_context_source if rule_context_source != "none" else False,
        "letters_file": str(paths["letters"]),
        "letters_sha256": sha256(paths["letters"]),
        "passages_sha256": sha256(paths["passages"]),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    if cfg.wandb:
        log_wandb(summary)
    return summary


def log_wandb(summary: dict) -> None:
    try:
        import wandb
    except ImportError:
        print("argument-graph: GRAPH_WANDB=1 but wandb is not installed (uv sync --extra track)")
        return
    run = wandb.init(project="undersigned-graph", name=f"graph-{summary['docket_id']}",
                     config={k: summary[k] for k in ("model", "backend", "effort")})  # fmt: skip
    run.log(
        {k: summary[k] for k in (
            "passages_in", "claims", "issues", "flagged", "review_rows", "usd_total",
            "cache_read_tokens", "wall_clock_s",
        ) if isinstance(summary.get(k), (int, float))}
    )  # fmt: skip
    run.finish()
