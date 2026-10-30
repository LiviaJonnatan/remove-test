from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import DOCKET, FakeSession
from rule_passages import pipeline
from rule_passages.collect import collect
from rule_passages.config import Settings
from rule_passages.store import PassageStore


def settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "data_dir": tmp_path,
        "chroma_host": "localhost",
        "chroma_port": 8000,
        "collection": "rule_passages_test",
        "dockets": (DOCKET,),
        "doc_types": ("Proposed Rule",),
        "documents": (),
        "max_words": 80,
        "overlap_words": 15,
    }
    return Settings(**{**base, **overrides})


def test_a_docket_with_a_known_commented_on_document_indexes_only_that_one(tmp_path, raw_excerpt):
    collect(DOCKET, settings(tmp_path).rule_dir, FakeSession(raw_excerpt))
    chunks = pipeline.build_chunks(settings(tmp_path))
    assert {c.document_number for c in chunks} == {"2019-00791"}


def test_other_dockets_fall_back_to_the_configured_document_types(tmp_path, raw_excerpt):
    other = "OTHER-2020-0001"
    collect(other, settings(tmp_path).rule_dir, FakeSession(raw_excerpt))
    only_proposed = settings(tmp_path, dockets=(other,))
    assert {c.document_number for c in pipeline.build_chunks(only_proposed)} == {"2019-00791"}
    both = settings(tmp_path, dockets=(other,), doc_types=("Proposed Rule", "Notice"))
    assert {c.document_number for c in pipeline.build_chunks(both)} == {"2019-00791", "2019-01483"}


def test_an_explicit_document_list_overrides_everything_else(tmp_path, raw_excerpt):
    collect(DOCKET, settings(tmp_path).rule_dir, FakeSession(raw_excerpt))
    cfg = settings(tmp_path, documents=("2019-01483",))
    assert {c.document_number for c in pipeline.build_chunks(cfg)} == {"2019-01483"}


def test_index_is_idempotent(tmp_path, raw_excerpt, chroma, embedder, collection_name):
    cfg = settings(tmp_path, collection=collection_name)
    collect(DOCKET, cfg.rule_dir, FakeSession(raw_excerpt))
    store = pipeline.index(cfg, chroma, embedder)
    first = embedder.passages_embedded
    assert first == store.count() > 0
    pipeline.index(cfg, chroma, embedder)
    assert embedder.passages_embedded == first


def test_index_prunes_chunks_that_no_longer_belong(tmp_path, raw_excerpt, chroma, embedder):
    name = "prune_test"
    collect(DOCKET, settings(tmp_path).rule_dir, FakeSession(raw_excerpt))
    wide = settings(tmp_path, collection=name, documents=("2019-00791", "2019-01483"))
    pipeline.index(wide, chroma, embedder)
    kept = pipeline.index(
        settings(tmp_path, collection=name, documents=("2019-00791",)), chroma, embedder
    )
    assert {c.document_number for c in kept.chunks()} == {"2019-00791"}


def test_sweep_scores_both_retrievers_at_each_size(tmp_path, raw_excerpt, chroma, embedder):
    from rule_passages.evaluate import LabeledQuery

    cfg = settings(tmp_path, collection="sweep_test")
    collect(DOCKET, cfg.rule_dir, FakeSession(raw_excerpt))
    labels = [LabeledQuery("c1", "ditch farm tributary", ("I/D",))]
    rows = pipeline.sweep(cfg, chroma, embedder, labels, sizes=[60, 120])
    assert [name for name, _ in rows] == [
        "bm25 @ 60 words",
        "dense @ 60 words",
        "bm25 @ 120 words",
        "dense @ 120 words",
    ]
    assert all(set(acc) == {1, 3} for _, acc in rows)


def test_section_outline_counts_chunks_per_section_in_reading_order():
    from conftest import make_chunk

    chunks = [
        make_chunk(0, "a", "III/E", "III > E. Ditches"),
        make_chunk(1, "b", "III/E", "III > E. Ditches"),
        make_chunk(2, "c", "III/G/1", "III > G. Wetlands > 1. What is proposed?"),
    ]
    assert pipeline.section_outline(chunks) == [
        ("2019-00791", "III/E", "E. Ditches", 4170, 2, False),
        ("2019-00791", "III/G/1", "G. Wetlands > 1. What is proposed?", 4172, 1, False),
    ]


