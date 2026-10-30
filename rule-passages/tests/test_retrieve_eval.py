from __future__ import annotations

import json

import pytest

from conftest import make_chunk
from rule_passages.evaluate import (
    LabeledQuery,
    format_table,
    in_section,
    load_labels,
    top_k_accuracy,
)
from rule_passages.retrieve import (
    FUSION_DEPTH,
    BM25Retriever,
    DenseRetriever,
    FusedRetriever,
    Hit,
    clean_query,
    reciprocal_rank_fusion,
)
from rule_passages.store import PassageStore

CHUNKS = [
    make_chunk(0, "Wetlands adjacent to a tributary are covered.", "III/G", "G. Wetlands"),
    make_chunk(1, "A ditch that drains a farm field is excluded.", "III/E", "E. Ditches"),
    make_chunk(2, "Lakes and ponds that are not connected are not covered.", "III/F", "F. Lakes"),
    make_chunk(3, "Wetlands in the final rule.", "III/G", "G. Wetlands", doc="2020-02500"),
]


def hit(ref: str, doc: str = "2019-00791") -> Hit:
    return Hit(1, 1.0, "bm25", make_chunk(0, "x", ref, doc=doc))


def test_bm25_retriever_ranks_the_matching_chunk_first():
    hits = BM25Retriever(CHUNKS).search("a farm ditch", k=2)
    assert [h.chunk.section_ref for h in hits][0] == "III/E"
    assert [h.rank for h in hits] == [1]  # only one chunk shares a term
    assert hits[0].retriever == "bm25"


def test_clean_query_strips_comment_html():
    raw = "<br/><span style='padding-left: 30px'></span>Re:&nbsp;the  ditch<br/>on my farm"
    assert clean_query(raw) == "Re: the ditch on my farm"


def test_queries_are_cleaned_before_searching(chroma, collection_name, embedder):
    html_query = "<br/><span style='x'>a farm</span><br/> ditch"
    assert BM25Retriever(CHUNKS).search(html_query, 1)[0].chunk.section_ref == "III/E"
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(CHUNKS[:3])
    assert DenseRetriever(store).search(html_query, 1)[0].chunk.section_ref == "III/E"


def test_retrievers_skip_procedural_chunks_by_default(chroma, collection_name, embedder):
    from dataclasses import replace

    chunks = [replace(CHUNKS[1], procedural=True), CHUNKS[0], CHUNKS[2]]
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(chunks)
    query = "a ditch on my farm"
    assert (
        BM25Retriever(chunks).search(query, 3) == []
    )  # the only chunk with those terms is procedural
    assert (
        BM25Retriever(chunks, include_procedural=True).search(query, 1)[0].chunk.id == chunks[0].id
    )
    assert chunks[0].id not in {h.chunk.id for h in DenseRetriever(store).search(query, 3)}
    assert (
        DenseRetriever(store, include_procedural=True).search(query, 1)[0].chunk.id == chunks[0].id
    )


def test_both_retrievers_can_be_limited_to_one_docket(chroma, collection_name, embedder):
    other = make_chunk(9, "Wetland rules for power plants.", "II/B", "B. Plants", "2017-22349",
                       "EPA-HQ-OAR-2017-0355")  # fmt: skip
    chunks = [*CHUNKS[:3], other]
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(chunks)
    for retriever in (
        BM25Retriever(chunks, docket_id="EPA-HQ-OAR-2017-0355"),
        DenseRetriever(store, docket_id="EPA-HQ-OAR-2017-0355"),
    ):
        hits = retriever.search("wetland", k=5)
        assert [h.chunk.id for h in hits] == [other.id]


def test_hit_to_dict_is_the_shape_the_api_returns():
    h = Hit(2, 0.123456, "bm25", make_chunk(5, "some text", "III/D/1", "D. Tributaries"))
    assert h.to_dict() == {
        "retriever": "bm25",
        "rank": 2,
        "score": 0.1235,
        "id": "2019-00791:0005",
        "docket_id": "EPA-HQ-OW-2018-0149",
        "document_number": "2019-00791",
        "citation": "84 FR 4154",
        "page": 4175,
        "section_ref": "III/D/1",
        "heading": "D. Tributaries",
        "text": "some text",
    }


def test_dense_retriever_wraps_the_store(chroma, collection_name, embedder):
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(CHUNKS[:3])
    hits = DenseRetriever(store).search("wetland near a tributary", k=2)
    assert hits[0].chunk.section_ref == "III/G" and hits[0].rank == 1
    assert hits[0].score >= hits[1].score


def ranked(retriever: str, refs: str, scores: list[float] | None = None) -> list[Hit]:
    """A ranked list from one retriever, best first. A letter is the same passage in every list."""
    scores = scores or [0.0] * len(refs)
    return [
        Hit(rank, score, retriever, make_chunk(ord(ref), ref, ref))
        for rank, (ref, score) in enumerate(zip(refs, scores, strict=True), start=1)
    ]


