"""POST /retrieve: a letter in, ranked rule passages out."""

import pytest
from fastapi.testclient import TestClient
from rule_passages.retrieve import RRF_K

from conftest import DEV_DOCKET, make_chunk
from main import PassageIndex, create_app

TRANSFER_DOCKET = "EPA-HQ-OAR-2017-0355"
# The fields the frontend reads. Hit.to_dict() in rule-passages defines them; this pins the
# contract from the API's side too.
HIT_FIELDS = {
    "retriever", "rank", "score", "id", "docket_id", "document_number",
    "citation", "page", "section_ref", "heading", "text",
}  # fmt: skip


@pytest.fixture
def client(store):
    store.upsert([
        make_chunk(0, "Tributary flow and ephemeral streams.", ref="III/D", heading="D. Flow"),
        make_chunk(1, "Wetland adjacency and wetland buffers.", ref="III/G", heading="G. Wetlands"),
        make_chunk(2, "Ditch exclusions for farm ditch work.", ref="III/E", heading="E. Ditches"),
        make_chunk(3, "Send tributary comments by tributary mail.", ref="SUMMARY",
                   heading="Summary", procedural=True),
        make_chunk(0, "Tributary rules for power plants.", docket=TRANSFER_DOCKET,
                   doc="2017-22349", ref="II/A", heading="A. Power"),
    ])  # fmt: skip
    with TestClient(create_app(lambda: PassageIndex(store))) as client:
        yield client


def retrieve(client, **body):
    response = client.post("/retrieve", json=body)
    assert response.status_code == 200, response.text
    return response.json()["hits"]


def test_both_retrievers_answer_bm25_first_then_embeddings(client):
    hits = retrieve(client, text="ephemeral tributary flow", k=1, docket_id=DEV_DOCKET)
    assert [(h["retriever"], h["rank"]) for h in hits] == [("bm25", 1), ("dense", 1)]
    assert {h["section_ref"] for h in hits} == {"III/D"}


def test_every_hit_has_the_fields_the_frontend_reads(client):
    for hit in retrieve(client, text="wetland buffers"):
        assert set(hit) == HIT_FIELDS


def test_method_picks_one_retriever(client):
    assert {h["retriever"] for h in retrieve(client, text="wetland", method="bm25")} == {"bm25"}
    assert {h["retriever"] for h in retrieve(client, text="wetland", method="dense")} == {"dense"}


def test_k_is_the_number_of_passages_per_retriever(client):
    assert len(retrieve(client, text="wetland", method="dense", k=2)) == 2


@pytest.mark.parametrize("k", [1, 50])
def test_k_accepts_both_ends_of_its_range(client, k):
    # The fixture holds 3 searchable dev passages, so k=50 returns all of them rather than 50.
    hits = retrieve(client, text="wetland", method="dense", k=k, docket_id=DEV_DOCKET)
    assert len(hits) == min(k, 3)


def test_merged_returns_one_ranked_list_of_k_distinct_passages(client):
    hits = retrieve(client, text="ephemeral tributary flow", method="merged", k=2)
    assert [(h["retriever"], h["rank"]) for h in hits] == [("merged", 1), ("merged", 2)]
    assert len({h["id"] for h in hits}) == 2
    assert all(set(h) == HIT_FIELDS for h in hits)
    # Both retrievers rank the flow passage first, so it tops the merged list.
    assert hits[0]["section_ref"] == "III/D"
    assert hits[0]["score"] == round(2 / (RRF_K + 1), 4)


def test_merged_respects_the_docket_filter(client):
    hits = retrieve(client, text="tributary", method="merged", docket_id=TRANSFER_DOCKET)
    assert hits and {h["docket_id"] for h in hits} == {TRANSFER_DOCKET}


def test_docket_id_limits_the_search_to_that_docket(client):
    hits = retrieve(client, text="tributary", docket_id=TRANSFER_DOCKET)
    assert hits and {h["docket_id"] for h in hits} == {TRANSFER_DOCKET}


def test_an_unknown_docket_finds_nothing(client):
    assert retrieve(client, text="tributary", docket_id="NO-SUCH-DOCKET") == []


def test_procedural_passages_are_never_returned(client):
    hits = retrieve(client, text="tributary comments mail", k=10)
    assert hits and "SUMMARY" not in {h["section_ref"] for h in hits}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "   "},
        {"text": "wetland", "k": 0},
        {"text": "wetland", "k": 51},
        {"text": "wetland", "method": "fuzzy"},
        {"text": "x" * 50_001},
    ],
    ids=["missing text", "empty", "blank", "k too small", "k too big", "bad method", "too long"],
)
def test_invalid_requests_are_rejected(client, body):
    assert client.post("/retrieve", json=body).status_code == 422
