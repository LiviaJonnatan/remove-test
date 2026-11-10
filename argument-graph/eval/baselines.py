"""Issue tables the pipeline has to beat, written in the pipeline's own issues.parquet shape so
match.py and score.py treat them alike.

  B0  passages as issues, no model: one issue per (passage, cited section), labelled by the
      passage text. A passage that cites two sections is an issue under both, since without a
      model nothing can say which one it is about; the pipeline lets the extractor pick among the
      cited sections. Issues equal cited (passage, section) pairs, not passages.
  B1  cosine clustering, no judge: the pipeline's claims and the same bge-small embeddings,
      single-linkage within a section at a cosine threshold swept so the issue count matches the
      pipeline's (so recall is compared at equal compression). Label = medoid claim's ask.
  B2  the 507 positions of the 12 Oct reading pilot (reading.json), section mapped to section_ref.

Usage: python eval/baselines.py --graph-dir ../data/derived/graph/EPA-HQ-OW-2022-0801
       --passages ../data/derived/passages/EPA-HQ-OW-2022-0801
       [--reading /Users/aidane/Harvard/ac215/undersigned2/reading/reading.json]
       [--out eval/out/baselines]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from config import Config  # noqa: E402
from issues import ISSUE_COLUMNS, counts, medoid, significance, union_find  # noqa: E402
from pairs import embed_claims, embedder  # noqa: E402

B0_WORDS = 60


def issue_row(iid: str, docket: str, ref: str, label: str, members: pd.DataFrame,
              campaign_sizes: dict[str, int], label_claim: str | None = None) -> dict:  # fmt: skip
    sig, sig_from = significance(members) if "evidence_type" in members else (False, [])
    return {
        "issue_id": iid, "docket_id": docket, "section_ref": ref, "label": label,
        "label_claim_id": label_claim, **counts(members, campaign_sizes), "significant": sig,
        "significance_from": sig_from, "contested_merge": False, "giant_issue": False,
    }  # fmt: skip


def b0(passages: pd.DataFrame, links: pd.DataFrame, assignments: pd.DataFrame,
       campaigns: pd.DataFrame, docket: str) -> pd.DataFrame:  # fmt: skip
    cited = links[(links["source"] == "citation") & links["section_ref"].notna()]
    pairs = sorted({(r.section_ref, r.passage_id) for r in cited.itertuples()})
    campaign_of = dict(zip(assignments["letter_id"], assignments["campaign_id"], strict=True))
    sizes = dict(zip(campaigns["campaign_id"], campaigns["n_letters"].astype(int), strict=True))
    by_id = passages.set_index("passage_id")
    rows = []
    for n, (ref, pid) in enumerate(pairs, 1):
        if pid not in by_id.index:
            continue
        p = by_id.loc[pid]
        members = pd.DataFrame(
            {"claim_id": [pid], "letter_id": [p["letter_id"]],
             "campaign_id": [campaign_of.get(p["letter_id"])], "stance": ["other"]}
        )  # fmt: skip
        label = " ".join(str(p["text"]).split()[:B0_WORDS])
        rows.append(issue_row(f"B0-{n:05d}", docket, ref, label, members, sizes))
    return pd.DataFrame(rows, columns=ISSUE_COLUMNS)


def b1_at(claims: pd.DataFrame, vecs: np.ndarray, threshold: float, campaigns: pd.DataFrame,
          docket: str) -> pd.DataFrame:  # fmt: skip
    """Single-linkage components within a section at a cosine threshold."""
    edges = []
    ids = claims["claim_id"].to_numpy()
    for _ref, idx in claims.groupby("section_ref").indices.items():
        sub = vecs[idx]
        cos = sub @ sub.T
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                if cos[i, j] >= threshold:
                    edges.append((ids[idx[i]], ids[idx[j]]))
    roots = union_find(list(ids), edges)
    sizes = dict(zip(campaigns["campaign_id"], campaigns["n_letters"].astype(int), strict=True))
    by_root: dict[str, list[int]] = {}
    for i, cid in enumerate(ids):
        by_root.setdefault(roots[cid], []).append(i)
    rows = []
    ordered = sorted(by_root.items(), key=lambda kv: (claims.iloc[kv[1][0]]["section_ref"], kv[0]))
    for n, (_root, idx) in enumerate(ordered, 1):
        members = claims.iloc[idx]
        m = claims.iloc[medoid(idx, vecs)]
        label = m["ask"] if isinstance(m["ask"], str) and m["ask"] else m["quote"]
        rows.append(
            issue_row(
                f"B1-{n:05d}",
                docket,
                members.iloc[0]["section_ref"],
                label,
                members,
                sizes,
                m["claim_id"],
            )  # fmt: skip
        )
    return pd.DataFrame(rows, columns=ISSUE_COLUMNS)


def b1(claims: pd.DataFrame, vecs: np.ndarray, target_issues: int, campaigns: pd.DataFrame,
       docket: str) -> tuple[pd.DataFrame, float]:  # fmt: skip
    """Sweep the threshold until the issue count is nearest the pipeline's."""
    best, best_t = None, None
    for t in np.arange(0.50, 0.96, 0.01):
        table = b1_at(claims, vecs, float(t), campaigns, docket)
        if best is None or abs(len(table) - target_issues) < abs(len(best) - target_issues):
            best, best_t = table, float(t)
    return best, best_t


