from __future__ import annotations

import json

from conftest import DOCKET, FakeSession
from rule_passages.collect import collect, list_documents, load_documents


def test_list_documents_follows_pagination(raw_excerpt):
    docs = list_documents(DOCKET, FakeSession(raw_excerpt))
    assert [d["document_number"] for d in docs] == ["2019-00791", "2019-01483"]


def test_listing_asks_for_the_fields_the_collector_needs(raw_excerpt):
    session = FakeSession(raw_excerpt)
    list_documents(DOCKET, session)
    assert session.listing_params["conditions[docket_id]"] == DOCKET
    assert {"raw_text_url", "document_number", "type"} <= set(session.listing_params["fields[]"])


def test_collect_saves_text_and_metadata_and_a_rerun_downloads_nothing(tmp_path, raw_excerpt):
    session = FakeSession(raw_excerpt)
    paths = collect(DOCKET, tmp_path, session)
    assert [p.name for p in paths] == ["2019-00791.txt", "2019-01483.txt"]
    meta = json.loads((tmp_path / DOCKET / "2019-00791.json").read_text())
    assert meta["citation"] == "84 FR 4154" and meta["type"] == "Proposed Rule"
    downloads = [r for r in session.requests if r.endswith(".txt")]
    assert len(downloads) == 2
    collect(DOCKET, tmp_path, session)
    assert len([r for r in session.requests if r.endswith(".txt")]) == 2


def test_load_documents_reads_back_what_collect_saved(tmp_path, raw_excerpt):
    collect(DOCKET, tmp_path, FakeSession(raw_excerpt))
    docs = load_documents(DOCKET, tmp_path)
    assert [d.document_number for d in docs] == ["2019-00791", "2019-01483"]
    assert docs[0].raw_text == raw_excerpt and docs[0].doc_type == "Proposed Rule"
