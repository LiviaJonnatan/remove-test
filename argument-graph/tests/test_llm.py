"""The call wrapper: cache, re-ask, ledger rows, prices, budget guard."""

import json

import pytest

from backends import FakeBackend
from conftest import FIXTURES, make_cfg
from llm import LLM, BudgetExceeded, CallFailed, parse_json, price
from templates import schema

LEDGER_FIELDS = {
    "tag", "step", "model", "backend", "effort", "attempt", "secs", "input_tokens",
    "cache_write_tokens", "cache_read_tokens", "output_tokens", "usd", "price_source", "ok",
    "stop_reason", "cached",
}  # fmt: skip


def make_llm(tmp_path, **overrides):
    cfg = make_cfg(**overrides)
    backend = FakeBackend(FIXTURES)
    return LLM(cfg, tmp_path / "out", backend=backend), backend


def test_parse_json_strips_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no object here")


def test_cache_hit_makes_no_backend_call(tmp_path):
    llm, backend = make_llm(tmp_path)
    out1 = llm.call("good_call", "extract", "sys", "static", "user", schema("extract"))
    out2 = llm.call("good_call", "extract", "sys", "static", "user", schema("extract"))
    assert out1 == out2 == {"passages": []}
    assert backend.calls == ["good_call"]
    rows = llm.rows()
    assert [r["cached"] for r in rows] == [False, True]
    assert set(rows[0]) >= LEDGER_FIELDS
    assert rows[0]["ok"] is True and rows[0]["attempt"] == 1
    assert (tmp_path / "out" / "raw" / "good_call.json").exists()
    assert (tmp_path / "out" / "prompts" / "good_call.txt").read_text().startswith("=== SYSTEM")


def test_schema_failure_triggers_one_reask_then_fails(tmp_path):
    llm, backend = make_llm(tmp_path)
    with pytest.raises(CallFailed):
        llm.call("schema_bad_twice", "extract", "sys", "", "user", schema("extract"))
    assert backend.calls == ["schema_bad_twice", "schema_bad_twice"]
    rows = llm.rows()
    assert [r["ok"] for r in rows] == [False, False]
    assert [r["attempt"] for r in rows] == [1, 2]
    assert "not JSON" in rows[0]["error"] and "schema" in rows[1]["error"]
    assert not (tmp_path / "out" / "raw" / "schema_bad_twice.json").exists()


def test_refusal_is_not_retried(tmp_path):
    llm, backend = make_llm(tmp_path)
    with pytest.raises(CallFailed):
        llm.call("refused", "extract", "sys", "", "user", schema("extract"))
    assert backend.calls == ["refused"]
    assert llm.rows()[0]["stop_reason"] == "refusal"


def test_usd_follows_prices_json():
    table = json.loads((FIXTURES.parents[1] / "prices.json").read_text())["claude-fable-5-1"]
    usage = {"input_tokens": 10, "cache_write_tokens": 1000, "cache_read_tokens": 500,
             "output_tokens": 200}  # fmt: skip
    usd, source = price(usage, "claude-fable-5-1")
    expected = (10 * table["input"] + 1000 * table["cache_write_5m"] + 500 * table["cache_read"]
                + 200 * table["output"]) / table["per"]  # fmt: skip
    assert usd == pytest.approx(expected)
    assert source.startswith("prices.json")
    assert price(usage, "unknown-model") == (None, "unknown")


def test_fixture_without_usd_is_priced_from_the_table(tmp_path):
    llm, _ = make_llm(tmp_path)
    llm.call("good_call", "extract", "sys", "", "user", schema("extract"))
    row = llm.rows()[0]
    assert row["usd"] == pytest.approx((10 * 10 + 1000 * 12.5 + 500 * 0.25 + 200 * 50) / 1e6)


def test_budget_guard_keeps_the_crossing_call_and_refuses_the_next_live_one(tmp_path):
    llm, backend = make_llm(tmp_path, max_usd=5.0)
    with pytest.raises(BudgetExceeded):
        llm.call("pricey", "extract", "sys", "", "user", schema("extract"))  # 1M input = $10
    assert llm.spent == pytest.approx(10.0)
    # The paid answer is on disk, so a rerun does not buy it again.
    assert (tmp_path / "out" / "raw" / "pricey.json").exists()
    again, backend2 = make_llm(tmp_path, max_usd=5.0)
    assert again.spent == pytest.approx(10.0)
    assert again.call("pricey", "extract", "sys", "", "user", schema("extract")) == {"passages": []}
    assert backend2.calls == []  # cached, and a cached call never raises
    # A live call is refused before the backend is reached: nothing more is paid for.
    with pytest.raises(BudgetExceeded):
        again.call("good_call", "extract", "sys", "", "user", schema("extract"))
    assert backend2.calls == [] and again.spent == pytest.approx(10.0)
    assert not (tmp_path / "out" / "raw" / "good_call.json").exists()


def test_cache_needs_the_prompt_hash_and_a_valid_answer(tmp_path):
    llm, backend = make_llm(tmp_path)
    llm.call("good_call", "extract", "sys", "static", "user", schema("extract"))
    raw = tmp_path / "out" / "raw" / "good_call.json"
    # Another prompt under the same tag is a miss.
    llm.call("good_call", "extract", "sys", "static", "another batch", schema("extract"))
    assert backend.calls == ["good_call", "good_call"]
    # A file written before the hash was stored is a miss too.
    d = json.loads(raw.read_text())
    del d["user_sha1"]
    raw.write_text(json.dumps(d))
    llm.call("good_call", "extract", "sys", "static", "another batch", schema("extract"))
    assert backend.calls == ["good_call"] * 3
    # A cached answer that no longer validates against the schema is a miss.
    llm.call("good_call", "extract", "sys", "static", "another batch", schema("extract"))
    assert backend.calls == ["good_call"] * 3  # hit
    with pytest.raises(CallFailed):  # the fixture's {"passages": []} lacks "matches"
        llm.call("good_call", "extract", "sys", "static", "another batch", schema("match"))
    assert backend.calls[:4] == ["good_call"] * 4  # the miss went to the backend
