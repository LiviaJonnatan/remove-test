"""The extractor's harness: partition re-ask, quote re-ask, drops, section disagreement."""

import pandas as pd

import extract
import inputs
from backends import FakeBackend
from conftest import DOCKET, FIXTURES, LETTERS, S84, S85, make_cfg, write_inputs
from llm import LLM


def run_extract(tmp_path):
    write_inputs(tmp_path)
    data = inputs.load(DOCKET, tmp_path)
    cfg = make_cfg()
    selected = inputs.select(data, cfg, section_order=[S84, S85])
    backend = FakeBackend(FIXTURES)
    llm = LLM(cfg, tmp_path / "graph", backend=backend)
    claims, review, stats = extract.run(selected, LETTERS, {}, llm, cfg, DOCKET)
    return claims, review, stats, backend


def test_batches_group_by_primary_section(data_dir):
    data = inputs.load(DOCKET, data_dir)
    selected = inputs.select(data, make_cfg(), section_order=[S84, S85])
    work = extract.batches(selected, 12)
    assert [(b.tag, list(b.passages["passage_id"])) for b in work] == [
        ("extract_141.84_000", ["L1:p000", "L1:p001", "L2:p000"]),
        ("extract_141.85_000", ["L3:p000"]),
    ]
    assert extract.batches(selected, 2)[1].tag == "extract_141.84_001"


def test_partition_check_and_section_resolution():
    assert extract.partition_check(["a", "b"], {"passages": [{"passage_id": "a"}]}) == (
        ["b"], [], []
    )
    assert extract.partition_check(
        ["a"], {"passages": [{"passage_id": "a"}, {"passage_id": "a"}, {"passage_id": "z"}]}
    ) == ([], ["a"], ["z"])
    assert extract.resolve_section(S85, [S84, S85]) == (S85, None)
    assert extract.resolve_section("141.85", [S84, S85]) == (S85, None)
    assert extract.resolve_section("none", [S84]) == (S84, "no_section")
    assert extract.resolve_section(S85, [S84]) == (S84, "section_disagrees")


def test_reask_requote_drop_and_disagreement(tmp_path):
    claims, review, stats, backend = run_extract(tmp_path)
    # A missing passage id triggered the fix call; bad quotes triggered one requote per batch.
    assert backend.calls == [
        "extract_141.84_000", "extract_141.84_000_fix1", "requote_141.84_000",
        "extract_141.85_000",
    ]  # fmt: skip
    reasons = sorted(r["reason"] for r in review)
    assert reasons == ["quote_failed", "section_disagrees"]
    # 6 claims came back, 2 quotes failed, the requote fixed one, the other was dropped.
    assert stats["claims_first_pass"] == 6
    assert stats["quotes_verified_first_pass"] == 4
    assert stats["quotes_verified_final"] == 5
    assert stats["claims_dropped"] == 1
    assert stats["requote_calls"] == 1 and stats["fix_calls"] == 1
    assert stats["passages_in"] == 4 and stats["passages_extracted"] == 4

    assert list(claims["claim_id"]) == [f"C{i:06d}" for i in range(1, 6)]
    by_id = claims.set_index("claim_id")
    fixed = by_id.loc["C000002"]
    assert fixed["quote"].startswith("Replacing every lead service line")
    assert fixed["quote_verified"] and fixed["quote_source"] == "passage"
    assert pd.isna(fixed["ask"]) and list(fixed["evidence_type"]) == ["feasibility"]
    dropped = next(r for r in review if r["reason"] == "quote_failed")
    assert dropped["detail"]["quote"].startswith("Our utility replaced only")

    # The model put L2:p000 under 141.85; the letter cites 141.84, so the citation stands.
    l2 = claims[claims["passage_id"] == "L2:p000"].iloc[0]
    assert l2["section_ref"] == S84 and l2["model_section_ref"] == S85
    disagree = next(r for r in review if r["reason"] == "section_disagrees")
    assert disagree["claim_id"] == l2["claim_id"]
    # A short-form answer that names a cited candidate is accepted.
    l1b = claims[claims["passage_id"] == "L1:p001"].iloc[0]
    assert l1b["section_ref"] == S85
    assert not claims["needs_review"].any()
    assert claims["prompt_sha1"].nunique() == 1


def test_llm_failure_marks_the_batch(tmp_path, failing_fixtures):
    write_inputs(tmp_path)
    data = inputs.load(DOCKET, tmp_path)
    cfg = make_cfg(fixtures=failing_fixtures)
    selected = inputs.select(data, cfg, section_order=[S84, S85])
    llm = LLM(cfg, tmp_path / "graph", backend=FakeBackend(failing_fixtures))
    claims, review, stats = extract.run(selected, LETTERS, {}, llm, cfg, DOCKET)
    failed = [r for r in review if r["reason"] == "llm_failed"]
    assert sorted(r["detail"]["passage_id"] for r in failed) == ["L1:p000", "L1:p001", "L2:p000"]
    assert stats["batches_failed"] == 1 and stats["passages_extracted"] == 1
    assert list(claims["passage_id"]) == ["L3:p000"]
