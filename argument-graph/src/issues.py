"""Issues: the claims of a section grouped by the judge's verdicts, counted by distinct letters.

Union-find over same_ask and same_issue_opposite_side edges. A singleton is an issue too. The label
is the ask (or quote) of the member nearest the embedding centroid, so the analyst reads a real
commenter's words beside the medoid quote. GRAPH_LABEL_ISSUES=1 adds one model call per section
that writes a neutral label instead.

Counts: n_letters is distinct letter_id among members; n_campaigns distinct non-null campaign_id;
n_letters_incl_copies adds, for each campaign present, the campaign's letters that are not already
among the members' distinct letters, so a form letter sent 5,000 times counts once in n_letters and
5,000 times in n_letters_incl_copies, and a campaign reaching an issue through two of its own
letters is not counted twice. Both are shown.

Significance is a rule on the extractor's evidence_type, not a third model: an issue is significant
when any member carries data, legal or alternative, the three kinds of comment an agency has to
answer on the record. significance_from lists those claims so the rule can be audited.

Review rows: contested_merge (a component that also holds a pair judged different), giant_issue (a
component with more than 40% of a section's claims, kept as is).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import Config, short_ref
from llm import LLM, BudgetExceeded, CallFailed
from pairs import EDGE_VERDICTS
from templates import prompt, render, schema

ISSUE_COLUMNS = [
    "issue_id", "docket_id", "section_ref", "label", "label_claim_id", "n_claims", "n_letters",
    "n_campaigns", "n_letters_incl_copies", "stances", "significant", "significance_from",
    "contested_merge", "giant_issue",
]  # fmt: skip
SIGNIFICANT = {"data", "legal", "alternative"}
GIANT_SHARE = 0.40
GIANT_MIN_CLAIMS = 5  # a section with fewer claims cannot have a meaningful giant


def union_find(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, str]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return {i: find(i) for i in ids}


def medoid(idx: list[int], vecs: np.ndarray) -> int:
    """Row index of the member nearest the centroid."""
    if len(idx) == 1:
        return idx[0]
    sub = vecs[idx]
    centroid = sub.mean(axis=0)
    return idx[int(np.argmax(sub @ centroid))]


def as_list(x) -> list:
    """A parquet list column comes back as a numpy array; None for a null."""
    if x is None:
        return []
    return list(x)


def significance(members: pd.DataFrame) -> tuple[bool, list[str]]:
    hits = [r.claim_id for r in members.itertuples() if set(as_list(r.evidence_type)) & SIGNIFICANT]
    return bool(hits), hits


def counts(members: pd.DataFrame, campaign_sizes: dict[str, int]) -> dict:
    letters = members["letter_id"].nunique()
    in_campaign = members[members["campaign_id"].apply(lambda c: isinstance(c, str) and c != "")]
    present = in_campaign.groupby("campaign_id")["letter_id"].nunique().to_dict()
    copies = sum(max(campaign_sizes.get(c, 1) - seen, 0) for c, seen in present.items())
    return {
        "n_claims": int(len(members)),
        "n_letters": int(letters),
        "n_campaigns": len(present),
        "n_letters_incl_copies": int(letters + copies),
        "stances": json.dumps(
            {k: int(v) for k, v in members["stance"].value_counts().sort_index().items()}
        ),
    }


def build(
    claims: pd.DataFrame, pairs: pd.DataFrame, campaigns: pd.DataFrame, vecs: np.ndarray,
    docket: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:  # fmt: skip
    judged = pairs[pairs["verdict"].notna()] if "verdict" in pairs else pairs.iloc[0:0]
    edges = [
        (p.claim_a, p.claim_b) for p in judged.itertuples() if p.verdict in EDGE_VERDICTS
    ]
    roots = union_find(list(claims["claim_id"]), edges)
    campaign_sizes = dict(
        zip(campaigns["campaign_id"], campaigns["n_letters"].astype(int), strict=True)
    )
    by_root: dict[str, list[int]] = {}
    for i, cid in enumerate(claims["claim_id"]):
        by_root.setdefault(roots[cid], []).append(i)
    # Which verdict joined each claim to its component.
    how: dict[str, str] = {}
    for p in judged.itertuples():
        if p.verdict == "same_ask":
            how[p.claim_a] = how[p.claim_b] = "same_ask"
        elif p.verdict == "same_issue_opposite_side":
            how.setdefault(p.claim_a, "same_issue_opposite_side")
            how.setdefault(p.claim_b, "same_issue_opposite_side")
    different = {(p.claim_a, p.claim_b) for p in judged.itertuples() if p.verdict == "different"}
    section_size = claims.groupby("section_ref").size().to_dict()

    issues, claim_issues, review = [], [], []
    ordered = sorted(by_root.items(), key=lambda kv: (claims.iloc[kv[1][0]]["section_ref"], kv[0]))
    for n, (_root, idx) in enumerate(ordered, start=1):
        iid = f"I{n:05d}"
        members = claims.iloc[idx]
        ids = set(members["claim_id"])
        m = medoid(idx, vecs)
        label_row = claims.iloc[m]
        label = label_row["ask"] if isinstance(label_row["ask"], str) and label_row["ask"] else (
            label_row["quote"]
        )
        sig, sig_from = significance(members)
        contested = any(a in ids and b in ids for a, b in different)
        ref = members.iloc[0]["section_ref"]
        giant = (
            section_size[ref] >= GIANT_MIN_CLAIMS and len(idx) > GIANT_SHARE * section_size[ref]
        )
        issues.append(
            {
                "issue_id": iid,
                "docket_id": docket,
                "section_ref": ref,
                "label": label,
                "label_claim_id": label_row["claim_id"],
                **counts(members, campaign_sizes),
                "significant": sig,
                "significance_from": sig_from,
                "contested_merge": contested,
                "giant_issue": bool(giant),
            }
        )
        for cid in members["claim_id"]:
            claim_issues.append(
                {"claim_id": cid, "issue_id": iid,
                 "how": "singleton" if len(idx) == 1 else how.get(cid, "same_ask")}
            )  # fmt: skip
        if contested:
            review.append(
                {"claim_id": None, "issue_id": iid, "reason": "contested_merge",
                 "detail": {"n_claims": len(idx), "pairs_different": [
                     [a, b] for a, b in different if a in ids and b in ids]}}
            )  # fmt: skip
        if giant:
            review.append(
                {"claim_id": None, "issue_id": iid, "reason": "giant_issue",
                 "detail": {"n_claims": len(idx), "section_claims": int(section_size[ref])}}
            )  # fmt: skip
    return (
        pd.DataFrame(issues, columns=ISSUE_COLUMNS),
        pd.DataFrame(claim_issues, columns=["claim_id", "issue_id", "how"]),
        review,
    )


def label_with_model(
    issues: pd.DataFrame, claims: pd.DataFrame, claim_issues: pd.DataFrame, llm: LLM
) -> tuple[pd.DataFrame, list[dict], int]:
    """Optional: one call per section rewriting multi-claim issue labels. Flag-gated."""
    system = prompt("system")
    members_of = claim_issues.groupby("issue_id")["claim_id"].agg(list).to_dict()
    by_claim = claims.set_index("claim_id")
    review, calls = [], 0
    for ref, group in issues.groupby("section_ref"):
        multi = group[group["n_claims"] > 1]
        if multi.empty:
            continue
        blocks = []
        for iss in multi.itertuples():
            lines = [f"=== ISSUE {iss.issue_id} ==="]
            for cid in members_of[iss.issue_id]:
                c = by_claim.loc[cid]
                lines.append(f"- stance={c['stance']} ask={c['ask']}\n  quote: {c['quote']}")
            blocks.append("\n".join(lines))
        user = render(prompt("label"), section_ref=short_ref(ref), groups="\n\n".join(blocks))
        calls += 1
        try:
            out = llm.call(f"label_{short_ref(ref)}", "label", system, "", user, schema("label"))
        except (CallFailed, BudgetExceeded) as e:
            review.append(
                {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                 "detail": {"tag": f"label_{short_ref(ref)}", "error": str(e)[:300]}}
            )  # fmt: skip
            continue
        labels = {x["issue_id"]: x["label"] for x in out["labels"]}
        mask = issues["issue_id"].isin(labels)
        issues.loc[mask, "label"] = issues.loc[mask, "issue_id"].map(labels)
    return issues, review, calls


def run(
    claims: pd.DataFrame, pairs: pd.DataFrame, campaigns: pd.DataFrame, vecs: np.ndarray,
    cfg: Config, docket: str, llm: LLM | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict], dict]:  # fmt: skip
    issues, claim_issues, review = build(claims, pairs, campaigns, vecs, docket)
    label_calls = 0
    if cfg.label_issues and llm is not None:
        issues, more, label_calls = label_with_model(issues, claims, claim_issues, llm)
        review += more
    stats = {
        "issues": int(len(issues)),
        "issues_multi_claim": int((issues["n_claims"] > 1).sum()),
        "flagged": int(issues["significant"].sum()),
        "contested_merges": int(issues["contested_merge"].sum()),
        "giant_issues": int(issues["giant_issue"].sum()),
        "label_calls": label_calls,
    }
    return issues, claim_issues, review, stats
