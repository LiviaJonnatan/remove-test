from __future__ import annotations

import argparse
import json

import main
from conftest import make_chunk
from rule_passages.store import PassageStore

WOTUS = "EPA-HQ-OW-2018-0149"
CPP = "EPA-HQ-OAR-2017-0355"


def run_query(monkeypatch, capsys, store, **overrides) -> list[dict]:
    monkeypatch.setattr(main, "open_store", lambda settings: store)
    args = {"text": "wetland", "file": None, "method": "both", "k": 5, "json": True, "docket": None}
    main.cmd_query(None, argparse.Namespace(**{**args, **overrides}))
    return json.loads(capsys.readouterr().out)


def two_docket_store(chroma, collection_name, embedder) -> PassageStore:
    store = PassageStore(chroma, collection_name, embedder)
    store.upsert(
        [
            make_chunk(0, "Wetlands next to a tributary.", "III/G", "G. Wetlands"),
            make_chunk(
                1, "Wetland credits in the repeal.", "II/B", "B. Credits", "2017-22349", CPP
            ),
        ]
    )
    return store


def test_query_command_searches_every_docket_by_default(
    monkeypatch, capsys, chroma, collection_name, embedder
):
    store = two_docket_store(chroma, collection_name, embedder)
    hits = run_query(monkeypatch, capsys, store)
    assert {h["docket_id"] for h in hits} == {WOTUS, CPP}


def test_query_command_passes_the_docket_to_both_retrievers(
    monkeypatch, capsys, chroma, collection_name, embedder
):
    store = two_docket_store(chroma, collection_name, embedder)
    hits = run_query(monkeypatch, capsys, store, docket=CPP)
    assert {h["retriever"] for h in hits} == {"bm25", "dense"}
    assert {h["docket_id"] for h in hits} == {CPP}


def test_query_command_returns_nothing_for_an_unknown_docket(
    monkeypatch, capsys, chroma, collection_name, embedder
):
    store = two_docket_store(chroma, collection_name, embedder)
    assert run_query(monkeypatch, capsys, store, docket="NOT-A-DOCKET") == []