class FixedRetriever:
    """Returns a fixed list and remembers how deep it was asked to search."""

    def __init__(self, hits: list[Hit]):
        self.name = hits[0].retriever
        self.hits = hits
        self.asked_for: list[int] = []

    def search(self, query: str, k: int) -> list[Hit]:
        self.asked_for.append(k)
        return self.hits[:k]


def test_fusion_prefers_a_passage_both_retrievers_rank_well():
    # B is second in both lists; A and C are each first in only one.
    merged = reciprocal_rank_fusion([ranked("bm25", "ABD"), ranked("dense", "CBE")], k=3)
    assert [h.chunk.section_ref for h in merged] == ["B", "A", "C"]
    assert [h.rank for h in merged] == [1, 2, 3]
    assert {h.retriever for h in merged} == {"merged"}


def test_fusion_ignores_raw_scores():
    # Adding raw scores would put A first (BM25 gave it 1000). By rank, B (2nd and 1st) wins.
    bm25 = ranked("bm25", "AB", scores=[1000.0, 999.0])
    dense = ranked("dense", "BC", scores=[0.9, 0.1])
    assert reciprocal_rank_fusion([bm25, dense], k=1)[0].chunk.section_ref == "B"


def test_fused_retriever_searches_each_retriever_deeper_than_k():
    bm25, dense = FixedRetriever(ranked("bm25", "ABD")), FixedRetriever(ranked("dense", "CBE"))
    fused = FusedRetriever([bm25, dense])
    assert [h.chunk.section_ref for h in fused.search("anything", k=1)] == ["B"]
    assert bm25.asked_for == dense.asked_for == [FUSION_DEPTH]
    # A k above the depth is still honored.
    fused.search("anything", k=FUSION_DEPTH + 10)
    assert bm25.asked_for[-1] == FUSION_DEPTH + 10


def test_fused_retriever_scores_like_the_other_two(chroma, collection_name, embedder):
    # It is a Retriever, so top_k_accuracy takes it as it takes BM25 and embeddings.
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(CHUNKS[:3])
    fused = FusedRetriever([BM25Retriever(CHUNKS[:3]), DenseRetriever(store)])
    assert fused.name == "merged"
    labels = [LabeledQuery("q1", "a farm ditch", ("III/E",))]
    assert top_k_accuracy(fused, labels, ks=(1,)) == {1: 1.0}


@pytest.mark.parametrize(
    ("ref", "gold", "expected"),
    [
        ("III/G", "III/G", True),
        ("III/G/1", "III/G", True),  # a subsection counts
        ("III/GG", "III/G", False),  # a different section with the same prefix does not
        ("III", "III/G", False),  # the parent is broader than the label
        ("III/G", "2019-00791:III/G", True),
        ("III/G", "2020-02500:III/G", False),  # right section, wrong document
        ("PART 328/§ 328.3", "PART 328/§ 328.3", True),
    ],
)
def test_in_section(ref, gold, expected):
    assert in_section(hit(ref), gold) is expected


class StubRetriever:
    name = "stub"

    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers

    def search(self, query: str, k: int) -> list[Hit]:
        return [
            Hit(i, 1.0, "stub", make_chunk(i, "t", ref))
            for i, ref in enumerate(self.answers[query][:k], 1)
        ]


def test_top_k_accuracy_counts_a_hit_anywhere_in_the_top_k():
    labels = [
        LabeledQuery("c1", "q1", ("III/G",)),
        LabeledQuery("c2", "q2", ("III/E",)),
        LabeledQuery("c3", "q3", ("VI/A",)),
    ]
    retriever = StubRetriever({"q1": ["III/G", "X"], "q2": ["X", "III/E/1"], "q3": ["X", "Y", "Z"]})
    assert top_k_accuracy(retriever, labels, ks=(1, 3)) == {1: 1 / 3, 3: 2 / 3}


def test_load_labels_reads_inline_and_file_queries_and_skips_unlabeled_campaigns(tmp_path):
    (tmp_path / "letters").mkdir()
    (tmp_path / "letters" / "c2.txt").write_text("a letter in a file")
    path = tmp_path / "labels.jsonl"
    rows = [
        {"campaign_id": "c1", "query": "a letter", "gold": ["III/G", "III/E"]},
        {"campaign_id": "c2", "query_file": "letters/c2.txt", "gold": ["2019-00791:VI/K"]},
        {"campaign_id": "c3", "query": "nothing specific", "gold": []},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    assert load_labels(path) == [
        LabeledQuery("c1", "a letter", ("III/G", "III/E")),
        LabeledQuery("c2", "a letter in a file", ("2019-00791:VI/K",)),
    ]


def test_format_table_lists_each_retriever_and_k():
    table = format_table([("bm25", {1: 0.5, 3: 0.75}), ("dense", {1: 0.6, 3: 0.9})])
    assert "top-1" in table and "top-3" in table
    assert "0.75" in table and "0.90" in table
