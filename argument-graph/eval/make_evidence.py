"""Copy what a run produced into docs/evidence/argument-graph/, with one claim followed end to end.

Writes README.md, run.log (copied from --log), summary.json, ledger-excerpt.jsonl (every row, the
prompts and raw answers stay out of git), results.md when eval/out/results.md exists, and
one-claim-end-to-end.md: one passage through its claims, the pairs the judge saw, the issue it
landed in and, when matches exist, the preamble point it answers. Letter ids are regulations.gov
document ids, which carry no personal details; letter text other than the stored quotes is not
copied.

Usage: python eval/make_evidence.py --graph-dir <folder> --log <run.log> [--label "S1 smoke"]
       [--claim C000003] [--out ../docs/evidence/argument-graph] [--inputs-note "..."]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def git_commit(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True,
                              ).stdout.strip()  # fmt: skip
    except Exception:
        return "unknown"


def one_claim(g: Path, claim_id: str | None, matches: Path | None) -> str:
    claims = pd.read_parquet(g / "claims.parquet")
    pairs = pd.read_parquet(g / "pairs.parquet") if (g / "pairs.parquet").exists() else None
    issues = pd.read_parquet(g / "issues.parquet")
    claim_issues = pd.read_parquet(g / "claim_issues.parquet")
    if claim_id is None:
        multi = claim_issues.merge(issues[issues["n_claims"] > 1][["issue_id"]], on="issue_id")
        claim_id = multi["claim_id"].iloc[0] if len(multi) else claims["claim_id"].iloc[0]
    c = claims.set_index("claim_id").loc[claim_id]
    same_passage = claims[claims["passage_id"] == c["passage_id"]]
    lines = [f"# One passage end to end: `{c['passage_id']}`", "",
             f"Letter `{c['letter_id']}`, cited section `{c['section_ref']}` "
             f"(section_source `{c['section_source']}`), campaign `{c['campaign_id']}`.", "",
             "## Claims the extractor returned for this passage", "",
             "| claim | stance | ask | evidence | quote (verified) |",
             "|---|---|---|---|---|"]  # fmt: skip
    for r in same_passage.itertuples():
        ev = ";".join(list(r.evidence_type)) if r.evidence_type is not None else ""
        lines.append(f"| {r.claim_id} | {r.stance} | {r.ask or ''} | {ev} | "
                     f"{(r.quote or '').replace('|', '/')} ({r.quote_verified}) |")  # fmt: skip
    if pairs is not None:
        mine = pairs[(pairs["claim_a"] == claim_id) | (pairs["claim_b"] == claim_id)]
        lines += ["", f"## Pairs the judge saw for `{claim_id}`", "",
                  "| pair | other claim | cosine | verdict |", "|---|---|---|---|"]  # fmt: skip
        for p in mine.itertuples():
            other = p.claim_b if p.claim_a == claim_id else p.claim_a
            lines.append(f"| {p.pair_id} | {other} | {p.cosine:.3f} | {p.verdict} |")
        if mine.empty:
            lines.append("| (none above the cosine floor) | | | |")
    iid = claim_issues.set_index("claim_id").loc[claim_id, "issue_id"]
    iss = issues.set_index("issue_id").loc[iid]
    lines += ["", f"## Issue `{iid}`", "",
              f"- label (medoid claim `{iss['label_claim_id']}`): {iss['label']}",
              f"- claims {iss['n_claims']}, letters {iss['n_letters']}, campaigns "
              f"{iss['n_campaigns']}, letters incl. copies {iss['n_letters_incl_copies']}",
              f"- stances {iss['stances']}; significant {iss['significant']} "
              f"(from {list(iss['significance_from'])}); "
              f"contested {iss['contested_merge']}"]  # fmt: skip
    if matches is not None and matches.exists():
        m = pd.read_parquet(matches)
        hit = m[(m["issue_id"] == iid) & (m["match"] == True)]  # noqa: E712
        points = pd.read_parquet(HERE / "out" / "points.parquet").set_index("point_id")
        lines += ["", "## Preamble points this issue answers", ""]
        for h in hit.itertuples():
            lines.append(f"- `{h.point_id}` ({h.block}): {points.loc[h.point_id, 'text']}")
        if hit.empty:
            lines.append("- none matched")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-dir", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--claim", default=None)
    ap.add_argument("--inputs-note", default="")
    ap.add_argument("--matches", default=str(HERE / "out" / "pipeline" / "matches.parquet"))
    ap.add_argument("--out", default=str(HERE.parents[1] / "docs" / "evidence" / "argument-graph"))
    a = ap.parse_args()
    g, out = Path(a.graph_dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(a.log, out / "run.log")
    shutil.copy(g / "summary.json", out / "summary.json")
    shutil.copy(g / "ledger.jsonl", out / "ledger-excerpt.jsonl")
    results = HERE / "out" / "results.md"
    if results.exists():
        shutil.copy(results, out / "results.md")
    (out / "one-claim-end-to-end.md").write_text(one_claim(g, a.claim, Path(a.matches)))
    s = json.loads((g / "summary.json").read_text())
    commit = git_commit(HERE.parents[1])
    readme = f"""# Evidence: argument-graph ({a.label})

Date {time.strftime("%Y-%m-%d")}, laptop, commit `{commit}`, backend `{s["backend"]}`, model
`{s["model_id"]}`. {a.inputs_note}

| File | What it shows |
|---|---|
| `run.log` | The stage's own log lines for this run |
| `summary.json` | Counts, cost by step, token totals, prompt hash, input checksums |
| `ledger-excerpt.jsonl` | One row per model call: tag, tokens, seconds, USD as reported |
| `one-claim-end-to-end.md` | One passage through claims, pair verdicts and its issue, real ids |
{"| `results.md` | Eval tables from eval/score.py |" if results.exists() else ""}

Run: {s["passages_in"]} passages in, {s["passages_extracted"]} extracted, {s["claims"]} claims
({s["quotes_verified_first_pass"]}/{s["claims_first_pass"]} quotes verified first pass,
{s["claims_dropped"]} dropped), {s["issues"]} issues ({s["issues_multi_claim"]} with more than one
claim), {s["flagged"]} flagged significant, {s["review_rows"]} review rows.
Calls {s["calls_by_step"]},
USD {s["usd_total"]} ({s["cache_read_tokens"]} cache-read tokens, {s["cache_write_tokens"]}
cache-write, {s["output_tokens"]} output), wall clock {s["wall_clock_s"]} s.

## Reproduce

```bash
cd argument-graph
GRAPH_BACKEND={s["backend"]} GRAPH_MODEL=fable DATA_DIR=../data DOCKET_IDS={s["docket_id"]} \\
  PYTHONPATH=../rule-passages/src uv run python src/main.py all
python eval/make_evidence.py --graph-dir ../data/derived/graph/{s["docket_id"]} --log run.log
```

## What this does not show

The prompts and raw answers (`prompts/`, `raw/`) hold letter text and stay in `data/derived/`,
which is not in git. Eval numbers appear only once `eval/match.py` and `eval/score.py` have run.
"""
    (out / "README.md").write_text(readme)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
