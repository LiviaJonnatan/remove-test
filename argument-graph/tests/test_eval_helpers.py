"""Eval helpers that carry numbers into the pilot: candidate widening, reuse of verdicts, the
block bootstrap, the paired difference, review load under both definitions, random trimming."""

import random
from types import SimpleNamespace

import numpy as np
import pandas as pd

import match
import score
from pack import make_pack

S84 = "PART 141/§ 141.84"
S85 = "PART 141/§ 141.85"


def test_catch_all_and_unmapped_points_see_every_section():
    issues = pd.DataFrame({"issue_id": ["I1", "I2", "I3"], "section_ref": [S84, S85, S85]})
    ivecs = np.array([[1, 0], [0, 1], [0.6, 0.8]], dtype=np.float32)
    pvec = np.array([0, 1], dtype=np.float32)
    masked = SimpleNamespace(section_refs=[S84], catch_all=False)
    assert [i for i, _ in match.candidates_for(masked, issues, ivecs, pvec, 3)] == ["I1"]
    wide = SimpleNamespace(section_refs=[S84], catch_all=True)
    assert [i for i, _ in match.candidates_for(wide, issues, ivecs, pvec, 3)] == ["I2", "I3", "I1"]
    unmapped = SimpleNamespace(section_refs=[], catch_all=False)
    assert len(match.candidates_for(unmapped, issues, ivecs, pvec, 2)) == 2


def test_reuse_keeps_verdicts_only_for_unchanged_candidate_lists():
    prev = pd.DataFrame(
        {"point_id": ["P1", "P1", "P2", "P2"], "issue_id": ["I1", "I2", "I1", "I2"],
         "rank": [1, 2, 1, 2], "match": [True, False, None, False]}
    )  # fmt: skip
    rows = match.reusable(prev, "P1", [("I1", 0.9), ("I2", 0.8)])
    assert [r["match"] for r in rows] == [True, False]
    assert match.reusable(prev, "P1", [("I2", 0.9), ("I1", 0.8)]) is None  # order changed
    assert match.reusable(prev, "P1", [("I1", 0.9)]) is None  # fewer candidates
    assert match.reusable(prev, "P2", [("I1", 0.9), ("I2", 0.8)]) is None  # unanswered
    assert match.reusable(None, "P1", [("I1", 0.9)]) is None
    b = [(SimpleNamespace(point_id="P1"), []), (SimpleNamespace(point_id="P2"), [])]
    assert match.batch_tag("B1", b) == match.batch_tag("B1", b)
    assert match.batch_tag("B1", b) != match.batch_tag("B1", b[::-1])


def points_and_matches():
    points = pd.DataFrame(
        {"point_id": ["A1", "A2", "B1", "B2", "C1"], "block": ["A", "A", "B", "B", "C"],
         "catch_all": [False, False, False, False, True],
         "has_explicit_response": [True, False, True, True, False]}
    )  # fmt: skip
    matches = pd.DataFrame(
        {"point_id": ["A1", "A1", "A2", "B1", "C1"], "issue_id": ["I1", "I2", "I3", "I4", "I5"],
         "rank": [1, 3, 1, 1, 1], "match": [False, True, False, True, True]}
    )  # fmt: skip
    return points, matches


def test_recall_tables_name_the_metrics_by_what_they_count():
    points, matches = points_and_matches()
    rng = np.random.default_rng(0)
    draws = score.block_draws(["A", "B", "C"], rng, 200)
    t = score.recall_tables(points, matches, draws)
    assert t["all"] == {
        "points": 4, "top3": 0.5, "top2": 0.25,
        "top3_ci95": t["all"]["top3_ci95"], "top2_ci95": t["all"]["top2_ci95"],
    }  # fmt: skip
    assert t["catch_all"]["top3"] == 1.0 and t["catch_all"]["points"] == 1
    assert (t["block_recall"], t["blocks"], t["blocks_hit"], t["points_hit"]) == (1.0, 3, 3, 3)
    lo, hi = t["all"]["top3_ci95"]
    assert lo <= 0.5 <= hi  # the interval holds its own point estimate
    # A draw is a ratio over whole blocks: with A (1 of 2) and B (1 of 2) it is 0.5, and a draw
    # of C alone (a catch-all block, no regular points) is left out of the percentile as NaN.
    assert np.nanmax(t["_draws"]["top3"]) == 0.5 and np.isnan(t["_draws"]["top3"]).any()


def test_paired_difference_against_the_pipeline():
    points, matches = points_and_matches()
    other = matches.assign(match=[True, True, True, False, True])  # A1 twice, A2; B1 lost
    draws = score.block_draws(["A", "B", "C"], np.random.default_rng(1), 100)
    base = score.recall_tables(points, matches, draws)
    oth = score.recall_tables(points, other, draws)
    p = score.paired(points, base, oth)
    assert (p["both"], p["only_pipeline"], p["only_other"], p["neither"]) == (1, 1, 1, 1)
    assert p["top3_diff"] == 0.0 and len(p["top3_diff_ci95"]) == 2


def test_review_load_under_both_definitions():
    claims = pd.DataFrame({"claim_id": [f"C{i}" for i in range(10)]})
    review = pd.DataFrame(
        {"claim_id": ["C1", "C1", "C2", None], "reason": ["a", "b", "a", "contested_merge"]}
    )
    rl = score.review_load(review, claims, {"review_rows_by_reason": {}})
    assert (rl["rows"], rl["share_rows"], rl["fails_20pct_rows"]) == (4, 0.4, True)
    assert (rl["claims_distinct"], rl["share_claims"], rl["fails_20pct_claims"]) == (2, 0.2, False)
    assert (rl["claims_with_two_rows"], rl["issue_rows"]) == (1, 1)


def test_stratified_trim_is_random_not_by_stratum_order():
    df = pd.DataFrame({"id": range(100), "s": ["a"] * 50 + ["b"] * 30 + ["c"] * 15 + ["d"] * 5})
    strata_hit = set()
    for seed in range(20):
        out = make_pack.stratified(df, "s", 12, random.Random(seed))
        assert len(out) == 12
        strata_hit |= set(out["s"])
    assert strata_hit == {"a", "b", "c", "d"}  # the last stratum is not always the one cut