def b2(reading: dict, docket: str) -> pd.DataFrame:
    rows = []
    for p in reading["positions"]:
        # One row per member ask; the ask's organisation stands in for the letter id.
        asks = reading.get("asks", {})
        ids = list(p["members"]) or [p["id"]]
        orgs = [str((asks.get(i) or {}).get("org", "?")) for i in ids]
        members = pd.DataFrame(
            {"claim_id": ids, "letter_id": orgs, "campaign_id": [None] * len(ids),
             "stance": ["other"] * len(ids)}
        )  # fmt: skip
        rows.append(
            issue_row(
                f"B2-{p['id']}", docket, f"PART {p['section'].split('.')[0]}/§ {p['section']}",
                p["statement"], members, {},
            )  # fmt: skip
        )
    return pd.DataFrame(rows, columns=ISSUE_COLUMNS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-dir", required=True)
    ap.add_argument("--passages", required=True, help="data/derived/passages/<docket>")
    ap.add_argument("--campaigns", default=None, help="data/derived/campaigns/<docket>")
    ap.add_argument("--reading", default=None, help="12 Oct reading.json for B2")
    ap.add_argument("--out", default=str(HERE / "out" / "baselines"))
    a = ap.parse_args()
    graph_dir, passages_dir = Path(a.graph_dir), Path(a.passages)
    campaigns_dir = (
        Path(a.campaigns)
        if a.campaigns
        else passages_dir.parent.parent / "campaigns" / passages_dir.name
    )
    summary = json.loads((graph_dir / "summary.json").read_text())
    docket = summary["docket_id"]
    claims = pd.read_parquet(graph_dir / "claims.parquet")
    passages = pd.read_parquet(passages_dir / "passages.parquet")
    links = pd.read_parquet(passages_dir / "links.parquet")
    assignments = pd.read_parquet(campaigns_dir / "assignments.parquet")
    campaigns = pd.read_parquet(campaigns_dir / "campaigns.parquet")
    out = Path(a.out)
    report = {}

    t0 = b0(passages, links, assignments, campaigns, docket)
    (out / "B0").mkdir(parents=True, exist_ok=True)
    t0.to_parquet(out / "B0" / "issues.parquet", index=False)
    report["B0"] = {"issues": len(t0), "passages": summary["passages_extracted"],
                    "compression": round(len(t0) / summary["passages_extracted"], 4)}  # fmt: skip

    vecs = embed_claims(claims, embedder(Config.from_env()))
    t1, thr = b1(claims, vecs, summary["issues"], campaigns, docket)
    (out / "B1").mkdir(parents=True, exist_ok=True)
    t1.to_parquet(out / "B1" / "issues.parquet", index=False)
    report["B1"] = {"issues": len(t1), "threshold": thr, "pipeline_issues": summary["issues"],
                    "compression": round(len(t1) / len(claims), 4) if len(claims) else None,
                    }  # fmt: skip

    if a.reading:
        t2 = b2(json.loads(Path(a.reading).read_text()), docket)
        (out / "B2").mkdir(parents=True, exist_ok=True)
        t2.to_parquet(out / "B2" / "issues.parquet", index=False)
        report["B2"] = {"issues": len(t2), "source": a.reading}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
