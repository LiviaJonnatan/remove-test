"""Issue counts by distinct letters and campaigns, the significance rule, the medoid label."""

import json

import numpy as np
import pandas as pd

import issues
import pairs
from conftest import DOCKET, S84, S85, fake_embed, make_cfg
from test_pairs import CLAIMS

PAIRS = pd.DataFrame(
    {
        "pair_id": ["P000001", "P000002", "P000003"],
        "claim_a": ["C000001", "C000001", "C000004"],
        "claim_b": ["C000003", "C000002", "C000005"],
        "section_ref": [S84, S84, S85],
        "cosine": [0.8, 0.7, 0.65],
        "verdict": ["same_issue_opposite_side", "different", "unsure"],
        "tag": ["judge_141.84_000", "judge_141.84_000", "judge_141.85_000"],
    }
)
CAMPAIGNS = pd.DataFrame(
    {"campaign_id": ["L2"], "representative_letter_id": ["L2"], "n_letters": [3]}
)


def test_counts_significance_and_edges():
    vecs = pairs.embed_claims(CLAIMS, fake_embed)
    built, edges, review, stats = issues.run(CLAIMS, PAIRS, CAMPAIGNS, vecs, make_cfg(), DOCKET)
    assert list(built["issue_id"]) == ["I00001", "I00002", "I00003", "I00004"]
    merged = built.iloc[0]
    assert merged["section_ref"] == S84 and merged["n_claims"] == 2
    # L1 and L2 wrote the two claims; L2 is a campaign of 3 letters.
    assert (merged["n_letters"], merged["n_campaigns"], merged["n_letters_incl_copies"]) == (
        2, 1, 4
    )
    assert json.loads(merged["stances"]) == {"oppose": 1, "support": 1}
    assert merged["significant"] and list(merged["significance_from"]) == ["C000001"]
    assert not merged["contested_merge"] and not merged["giant_issue"]
    singles = built[built["n_claims"] == 1]
    assert list(singles["significant"]) == [False, False, False]
    assert list(singles["n_letters_incl_copies"]) == [1, 1, 3]  # L3 is in the L2 campaign
    how = dict(zip(edges["claim_id"], edges["how"], strict=True))
    assert how == {
        "C000001": "same_issue_opposite_side", "C000003": "same_issue_opposite_side",
        "C000002": "singleton", "C000004": "singleton", "C000005": "singleton",
    }  # fmt: skip
    assert review == []
    assert stats == {
        "issues": 4, "issues_multi_claim": 1, "flagged": 1, "contested_merges": 0,
        "giant_issues": 0, "label_calls": 0,
    }  # fmt: skip


def test_copies_count_each_campaign_letter_once():
    # L2 (the representative) and L3 (a member with its own passage) land in one issue: the
    # campaign of 3 adds its one absent letter, not size - 1 per campaign.
    members = CLAIMS.set_index("claim_id").loc[["C000003", "C000005"]].reset_index()
    assert set(members["letter_id"]) == {"L2", "L3"}
    c = issues.counts(members, {"L2": 3})
    assert (c["n_letters"], c["n_campaigns"], c["n_letters_incl_copies"]) == (2, 1, 3)
    # Every campaign letter present: no copies to add.
    three = pd.concat([members, members.iloc[[0]].assign(letter_id="L4", claim_id="C000009")])
    assert issues.counts(three, {"L2": 3})["n_letters_incl_copies"] == 3
    # A campaign the table does not know keeps the letter count.
    assert issues.counts(members.assign(campaign_id="ZZ"), {})["n_letters_incl_copies"] == 2


def test_label_is_the_medoid_members_ask_or_quote():
    vecs = pairs.embed_claims(CLAIMS, fake_embed)
    built, _, _ = issues.build(CLAIMS, PAIRS, CAMPAIGNS, vecs, DOCKET)
    merged = built.iloc[0]
    # The label is a member's own ask, never a paraphrase.
    member = CLAIMS.set_index("claim_id").loc[merged["label_claim_id"]]
    assert merged["label_claim_id"] in {"C000001", "C000003"}
    assert merged["label"] == member["ask"]
    # A singleton with no ask is labelled by its quote.
    c2 = built[built["label_claim_id"] == "C000002"].iloc[0]
    assert c2["label"].startswith("Replacing every lead service line")


def test_medoid_and_significance_helpers():
    vecs = np.array([[1, 0], [0.7071, 0.7071], [0, 1]], dtype=np.float32)
    assert issues.medoid([0, 1, 2], vecs) == 1
    assert issues.medoid([2], vecs) == 2
    sig, hits = issues.significance(CLAIMS.iloc[[1, 3]])  # feasibility only
    assert (sig, hits) == (False, [])
    sig, hits = issues.significance(CLAIMS.iloc[[0, 1]])
    assert (sig, hits) == (True, ["C000001"])
    assert issues.as_list(np.array(["data"])) == ["data"] and issues.as_list(None) == []


def test_giant_issue_flag_needs_a_section_with_enough_claims():
    many = pd.concat([CLAIMS.iloc[[0]].assign(claim_id=f"C{i:06d}") for i in range(1, 8)])
    many = many.reset_index(drop=True)
    edges = pd.DataFrame(
        {
            "pair_id": [f"P{i}" for i in range(5)],
            "claim_a": [f"C{i:06d}" for i in range(1, 6)],
            "claim_b": [f"C{i:06d}" for i in range(2, 7)],
            "section_ref": [S84] * 5,
            "cosine": [0.9] * 5,
            "verdict": ["same_ask"] * 5,
            "tag": ["t"] * 5,
        }
    )
    vecs = np.ones((7, 2), dtype=np.float32)
    built, _, review = issues.build(many, edges, CAMPAIGNS, vecs, DOCKET)
    assert built.iloc[0]["n_claims"] == 6 and built.iloc[0]["giant_issue"]
    assert [r["reason"] for r in review] == ["giant_issue"]
