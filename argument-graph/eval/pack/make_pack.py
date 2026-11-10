"""Seeded, stratified reader sheets for two readers, from the graph outputs and the eval matches.

Writes eval/pack/out/<sheet>_A.csv and _B.csv (identical content, separate files so each reader
locks their own), plus key.json with the sampled ids. No letter ids, no names: readers see the
quote, the ask, the stance, the evidence types, the issue label and the point text.

Usage: python eval/pack/make_pack.py --graph-dir ../data/derived/graph/EPA-HQ-OW-2022-0801
       [--matches eval/out/pipeline/matches.parquet] [--points eval/out/points.parquet]
       [--out eval/pack/out] [--seed 215]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SIZES = {"claims": 50, "issues": 30, "flagged": 30, "matches": 60, "boundaries": 40}


def stratified(df: pd.DataFrame, by: str, n: int, rng: random.Random) -> pd.DataFrame:
    """About n rows, spread over the strata in proportion, at least one per stratum."""
    if len(df) <= n:
        return df.sample(frac=1, random_state=rng.randint(0, 10**9))
    groups = [g for _, g in df.groupby(by, sort=True)]
    quota = {id(g): max(1, round(n * len(g) / len(df))) for g in groups}
    picked = [
        g.sample(min(len(g), quota[id(g)]), random_state=rng.randint(0, 10**9)) for g in groups
    ]
    out = pd.concat(picked)
    if len(out) > n:  # quota rounding overshoots: trim at random, never by stratum order
        out = out.sample(n, random_state=rng.randint(0, 10**9))
    return out.sample(frac=1, random_state=rng.randint(0, 10**9)).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-dir", required=True)
    ap.add_argument("--matches", default=str(HERE.parent / "out" / "pipeline" / "matches.parquet"))
    ap.add_argument("--points", default=str(HERE.parent / "out" / "points.parquet"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--seed", type=int, default=215)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    g = Path(a.graph_dir)
    claims = pd.read_parquet(g / "claims.parquet")
    issues = pd.read_parquet(g / "issues.parquet")
    claim_issues = pd.read_parquet(g / "claim_issues.parquet")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    key: dict[str, list] = {}

    def write(name: str, df: pd.DataFrame, answer_cols: list[str]) -> None:
        for col in answer_cols + ["seconds", "notes"]:
            df[col] = ""
        for reader in ("A", "B"):
            df.to_csv(out / f"{name}_{reader}.csv", index=False)
        key[name] = df.iloc[:, 0].tolist()

    c = stratified(claims, "section_ref", SIZES["claims"], rng)
    c = c[["claim_id", "section_ref", "quote", "stance", "ask", "evidence_type"]].copy()
    c["evidence_type"] = c["evidence_type"].apply(
        lambda x: ";".join(list(x)) if x is not None else ""
    )
    write("claims", c, ["faithful", "evidence_ok"])

    multi = issues[issues["n_claims"] > 1]
    i = stratified(multi, "section_ref", SIZES["issues"], rng)
    members = claim_issues.merge(claims[["claim_id", "quote", "ask", "stance"]], on="claim_id")
    rows = []
    for iss in i.itertuples():
        ms = members[members["issue_id"] == iss.issue_id]
        rows.append(
            {"issue_id": iss.issue_id, "section_ref": iss.section_ref, "label": iss.label,
             "members": "\n".join(f"{m.claim_id} [{m.stance}] {m.ask or ''} | {m.quote}"
                                  for m in ms.itertuples())}
        )  # fmt: skip
    write("issues", pd.DataFrame(rows), ["clean", "stray"])

    flagged = issues[issues["significant"]].copy()
    flagged["claim_id"] = flagged["significance_from"].apply(
        lambda x: list(x)[0] if len(x) else None
    )
    f = stratified(flagged, "section_ref", SIZES["flagged"], rng)
    f = f.merge(claims[["claim_id", "quote", "evidence_type"]], on="claim_id", how="left")
    f["evidence_type"] = f["evidence_type"].apply(
        lambda x: ";".join(list(x)) if x is not None else ""
    )
    cols = ["issue_id", "claim_id", "section_ref", "label", "quote", "evidence_type"]
    write("flagged", f[cols].copy(),
          ["carries"])  # fmt: skip

    points = pd.read_parquet(a.points)
    if Path(a.matches).exists():
        matches = pd.read_parquet(a.matches).merge(points[["point_id", "text"]], on="point_id")
        matches = matches.merge(issues[["issue_id", "label"]], on="issue_id")
        m = stratified(matches, "block", SIZES["matches"], rng)
        m = m[["point_id", "issue_id", "block", "text", "label", "match"]].rename(
            columns={"text": "point_text", "match": "model_match"}
        )
        m["model_match"] = ""  # blind
        write("matches", m, ["match"])

    b = stratified(points, "block", SIZES["boundaries"], rng)
    write("boundaries", b[["point_id", "block", "text"]].copy(), ["boundary"])

    (out / "key.json").write_text(json.dumps({"seed": a.seed, "ids": key}, indent=1))
    print({k: len(v) for k, v in key.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
