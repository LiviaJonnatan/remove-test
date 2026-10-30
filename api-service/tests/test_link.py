"""POST /link: a comment passage in, the rule's regulatory sections ranked by the linker out."""

import pytest
from fastapi.testclient import TestClient

from conftest import LEAD, PART, FakeEmbedder, make_chunk
from linker import SectionLinker
from main import PassageIndex, create_app

INFO = {"run": "test", "commit": "abc1234", "margin_cutoff": 0.05, "query_prefix": ""}


def lead(index, text, ref, heading, procedural=False):
    return make_chunk(index, text, docket=LEAD, doc="2023-26148", ref=ref, heading=heading,
                      procedural=procedural)


@pytest.fixture
def chunks():
    return [
        lead(0, "Wetland permit rules.", "PART 141/§ 141.84", f"{PART} > § 141.84 Inventory."),
        lead(1, "More wetland text.", "PART 141/§ 141.84", f"{PART} > § 141.84 Inventory."),
        lead(2, "Ditch and farm notices.", "PART 141/§ 141.85", f"{PART} > § 141.85 Education."),
        lead(3, "Tributary sampling.", "PART 141/§ 141.86", f"{PART} > § 141.86 Monitoring."),
        # Preamble and procedural text are never linked: the model was trained on CFR sections.
        lead(4, "Wetland wetland wetland.", "V/B", "V. Proposed Revisions > B. Replacement"),
        lead(5, "Wetland comments by mail.", "PART 141/§ 141.84", "Addresses", procedural=True),
    ]


@pytest.fixture
def client(store, chunks):
    store.upsert(chunks)
    linker = lambda cs: SectionLinker(cs, FakeEmbedder(), INFO)  # noqa: E731
    app = create_app(lambda: PassageIndex(store), linker)
    with TestClient(app) as client:
        yield client


def link(client, **body):
    response = client.post("/link", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_link_ranks_regulatory_sections_with_the_matching_rule_text(client):
    out = link(client, text="A wetland permit question.", docket_id=LEAD, k=3)
    refs = [s["section_ref"] for s in out["sections"]]
    assert refs[0] == "PART 141/§ 141.84"
    assert set(refs) == {"PART 141/§ 141.84", "PART 141/§ 141.85", "PART 141/§ 141.86"}
    assert [s["rank"] for s in out["sections"]] == [1, 2, 3]
    assert out["sections"][0]["evidence"]["text"] in {"Wetland permit rules.", "More wetland text."}
    assert out["model"]["run"] == "test"


def test_preamble_and_procedural_text_are_never_linked(client):
    out = link(client, text="wetland", docket_id=LEAD, k=10)
    assert all("§" in s["section_ref"] for s in out["sections"])
    assert len(out["sections"]) == 3


def test_a_clear_answer_is_not_sent_to_the_reader_and_a_tie_is(client):
    clear = link(client, text="wetland permit", docket_id=LEAD)
    assert clear["margin"] > 0.05 and clear["needs_reader"] is False
    tie = link(client, text="nothing the vocabulary knows", docket_id=LEAD)
    assert tie["margin"] == 0 and tie["needs_reader"] is True


def test_a_docket_without_regulatory_sections_is_a_404(client):
    response = client.post("/link", json={"text": "wetland", "docket_id": "EPA-HQ-OW-2018-0149"})
    assert response.status_code == 404
    assert LEAD in response.json()["detail"]


def test_blank_text_and_a_missing_docket_are_rejected(client):
    assert client.post("/link", json={"text": "  ", "docket_id": LEAD}).status_code == 422
    assert client.post("/link", json={"text": "wetland"}).status_code == 422


def test_without_a_model_link_is_a_503_and_health_says_so(store, chunks):
    store.upsert(chunks)
    with TestClient(create_app(lambda: PassageIndex(store), lambda cs: None)) as client:
        assert client.post("/link", json={"text": "wetland", "docket_id": LEAD}).status_code == 503
        assert client.get("/health").json()["linker"] is None


def test_stats_counts_requests_and_errors_per_route(client):
    link(client, text="wetland", docket_id=LEAD)
    client.post("/link", json={"text": "wetland", "docket_id": "nope"})
    stats = client.get("/stats").json()
    assert stats["POST /link"]["requests"] == 2
    assert stats["POST /link"]["server_errors"] == 0
    assert stats["POST /link"]["p50_ms"] is not None


def test_each_request_is_one_json_log_line_without_the_text(client, capsys):
    import json

    link(client, text="secret wetland passage", docket_id=LEAD)
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    entry = next(x for x in lines if x["route"] == "/link")
    assert entry["status"] == 200 and entry["severity"] == "INFO" and entry["latency_ms"] >= 0
    assert "secret" not in json.dumps(lines)
