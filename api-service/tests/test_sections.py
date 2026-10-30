"""GET /rules/{docket_id}/sections: the rule's sections, in reading order, for the rule page."""

import pytest
from fastapi.testclient import TestClient

from conftest import DEV_DOCKET, make_chunk
from main import PassageIndex, create_app

TRANSFER_DOCKET = "EPA-HQ-OAR-2017-0355"
# The fields the rule page reads; this pins the contract from the API's side.
SECTION_FIELDS = {
    "document_number", "citation", "section_ref", "parent_ref", "heading", "title", "depth",
    "page", "rule_passages", "citing_passages", "citing_letters",
}  # fmt: skip
FLOW = "III. Proposed Definition > D. Tributaries"
WETLANDS = "III. Proposed Definition > G. Adjacent Wetlands"
PART = "PART 328--DEFINITION OF WATERS OF THE UNITED STATES"
DEFINITIONS = f"{PART} > Sec. 328.3 Definitions."


@pytest.fixture
def client(store):
    # Upserted out of order on purpose: the endpoint must sort by position in the document.
    # "III" has no text of its own; "PART 328" has one passage before its subsection.
    store.upsert([
        make_chunk(3, "Wetland adjacency.", ref="III/G", heading=WETLANDS),
        make_chunk(1, "Tributary flow.", ref="III/D", heading=FLOW),
        make_chunk(2, "Ephemeral streams.", ref="III/D", heading=FLOW),
        make_chunk(0, "Send comments by mail.", ref="SUMMARY", heading="Summary", procedural=True),
        make_chunk(5, "Waters of the United States means...", ref="PART 328/§ 328.3",
                   heading=DEFINITIONS),
        make_chunk(4, "Authority: 33 U.S.C. 1251.", ref="PART 328", heading=PART),
        make_chunk(0, "Power plants.", docket=TRANSFER_DOCKET, doc="2017-22349", ref="II/A",
                   heading="II. Background > A. Power"),
    ])  # fmt: skip
    with TestClient(create_app(lambda: PassageIndex(store))) as client:
        yield client


def sections(client, docket_id=DEV_DOCKET):
    response = client.get(f"/rules/{docket_id}/sections")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["docket_id"] == docket_id
    return body["sections"]


def by_ref(client):
    return {s["section_ref"]: s for s in sections(client)}


def test_sections_come_in_reading_order_parents_before_children(client):
    assert [s["section_ref"] for s in sections(client)] == [
        "III", "III/D", "III/G", "PART 328", "PART 328/§ 328.3",
    ]  # fmt: skip


def test_each_section_carries_what_the_rule_page_shows(client):
    flow = by_ref(client)["III/D"]
    assert set(flow) == SECTION_FIELDS
    assert flow["heading"] == FLOW
    assert (flow["title"], flow["depth"], flow["parent_ref"]) == ("D. Tributaries", 2, "III")
    # A section's page is where its first passage starts.
    assert flow["page"] == 4171
    assert (flow["document_number"], flow["citation"]) == ("2019-00791", "84 FR 4154")


def test_a_parent_with_no_text_of_its_own_still_gets_an_entry(client):
    top = by_ref(client)["III"]
    assert (top["heading"], top["title"]) == ("III. Proposed Definition",) * 2
    assert (top["depth"], top["parent_ref"]) == (1, None)
    # Its first child's page, and its children's passages rolled up.
    assert (top["page"], top["rule_passages"]) == (4171, 3)


def test_a_parent_with_text_of_its_own_is_listed_once_and_counts_both(client):
    found = sections(client)
    assert [s["section_ref"] for s in found].count("PART 328") == 1
    part, definitions = by_ref(client)["PART 328"], by_ref(client)["PART 328/§ 328.3"]
    assert part["rule_passages"] == 2
    assert (definitions["rule_passages"], definitions["parent_ref"]) == (1, "PART 328")


def test_a_chunk_whose_ref_and_heading_disagree_is_listed_alone(store):
    # Two ref levels but one heading: no parent is guessed, and the API still starts.
    store.upsert([make_chunk(0, "Flow.", ref="III/D", heading="D. Flow")])
    with TestClient(create_app(lambda: PassageIndex(store))) as client:
        [only] = sections(client)
    assert (only["section_ref"], only["parent_ref"], only["title"]) == ("III/D", "III", "D. Flow")


def test_procedural_sections_are_left_out(client):
    assert "SUMMARY" not in by_ref(client)


def test_each_docket_lists_only_its_own_rule(client):
    assert [s["section_ref"] for s in sections(client, TRANSFER_DOCKET)] == ["II", "II/A"]


def test_citation_counts_are_unknown_until_the_passage_stage_exists(client):
    for section in sections(client):
        assert section["citing_passages"] is None
        assert section["citing_letters"] is None


def test_an_unknown_docket_is_a_404_that_names_the_indexed_dockets(client):
    response = client.get("/rules/NO-SUCH-DOCKET/sections")
    assert response.status_code == 404
    assert DEV_DOCKET in response.json()["detail"]
