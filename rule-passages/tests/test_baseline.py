from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from conftest import make_chunk
from rule_passages.baseline import (
    CitedPassage,
    RegulatoryTextOnly,
    first_hit,
    load_cited_passages,
    run,
    score,
)
from rule_passages.retrieve import Hit
from rule_passages.store import PassageStore

DOCKET = "EPA-HQ-OW-2018-0149"
CPP = "EPA-HQ-OAR-2017-0355"

# A tiny rule: one preamble chunk and two sections of regulatory text.
RULE = [
    make_chunk(0, "A ditch that drains a farm field is excluded.", "III/E", "E. Exclusions"),
    make_chunk(1, "Ditch means a constructed channel.", "PART 328/§ 328.3", "Sec. 328.3 Terms."),
    make_chunk(2, "Lakes and ponds are covered.", "PART 328/§ 328.4", "Sec. 328.4 Waters."),
]
# Another docket's rule. It matches the first query best, so it would win if the docket filter
# were missing.
OTHER = make_chunk(
    9,
    "A ditch on a farm, a farm ditch.",
    "PART 328/§ 328.9",
    "Sec. 328.9 Other.",
    "2017-22349",
    CPP,
)


def write_passages(directory, passages, links):
    directory.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(passages), directory / "passages.parquet")
    pq.write_table(pa.Table.from_pylist(links), directory / "links.parquet")


def passage(pid, letter, text):
    return {"passage_id": pid, "letter_id": letter, "text_masked": text}


def link(pid, ref):
    return {"passage_id": pid, "section_ref": ref}


@pytest.fixture
def passages_dir(tmp_path):
    directory = tmp_path / "derived" / "passages" / DOCKET
    write_passages(
        directory,
        [
            passage("L1:p001", "L1", "a ditch on my farm"),
            passage("L1:p002", "L1", "cites only a rule outside this one"),
            passage("L1:p003", "L1", "cites nothing"),
            passage("L2:p001", "L2", "lakes and ponds"),
        ],
        [
            link("L1:p001", "PART 328/§ 328.3"),
            link("L1:p002", None),
            link("L2:p001", "PART 328/§ 328.4"),
        ],
    )
    return directory


@pytest.fixture
def store(chroma, collection_name, embedder):
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert([*RULE, OTHER])
    return store


def test_only_passages_with_a_section_are_tested(tmp_path):
    directory = tmp_path / "passages"
    write_passages(
        directory,
        [passage("a", "L1", "x"), passage("b", "L1", "y"), passage("c", "L1", "z")],
        [link("a", "PART 141/§ 141.86"), link("a", "PART 141/§ 141.2"), link("b", None)],
    )
    assert load_cited_passages(directory) == [
        CitedPassage("a", "L1", "x", ("PART 141/§ 141.2", "PART 141/§ 141.86"))
    ]


def test_first_hit_is_the_rank_of_the_first_result_in_a_cited_section():
    hits = [
        Hit(1, 1.0, "bm25", make_chunk(0, "x", "PART 141/§ 141.8")),
        Hit(2, 1.0, "bm25", make_chunk(1, "x", "PART 141/§ 141.84")),
    ]
    # § 141.8 is a different section from § 141.84, not a parent of it.
    assert first_hit(hits, ("PART 141/§ 141.84",)) == 2
    assert first_hit(hits, ("PART 141/§ 141.86",)) is None


class FixedRetriever:
    name = "fixed"

    def __init__(self, refs):
        self.refs = refs
        self.asked_for = None

    def search(self, query, k):
        self.asked_for = k
        return [
            Hit(rank, 1.0, self.name, make_chunk(rank, "x", ref))
            for rank, ref in enumerate(self.refs[:k], 1)
        ]


def test_regulatory_text_only_drops_the_preamble_and_renumbers():
    inner = FixedRetriever(["V/B/1", "PART 141/§ 141.84", "IX", "PART 141/§ 141.2"])
    hits = RegulatoryTextOnly(inner, depth=4).search("q", 3)
    assert [(h.rank, h.chunk.section_ref) for h in hits] == [
        (1, "PART 141/§ 141.84"),
        (2, "PART 141/§ 141.2"),
    ]
    assert inner.asked_for == 4  # the whole ranking, not just the top 3


def test_every_method_on_a_hand_worked_rule(passages_dir, store):
    # "a ditch on my farm" cites § 328.3. Over the whole rule every method puts the preamble chunk
    # (ditch and farm) first and § 328.3 (ditch only) second; in the regulatory text § 328.3 is
    # first. "lakes and ponds" cites § 328.4, and every method puts it first.
    rows = score([*RULE, OTHER], store, DOCKET, load_cited_passages(passages_dir))
    assert [r.key for r in rows] == ["bm25", "dense", "merged"]
    for row in rows:
        assert row.whole_rule == [2, 1]
        assert row.regulatory == [1, 1]


def test_run_writes_the_table_and_the_ranks(tmp_path, passages_dir, store):
    report = run(tmp_path, DOCKET, [*RULE, OTHER], store)
    assert "2 passages from 2 letters" in report
    assert "3 chunks of the rule, procedural sections left out; 2 of them" in report
    assert "| BM25 | 50.0% | 100.0% | 100.0% | 100.0% |" in report
    assert "| L1 | 1 | 0 / 1 | 0 / 1 | 0 / 1 |" in report

    out = tmp_path / "derived" / "baseline" / DOCKET
    assert (out / "baseline.md").read_text(encoding="utf-8") == report
    lines = [json.loads(line) for line in (out / "ranks.jsonl").read_text().splitlines()]
    assert lines[0] == {
        "passage_id": "L1:p001",
        "letter_id": "L1",
        "gold": ["PART 328/§ 328.3"],
        "bm25": 2,
        "bm25_regulatory": 1,
        "dense": 2,
        "dense_regulatory": 1,
        "merged": 2,
        "merged_regulatory": 1,
    }


def test_a_docket_with_no_cited_passage_stops(tmp_path, store):
    write_passages(
        tmp_path / "derived" / "passages" / DOCKET,
        [passage("a", "L1", "x")],
        [link("a", None)],
    )
    with pytest.raises(RuntimeError, match="no passage cites a section"):
        run(tmp_path, DOCKET, RULE, store)
