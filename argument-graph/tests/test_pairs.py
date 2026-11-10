"""Candidate pairs, the judge's partition default, union-find and the transitivity flag."""

import numpy as np
import pandas as pd

import issues
import pairs
from backends import FakeBackend
from conftest import DOCKET, FIXTURES, S84, S85, fake_embed, make_cfg
from llm import LLM

CLAIMS = pd.DataFrame(
    {
        "claim_id": ["C000001", "C000002", "C000003", "C000004", "C000005"],
        "docket_id": [DOCKET] * 5,
        "letter_id": ["L1", "L1", "L2", "L1", "L3"],
        "passage_id": ["L1:p000", "L1:p000", "L2:p000", "L1:p001", "L3:p000"],
        "campaign_id": [None, None, "L2", None, "L2"],
        "section_ref": [S84, S84, S84, S85, S85],
        "quote": [
            "We oppose the ten-year replacement deadline in § 141.84(b) as proposed.",
            "Replacing every lead service line in ten years is not feasible for systems with more "
            "than 10,000 lines.",
            "Please require full replacement of all lead pipes within ten years as proposed in "
            "§ 141.84(b).",
            "The inventory in § 141.84(a) and the notice in § 141.85(a) should use the same "
            "reporting form.",
            "§ 141.85(a) notices should be mailed in Spanish as well as English.",
        ],
        "stance": ["oppose", "oppose", "support", "modify", "modify"],
        "ask": [
            "Allow a deferred deadline based on the number of lines a system owns.",
            None,
            "Require full replacement of all lead pipes within ten years.",
            "Use one reporting form for the inventory and the notice.",
            "Mail § 141.85(a) notices in Spanish as well as English.",
        ],
        "evidence_type": [["data", "alternative"], ["feasibility"], [], ["feasibility"], []],
        "needs_review": [False] * 5,
    }
)


def test_candidates_respect_floor_and_k():
    vecs = pairs.embed_claims(CLAIMS, fake_embed)
    cands = pairs.candidates(CLAIMS, vecs, make_cfg())
    got = [(p.pair_id, p.claim_a, p.claim_b, round(p.cosine, 2)) for p in cands.itertuples()]
    assert got == [
        ("P000001", "C000001", "C000003", 0.8),
        ("P000002", "C000001", "C000002", 0.7),
        ("P000003", "C000004", "C000005", 0.65),
    ]
    # A higher floor drops the 141.85 pair; k=1 keeps only each claim's nearest neighbour.
    assert len(pairs.candidates(CLAIMS, vecs, make_cfg(pair_min=0.75))) == 1
    k1 = pairs.candidates(CLAIMS, vecs, make_cfg(pair_k=1))
    assert set(zip(k1["claim_a"], k1["claim_b"], strict=True)) == {
        ("C000001", "C000003"), ("C000001", "C000002"), ("C000004", "C000005")
    }  # fmt: skip
    assert len(pairs.candidates(CLAIMS, vecs, make_cfg(max_pairs=2))) == 2


def test_claim_text_prefers_ask_then_quote():
    rows = list(CLAIMS.itertuples())
    assert pairs.claim_text(rows[0]).startswith("Allow a deferred")
    assert pairs.claim_text(rows[1]).startswith("Replacing every")


def test_missing_pair_defaults_to_different_and_unsure_is_logged(tmp_path):
    cfg = make_cfg()
    backend = FakeBackend(FIXTURES)
    llm = LLM(cfg, tmp_path / "graph", backend=backend)
    judged, review, stats = pairs.run(CLAIMS, {}, llm, cfg)
    assert backend.calls == ["judge_141.84_000", "judge_141.84_000_fix1", "judge_141.85_000"]
    verdicts = dict(zip(judged["pair_id"], judged["verdict"], strict=True))
    assert verdicts == {
        "P000001": "same_issue_opposite_side", "P000002": "different", "P000003": "unsure"
    }  # fmt: skip
    reasons = sorted(r["reason"] for r in review)
    assert reasons == ["judge_unsure", "missing_from_output"]
    assert stats["pairs_proposed"] == 3 and stats["pairs_judged"] == 3
    assert stats["judge_fix_calls"] == 1 and stats["judge_batches_failed"] == 0
    assert set(judged["tag"]) == {"judge_141.84_000", "judge_141.85_000"}


def test_union_find_and_transitivity_flag():
    roots = issues.union_find(["a", "b", "c", "d"], [("a", "b"), ("b", "c")])
    assert roots["a"] == roots["b"] == roots["c"] != roots["d"]
    pairs_df = pd.DataFrame(
        {
            "pair_id": ["P1", "P2", "P3"],
            "claim_a": ["C000001", "C000002", "C000001"],
            "claim_b": ["C000002", "C000003", "C000003"],
            "section_ref": [S84] * 3,
            "cosine": [0.9, 0.8, 0.7],
            "verdict": ["same_ask", "same_ask", "different"],
            "tag": ["t"] * 3,
        }
    )
    campaigns = pd.DataFrame({"campaign_id": ["L2"], "n_letters": [3]})
    vecs = np.eye(5, dtype=np.float32)
    built, edges, review = issues.build(CLAIMS, pairs_df, campaigns, vecs, DOCKET)
    merged = built[built["n_claims"] == 3].iloc[0]
    assert merged["contested_merge"]
    assert [r["reason"] for r in review] == ["contested_merge"]
    assert review[0]["detail"]["pairs_different"] == [["C000001", "C000003"]]
    assert len(built) == 3  # the merged one plus two singletons in 141.85
