"""The stage end to end on the fake backend: files, counts that reconcile, exit codes."""

import json

import main as m
from conftest import DOCKET, FIXTURES, S84, S85, fake_embed, make_cfg, read_outputs, write_inputs


def test_no_backend_skips_with_exit_zero(data_dir, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DOCKET_IDS", DOCKET)
    monkeypatch.setenv("GRAPH_BACKEND", "none")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert m.main([]) == 0
    assert "no LLM backend" in capsys.readouterr().out
    assert not (data_dir / "derived" / "graph" / DOCKET / "summary.json").exists()


def test_full_fake_run_writes_every_table(data_dir):
    assert m.build_docket(DOCKET, data_dir, "all", make_cfg()) is True
    out = read_outputs(data_dir)
    assert set(out) >= {"claims", "pairs", "issues", "claim_issues", "review", "summary", "graph"}
    s = out["summary"]
    # Reconciles with passages.parquet: 4 of 5 passages cite a resolved section.
    assert s["passages_in"] == 4 and s["passages_extracted"] == 4
    assert s["claims"] == len(out["claims"]) == 5
    assert s["claims_first_pass"] == 6 and s["claims_dropped"] == 1
    assert (s["quotes_verified_first_pass"], s["quotes_verified_final"]) == (4, 5)
    assert s["issues"] == len(out["issues"]) == 4  # {C1,C3}, C2, C4, C5
    assert s["issues_multi_claim"] == 1 and s["flagged"] == 1
    assert s["pairs_proposed"] == 3 and s["pairs_judged"] == 3
    assert s["pair_verdicts"] == {"same_issue_opposite_side": 1, "different": 1, "unsure": 1}
    assert s["review_rows_by_reason"] == {
        "quote_failed": 1, "quote_fragment": 0, "section_disagrees": 1, "no_section": 0,
        "linker_disagrees": 0, "missing_from_output": 1, "llm_failed": 0, "contested_merge": 0,
        "giant_issue": 0, "judge_unsure": 1,
    }  # fmt: skip
    assert s["forced_fallbacks"] == 1
    assert s["calls_by_step"] == {"extract": 3, "requote": 1, "judge": 3}
    assert s["usd_total"] > 0 and s["backend"] == "fake"
    assert s["linker_checked"] is False and s["rule_context"] is False
    assert len(s["letters_sha256"]) == 64 and len(s["passages_sha256"]) == 64
    assert s["prompt_sha1s"]["extract"]
    assert len(out["claim_issues"]) == 5 and set(out["claim_issues"]["claim_id"]) == set(
        out["claims"]["claim_id"]
    )
    g = out["graph"]
    assert {n["section_ref"] for n in g["nodes"]["section"]} == {S84, S85}
    assert sorted(n["letter_id"] for n in g["nodes"]["letter"]) == ["L1", "L2", "L3"]  # L4: copy
    assert g["nodes"]["campaign"][0]["campaign_id"] == "L2"
    assert len(g["edges"]["letter_claim"]) == 5
    assert sorted(e["letter_id"] for e in g["edges"]["letter_campaign"]) == ["L2", "L3"]
    assert "response" not in g["nodes"]
    review = out["review"]
    assert len(review) == 4
    assert json.loads(review[review["reason"] == "quote_failed"].iloc[0]["detail"])["passage_id"]


def test_rerun_from_pairs_makes_no_extract_call(data_dir):
    cfg = make_cfg()
    assert m.build_docket(DOCKET, data_dir, "all", cfg)
    first = read_outputs(data_dir)
    assert m.build_docket(DOCKET, data_dir, "pairs", cfg)
    second = read_outputs(data_dir)
    assert second["summary"]["claims"] == first["summary"]["claims"]
    # Every judge call was cached the second time: the ledger has cached rows for them.
    cached = [r["tag"] for r in second["ledger"] if r["cached"]]
    assert set(cached) == {"judge_141.84_000", "judge_141.84_000_fix1", "judge_141.85_000"}
    assert second["summary"]["calls_by_step"] == first["summary"]["calls_by_step"]


def test_llm_failure_gives_nonzero_exit(tmp_path, failing_fixtures, monkeypatch):
    write_inputs(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DOCKET_IDS", DOCKET)
    monkeypatch.setenv("GRAPH_BACKEND", "fake")
    monkeypatch.setenv("GRAPH_FIXTURES", str(failing_fixtures))
    monkeypatch.setenv("GRAPH_THREADS", "1")
    monkeypatch.setattr("pairs.embedder", lambda cfg: fake_embed)
    assert m.main(["all"]) == 1
    out = read_outputs(tmp_path)
    assert out["summary"]["review_rows_by_reason"]["llm_failed"] == 3
    assert out["summary"]["extract_batches_failed"] == 1
    assert out["summary"]["claims"] == 1


def test_budget_exceeded_writes_partial_outputs_and_exits_two(tmp_path, monkeypatch):
    write_inputs(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DOCKET_IDS", DOCKET)
    monkeypatch.setenv("GRAPH_BACKEND", "fake")
    monkeypatch.setenv("GRAPH_FIXTURES", str(FIXTURES))
    monkeypatch.setenv("GRAPH_THREADS", "1")
    monkeypatch.setenv("GRAPH_MAX_USD", "0.05")  # the first extract fixture costs $0.0581
    monkeypatch.setattr("pairs.embedder", lambda cfg: fake_embed)
    assert m.main(["all"]) == m.EXIT_BUDGET
    out = read_outputs(tmp_path)
    assert out["summary"]["budget_exceeded"] is True
    assert (tmp_path / "derived" / "graph" / DOCKET / "claims.parquet").exists()
    assert out["summary"]["review_rows_by_reason"]["llm_failed"] >= 1


def test_bad_subcommand(monkeypatch):
    assert m.main(["frobnicate"]) == 1
