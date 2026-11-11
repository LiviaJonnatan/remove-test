"""The coach's checks: cited asks must come from a tool, rule quotes must be in the rule."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach import Coach, Index, parse_reply
from test_store import DOCKET, make


def coach(tmp_path, monkeypatch) -> Coach:
    st = make(tmp_path)
    pd.DataFrame([
        {"docket_id": DOCKET, "section": "141.84", "title": "Service lines", "op": "modified",
         "marker": "(d)", "proposed": "old text", "similarity": 0.5, "diff": "",
         "final": "A water system must replace lead service lines at an average annual rate of at least 10 percent."},
    ]).to_parquet(tmp_path / f"responses/{DOCKET}/rule_diff.parquet")  # fmt: skip
    # no embedding model in tests: vectors are never used by these checks
    monkeypatch.setattr(Index, "cached", lambda self, name, texts: np.zeros((len(texts), 384), np.float32))
    return Coach(st)


def test_clean_drops_ids_no_tool_returned(tmp_path, monkeypatch):
    c = coach(tmp_path, monkeypatch)
    raw = {"overall": "ok", "points": [{"ask": "x", "similar": ["ask:9.7:1", "ask:9.7:0", "ask:99.1:0"],
                                        "outlook": "likely_declined"}]}  # fmt: skip
    out = c.clean(raw, allowed={"ask:9.7:1", "ask:99.1:0"})
    p = out["points"][0]
    assert p["similar"] == ["ask:9.7:1"]  # 9.7:0 was never returned, 99.1:0 does not exist
    assert p["mix"] == {"declined": 1}  # counted in code from the graph, not by the model
    assert set(out["asks"]) == {"ask:9.7:1"}


def test_rule_quote_kept_only_if_in_final_text(tmp_path, monkeypatch):
    c = coach(tmp_path, monkeypatch)
    good = {"section": "141.84(d)", "quote": "replace lead service lines at an average annual rate of at least 10 percent"}
    bad = {"section": "141.84(d)", "quote": "replace lead service lines within five years of the compliance date"}
    raw = {"points": [
        {"ask": "a", "similar": [], "outlook": "already_in_rule", "in_rule": good},
        {"ask": "b", "similar": [], "outlook": "already_in_rule", "in_rule": bad},
    ]}  # fmt: skip
    a, b = c.clean(raw, allowed=set())["points"]
    assert a["in_rule"]["section"] == "141.84(d)" and a["outlook"] == "already_in_rule"
    assert b["in_rule"] is None and b["outlook"] == "new"  # unverified claim dropped


def test_placeholders_stripped_and_garbled_reply_rejected(tmp_path, monkeypatch):
    c = coach(tmp_path, monkeypatch)
    raw = {"points": [{"ask": "a", "similar": [], "why": "EPA declined it. EPA said {{PLACEHOLDER}}"}]}
    assert c.clean(raw, set())["points"][0]["why"] == "EPA declined it."
    assert parse_reply('{"overall": "x", "points": [{"why": "said "no""}]}') is None
    assert parse_reply('text {"overall": "x", "points": []} text')["points"] == []


def test_prefixed_ids_resolve_to_the_right_rule(tmp_path, monkeypatch):
    c = coach(tmp_path, monkeypatch)
    short = c.s.short
    assert c.resolve("ask:9.7:0")[1] == "ask:9.7:0"
    assert c.resolve(f"{short}/ask:9.7:0")[1] == "ask:9.7:0"
    assert c.resolve("NOPE/ask:9.7:0") is None