def test_a_docket_that_yields_no_chunks_stops_the_stage_and_names_what_is_on_disk(
    tmp_path, raw_excerpt
):
    collect(DOCKET, settings(tmp_path).rule_dir, FakeSession(raw_excerpt))
    wrong = settings(tmp_path, documents=("0000-00000",))
    with pytest.raises(RuntimeError, match=r"no chunks to index.*2019-00791"):
        pipeline.build_chunks(wrong)


def test_a_docket_with_nothing_collected_fails_instead_of_indexing_nothing(tmp_path):
    with pytest.raises(RuntimeError, match=r"Documents on disk: none"):
        pipeline.build_chunks(settings(tmp_path))


def test_a_failed_build_leaves_the_existing_index_untouched(
    tmp_path, raw_excerpt, chroma, embedder, collection_name
):
    good = settings(tmp_path, collection=collection_name)
    collect(DOCKET, good.rule_dir, FakeSession(raw_excerpt))
    store = pipeline.index(good, chroma, embedder)
    before = store.count()
    broken = settings(tmp_path, collection=collection_name, documents=("0000-00000",))
    with pytest.raises(RuntimeError):
        pipeline.index(broken, chroma, embedder)
    assert PassageStore(chroma, collection_name, embedder).count() == before > 0


def write_document(rule_dir: Path, docket: str, number: str, text: str) -> None:
    folder = rule_dir / docket
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{number}.txt").write_text(text, encoding="utf-8")
    meta = {
        "document_number": number,
        "title": "A rule",
        "type": "Proposed Rule",
        "publication_date": "2019-02-14",
        "citation": "84 FR 1",
        "html_url": "https://example.org",
    }
    (folder / f"{number}.json").write_text(json.dumps(meta), encoding="utf-8")


def test_indexing_one_docket_does_not_delete_another_dockets_chunks(
    tmp_path, raw_excerpt, chroma, embedder, collection_name
):
    other = "OTHER-2020-0001"
    rule_dir = settings(tmp_path).rule_dir
    write_document(rule_dir, DOCKET, "2019-00791", raw_excerpt)
    write_document(rule_dir, other, "2020-00001", raw_excerpt)
    shared = {"collection": collection_name}
    pipeline.index(settings(tmp_path, dockets=(DOCKET,), **shared), chroma, embedder)
    store = pipeline.index(settings(tmp_path, dockets=(other,), **shared), chroma, embedder)
    assert {c.docket_id for c in store.chunks()} == {DOCKET, other}
    pipeline.index(settings(tmp_path, dockets=(DOCKET,), **shared), chroma, embedder)
    assert {c.docket_id for c in store.chunks()} == {DOCKET, other}


def test_the_same_document_under_two_dockets_is_refused(tmp_path, raw_excerpt):
    rule_dir = settings(tmp_path).rule_dir
    for docket in (DOCKET, "OTHER-2020-0001"):
        write_document(rule_dir, docket, "2019-00791", raw_excerpt)
    both = settings(tmp_path, dockets=(DOCKET, "OTHER-2020-0001"))
    with pytest.raises(RuntimeError, match=r"chunk ids appear twice"):
        pipeline.build_chunks(both)


def test_sweep_can_include_procedural_sections(tmp_path, raw_excerpt, chroma, embedder):
    from rule_passages.evaluate import LabeledQuery

    cfg = settings(tmp_path, collection="sweep_proc")
    collect(DOCKET, cfg.rule_dir, FakeSession(raw_excerpt))
    labels = [LabeledQuery("c1", "comments must be received", ("2019-00791:DATES",))]
    default = dict(pipeline.sweep(cfg, chroma, embedder, labels, sizes=[80]))
    with_all = dict(
        pipeline.sweep(cfg, chroma, embedder, labels, sizes=[80], include_procedural=True)
    )
    assert default["bm25 @ 80 words"][1] == 0.0  # DATES is procedural, so it cannot be found
    assert with_all["bm25 @ 80 words"][1] == 1.0
