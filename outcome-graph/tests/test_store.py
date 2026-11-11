"""Store and builder logic on a tiny hand-made graph, so no model or real data is needed."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build import stakeholder
from store import Store, _outcome

DOCKET = "TEST-0001"


def make(tmp: Path) -> Store:
    out = tmp / f"outcomes/{DOCKET}"
    out.mkdir(parents=True)
    (tmp / f"responses/{DOCKET}").mkdir(parents=True)
    nodes = [
        {"id": "ch:9", "kind": "chapter", "label": "Service line replacement", "chapter": "9"},
        {
            "id": "topic:9.7",
            "kind": "topic",
            "label": "Replacement deadlines",
            "code": "9.7",
            "chapter": "9",
            "comments": 3,
            "verdicts": {"adopted": 1, "declined": 1},
        },
        {
            "id": "ask:9.7:0",
            "kind": "ask",
            "label": "Use a cumulative average",
            "verdict": "adopted",
            "code": "9.7",
            "chapter": "9",
            "for": 1,
        },
        {
            "id": "ask:9.7:1",
            "kind": "ask",
            "label": "Allow 20 years for small systems",
            "verdict": "declined",
            "code": "9.7",
            "chapter": "9",
            "for": 1,
            "against": 1,
        },
        {
            "id": "org:0",
            "kind": "org",
            "label": "Denver Water",
            "stakeholder": "utility",
            "comments": 2,
            "record": {"won": 1, "lost": 1},
        },
        {
            "id": "org:1",
            "kind": "org",
            "label": "Unleaded Kids",
            "stakeholder": "advocacy",
            "comments": 1,
            "record": {"won": 1},
        },
        {
            "id": "sec:141.84",
            "kind": "section",
            "label": "§ 141.84",
            "title": "Replacement",
            "changed": 5,
            "paragraphs": 9,
        },
    ]
    edges = [
        {"source": "topic:9.7", "target": "ch:9", "kind": "in_chapter", "weight": 1},
        {"source": "ask:9.7:0", "target": "topic:9.7", "kind": "asked_in", "weight": 1},
        {"source": "ask:9.7:1", "target": "topic:9.7", "kind": "asked_in", "weight": 1},
        {"source": "topic:9.7", "target": "sec:141.84", "kind": "cites", "weight": 2},
        {"source": "org:0", "target": "topic:9.7", "kind": "commented", "weight": 2},
        {"source": "org:1", "target": "topic:9.7", "kind": "commented", "weight": 1},
        {"source": "org:0", "target": "ask:9.7:0", "kind": "supports", "weight": 1},
        {"source": "org:0", "target": "ask:9.7:1", "kind": "supports", "weight": 1},
        {"source": "org:1", "target": "ask:9.7:1", "kind": "opposes", "weight": 1},
    ]
    (out / "graph.json").write_text(
        json.dumps({"stats": {"asks": 2}, "nodes": nodes, "edges": edges})
    )
    details = {
        "topic:9.7": {"summary": "The EPA has adopted the cumulative average approach."},
        "ask:9.7:0": {
            "quote": "The EPA has adopted the cumulative average approach.",
            "quote_verified": True,
            "final_rule_change": "Cumulative average.",
        },
        "ask:9.7:1": {
            "quote": "The EPA disagrees.",
            "quote_verified": True,
            "final_rule_change": None,
        },
        "org:0": {"entries": [], "record": {"won": 1, "lost": 1}},
        "org:1": {"entries": [], "record": {"won": 1}},
        "sec:141.84": {"diff": []},
        "ch:9": {},
    }
    (out / "details.json").write_text(json.dumps(details))
    pd.DataFrame(
        {
            "entry_id": ["e1"],
            "organization": ["Denver Water"],
            "code": ["9.7"],
            "excerpt": ["x"],
            "response": ["y"],
            "record_id": ["r"],
        }
    ).to_parquet(tmp / f"responses/{DOCKET}/entries.parquet")
    return Store(DOCKET, data_root=tmp)


def test_outcome_rules():
    assert _outcome("adopted", "for") == "won"
    assert _outcome("adopted", "against") == "lost"
    assert _outcome("declined", "for") == "lost"
    assert _outcome("declined", "against") == "won"
    assert _outcome("partly_adopted", "for") == "partly"
    assert _outcome("clarified", "for") == "no_change"


def test_org_record_counts_sides(tmp_path):
    s = make(tmp_path)
    r = s.org_record("Denver")
    outcomes = {a["id"]: a["outcome"] for a in r["asks"]}
    assert outcomes == {"ask:9.7:0": "won", "ask:9.7:1": "lost"}


def test_compare_stakeholders(tmp_path):
    s = make(tmp_path)
    rows = {r["stakeholder"]: r for r in s.compare_stakeholders()["rows"]}
    assert rows["utility"]["won"] == 1 and rows["utility"]["lost"] == 1
    assert rows["advocacy"]["won"] == 1  # opposed an ask EPA declined
    assert rows["utility"]["won_share_of_decided"] == 0.5
    assert s.compare_stakeholders("ch:9")["rows"]
    assert s.compare_stakeholders("topic:1.1")["rows"] == []


def test_node_and_search(tmp_path):
    s = make(tmp_path)
    t = s.node("topic:9.7")
    assert {a["id"] for a in t["asks"]} == {"ask:9.7:0", "ask:9.7:1"}
    assert t["sections"][0]["id"] == "sec:141.84"
    a = s.node("ask:9.7:1")
    assert [o["id"] for o in a["supporters"]] == ["org:0"]
    assert [o["id"] for o in a["opponents"]] == ["org:1"]
    assert s.search("cumulative")[0]["id"] == "ask:9.7:0"
    assert s.search("denver", kind="org")[0]["id"] == "org:0"


def test_stakeholder_tags():
    assert stakeholder("Denver Water") == "utility"
    assert stakeholder("Texas Commission on Environmental Quality (TCEQ)") == "state"
    assert stakeholder("Freshwater Future") == "advocacy"
    assert stakeholder("American Water Works Association (AWWA)") == "trade"
    assert stakeholder("City of Concord, New Hampshire") == "local"
    assert stakeholder("Jane Smith") == "individual"
    assert stakeholder("Unknown") == "unknown"
