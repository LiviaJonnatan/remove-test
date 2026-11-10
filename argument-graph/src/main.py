"""argument-graph: claims, issues and a review queue from the comment passages that cite the rule.

For the staff who write the response to comments in a final rule. For each docket in DOCKET_IDS it
reads passage-stage's cited passages (one copy per campaign, so a form letter is read once), asks
the model for every claim a passage makes with a verbatim quote, a stance, an ask and the kind of
evidence offered, checks each quote against the passage with a string match, groups the claims of a
section into issues with embeddings proposing pairs and the model judging them, counts each issue
by distinct letters and campaigns, and flags the issues that carry new data, a legal argument or a
concrete alternative. Everything the checks could not settle goes to review.parquet.

Two model steps (extract, judge). Everything else is script. The linker is frozen and is used only
as a cross-check.

Writes to DATA_DIR/derived/graph/<docket>/ (schema.md §3c):
  claims.parquet        one row per claim, with quote, quote_verified, stance, ask, evidence_type
  pairs.parquet         one row per judged pair: claim_a, claim_b, cosine, verdict, tag
  issues.parquet        one row per issue: label, counts by letters and campaigns, significant
  claim_issues.parquet  claim -> issue edges
  review.parquet        the uncertainty queue: claim_id, issue_id, reason, detail
  graph.json            nodes and edges for the API and the analyst screens
  summary.json          counts, cost by step, model, prompt hashes, input checksums
  ledger.jsonl, raw/<tag>.json, prompts/<tag>.txt   one per model call; a rerun reuses raw/

Usage: python src/main.py [all|extract|pairs|issues|export]   (default all)
Each stage reads the previous stage's parquet, so a rerun from `pairs` costs no extraction calls.

Exit codes: 0 every batch produced valid output (or no backend: skipped with a message);
1 an input is missing or some batch failed after a re-ask; 2 GRAPH_MAX_USD was reached and partial
outputs were written.

Environment:
  DOCKET_IDS, DATA_DIR      as for the other stages (default EPA-HQ-OW-2022-0801, /app/data)
  GRAPH_BACKEND             cli | sdk | fake | none; default: sdk if ANTHROPIC_API_KEY is set, else
                            cli if `claude` is on PATH, else none
  GRAPH_MODEL               CLI model alias, default fable
  GRAPH_MODEL_ID            SDK model id, default claude-fable-5-1
  GRAPH_EFFORT              SDK only, default medium
  GRAPH_BATCH               passages per extract call, default 12
  GRAPH_PAIRS_PER_CALL      default 40
  GRAPH_PAIR_MIN            cosine floor for candidate pairs, default 0.60
  GRAPH_PAIR_K              max neighbours per claim, default 10
  GRAPH_MAX_PASSAGES        smoke cap: first N passages by (section, passage_id)
  GRAPH_MAX_PAIRS           cap on judged pairs, highest cosine first
  GRAPH_MAX_USD             cost guard, default 40
  GRAPH_THREADS             parallel model calls, default 8
  GRAPH_INCLUDE_UNCITED     1 adds passages the linker places above its margin cutoff (needs a
                            linker)
  GRAPH_LINKER_DIR, GRAPH_LINK_URL   cross-check source: the ONNX folder, or a running API
  GRAPH_LABEL_ISSUES        1 adds one label call per section
  GRAPH_WANDB               1 logs summary counts to W&B (optional extra `track`)
  ANTHROPIC_API_KEY         for the sdk backend
  CHROMA_HOST, CHROMA_PORT, CHROMA_PATH   where rule context comes from; rule text on disk otherwise
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import crosscheck
import export
import extract
import inputs
import issues as issues_mod
import pairs as pairs_mod
from config import Config
from llm import LLM, NoBackend

STAGES = ("extract", "pairs", "issues", "export")
EXIT_BUDGET = 2


def _read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str) + "\n")


def build_docket(
    docket: str, data_dir: Path, stage: str = "all", cfg: Config | None = None
) -> bool:
    """Run the stages from `stage` on for one docket. False when any batch failed."""
    cfg = cfg or Config.from_env()
    t0 = time.time()
    data = inputs.load(docket, data_dir)
    out = data_dir / "derived" / "graph" / docket
    work = out / "work"
    out.mkdir(parents=True, exist_ok=True)
    try:
        llm = LLM(cfg, out)
    except NoBackend as e:
        print(f"argument-graph: no LLM backend ({e}), skipping {docket}")
        return True

    chunks, ctx_source = inputs.rule_chunks(docket, data_dir)
    ctx = inputs.rule_context(chunks)
    section_order = list(ctx)
    stages = STAGES if stage == "all" else STAGES[STAGES.index(stage) :]
    ok = True
    stats: dict = {}
    review: list[dict] = []
    vecs = None

    if "extract" in stages:
        link = crosscheck.open_linker(cfg, chunks, docket)
        selected = inputs.select(data, cfg, link=link, section_order=section_order)
        claims, review, stats = extract.run(selected, data.letters, ctx, llm, cfg, docket)
        texts = dict(zip(selected["passage_id"], selected["text"], strict=True))
        claims, more, cstats = crosscheck.run(claims, texts, link)
        review += more
        stats.update(cstats)
        claims.to_parquet(out / "claims.parquet", index=False)
        _write_json(work / "review_extract.json", review)
        _write_json(work / "stats_extract.json", stats)
        ok = ok and stats["batches_failed"] == 0 and not stats["budget_exceeded"]
        print(
            f"[{docket}] extract: {stats['passages_in']} passages in, {len(claims)} claims, "
            f"{stats['quotes_verified_first_pass']}/{stats['claims_first_pass']} quotes verified "
            f"first pass, {stats['claims_dropped']} dropped, {stats['batches_failed']} batches "
            "failed"
        )
    else:
        claims = pd.read_parquet(out / "claims.parquet")
        review = _read_json(work / "review_extract.json", [])
        stats = _read_json(work / "stats_extract.json", {})

    if "pairs" in stages and not stats.get("budget_exceeded"):
        vecs = pairs_mod.embed_claims(claims, pairs_mod.embedder(cfg))
        pairs, more, pstats = pairs_mod.run(claims, ctx, llm, cfg, vecs=vecs)
        pairs.to_parquet(out / "pairs.parquet", index=False)
        _write_json(work / "review_pairs.json", more)
        _write_json(work / "stats_pairs.json", pstats)
        ok = ok and pstats["judge_batches_failed"] == 0 and not pstats["budget_exceeded"]
        print(
            f"[{docket}] pairs: {pstats['pairs_proposed']} proposed, {pstats['pairs_judged']} "
            f"judged, verdicts {pstats['verdicts']}"
        )
    elif (out / "pairs.parquet").exists():
        pairs = pd.read_parquet(out / "pairs.parquet")
        more, pstats = _read_json(work / "review_pairs.json", []), _read_json(
            work / "stats_pairs.json", {}
        )
    else:
        pairs = pd.DataFrame(columns=pairs_mod.PAIR_COLUMNS)
        more, pstats = [], {}
    review += more
    stats.update(pstats)

    if "issues" in stages:
        if vecs is None:
            vecs = pairs_mod.embed_claims(claims, pairs_mod.embedder(cfg))
        issues, claim_issues, more, istats = issues_mod.run(
            claims, pairs, data.campaigns, vecs, cfg, docket, llm=llm
        )
        issues.to_parquet(out / "issues.parquet", index=False)
        claim_issues.to_parquet(out / "claim_issues.parquet", index=False)
        _write_json(work / "review_issues.json", more)
        _write_json(work / "stats_issues.json", istats)
        print(
            f"[{docket}] issues: {istats['issues']} issues ({istats['issues_multi_claim']} with "
            f"more than one claim), {istats['flagged']} flagged significant, "
            f"{istats['contested_merges']} contested merges"
        )
    else:
        issues = pd.read_parquet(out / "issues.parquet")
        claim_issues = pd.read_parquet(out / "claim_issues.parquet")
        more, istats = _read_json(work / "review_issues.json", []), _read_json(
            work / "stats_issues.json", {}
        )
    review += more
    stats.update(istats)

    summary = export.run(
        out, docket, data.paths, data.letters, data.campaigns, claims, issues, claim_issues, review,
        stats, llm.rows(), cfg, llm.backend.name, ctx, ctx_source, time.time() - t0,
    )  # fmt: skip
    print(
        f"[{docket}] {summary['claims']} claims, {summary['issues']} issues, {summary['flagged']} "
        f"flagged, {summary['review_rows']} review rows, {summary['calls_by_step']} calls, "
        f"${summary['usd_total']:.2f}"
    )
    return ok


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = sys.argv[1:] if argv is None else argv
    stage = argv[0] if argv else "all"
    if stage not in ("all", *STAGES):
        print(f"usage: main.py [all|{'|'.join(STAGES)}]", file=sys.stderr)
        return 1
    dockets = [
        d.strip() for d in os.getenv("DOCKET_IDS", "EPA-HQ-OW-2022-0801").split(",") if d.strip()
    ]
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    cfg = Config.from_env()
    code = 0
    for docket in dockets:
        ok = build_docket(docket, data_dir, stage, cfg)
        summary_path = data_dir / "derived" / "graph" / docket / "summary.json"
        summary = _read_json(summary_path, {})
        if summary.get("budget_exceeded"):
            print(f"[{docket}] GRAPH_MAX_USD reached; partial outputs written", file=sys.stderr)
            code = EXIT_BUDGET
        elif not ok and code == 0:
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
