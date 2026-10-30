from __future__ import annotations

import math

from rule_passages.bm25 import BM25Index, stem, tokenize


def test_stem_strips_plurals_but_leaves_other_words_alone():
    words = ["wetlands", "ponds", "ditches", "boundaries", "glass", "status", "analysis", "tie"]
    assert [stem(w) for w in words] == [
        "wetland",
        "pond",
        "ditch",
        "boundary",
        "glass",
        "status",
        "analysis",
        "tie",
    ]


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("The Agencies propose a definition of Wetlands.") == [
        "agency",
        "propose",
        "definition",
        "wetland",
    ]


def test_idf_matches_the_lucene_formula():
    index = BM25Index(["wetland ditch", "wetland pond", "farm road"])
    assert math.isclose(index.idf("wetland"), math.log(1 + (3 - 2 + 0.5) / (2 + 0.5)))
    assert math.isclose(index.idf("farm"), math.log(1 + (3 - 1 + 0.5) / (1 + 0.5)))
    assert index.idf("absent") > index.idf("wetland")


def test_score_matches_a_hand_computation():
    docs = ["wetland ditch ditch", "pond"]
    index = BM25Index(docs, k1=1.5, b=0.75)
    avg = (3 + 1) / 2
    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected = idf * 2 * (1.5 + 1) / (2 + 1.5 * (1 - 0.75 + 0.75 * 3 / avg))
    ((doc, score),) = index.search("ditches", k=5)
    assert doc == 0 and math.isclose(score, expected)


def test_best_match_ranks_first_and_unknown_terms_return_nothing():
    index = BM25Index(["lakes and ponds", "wetlands adjacent to ditches", "farm roads"])
    assert index.search("wetland", k=3)[0][0] == 1
    assert index.search("xylophone", k=3) == []


def test_a_shorter_passage_beats_a_longer_one_with_the_same_term_count():
    index = BM25Index(["ditch " + "filler " * 40, "ditch"])
    assert [d for d, _ in index.search("ditch", k=2)] == [1, 0]


def test_repeating_a_query_term_does_not_change_the_ranking_or_scores():
    index = BM25Index(["wetland ditch", "ditch ditch"])
    assert index.search("ditch ditch ditch", k=2) == index.search("ditch", k=2)


def test_ties_break_by_document_order():
    index = BM25Index(["ditch", "ditch", "ditch"])
    assert [d for d, _ in index.search("ditch", k=3)] == [0, 1, 2]
