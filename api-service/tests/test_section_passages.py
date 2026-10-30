"""GET /rules/{docket_id}/passages: the comment passages that cite a section."""

import pytest
from fastapi.testclient import TestClient

from conftest import DEV_DOCKET as WOTUS
from conftest import LEAD, write_links, write_passages
from main import PassageIndex, create_app, in_section

INVENTORY = "PART 141/§ 141.84"
EDUCATION = "PART 141/§ 141.85"


@pytest.fixture
def client(lead_store, tmp_path):
    write_links(tmp_path, LEAD, [
        ("b:p002", "letter-b", INVENTORY, "§ 141.84(a)"),
        ("a:p007", "letter-a", INVENTORY, "§ 141.84"),
        ("a:p001", "letter-a", EDUCATION, "§ 141.85"),
        # One passage citing both sections, and a citation outside the rule.
        ("b:p002", "letter-b", EDUCATION, "§ 141.85(b)"),
        ("c:p001", "letter-c", None, "§ 142.99"),
    ])  # fmt: skip
    write_passages(tmp_path, LEAD, [
        ("a:p001", "letter-a", 1),
        ("a:p007", "letter-a", 7),
        ("b:p002", "letter-b", 2),
        ("c:p001", "letter-c", 1),
        ("a:p003", "letter-a", 3),  # cites nothing
    ])  # fmt: skip
    with TestClient(create_app(lambda: PassageIndex(lead_store, tmp_path))) as c:
        yield c


def get_passages(client, section_ref, docket=LEAD, **params):
    params["section_ref"] = section_ref
    response = client.get(f"/rules/{docket}/passages", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids(body):
    return [p["passage_id"] for p in body["passages"]]


def test_lists_a_sections_passages_by_letter_then_position(client):
    body = get_passages(client, INVENTORY)
    assert body["total"] == 2
    assert ids(body) == ["a:p007", "b:p002"]
    first = body["passages"][0]
    assert first["letter_id"] == "letter-a" and first["index"] == 7
    assert first["text"] == "Passage a:p007 text."
    assert first["citations"] == [{"section_ref": INVENTORY, "citation_raw": "§ 141.84"}]


def test_a_parent_lists_its_childrens_passages_once_each(client):
    body = get_passages(client, "PART 141")
    # The same three passages the section counts give PART 141.
    assert ids(body) == ["a:p001", "a:p007", "b:p002"]
    both = body["passages"][2]
    assert both["citations"] == [
        {"section_ref": INVENTORY, "citation_raw": "§ 141.84(a)"},
        {"section_ref": EDUCATION, "citation_raw": "§ 141.85(b)"},
    ]


def test_pages_with_limit_and_offset_and_reports_the_full_total(client):
    body = get_passages(client, "PART 141", limit=2, offset=1)
    assert body["total"] == 3
    assert ids(body) == ["a:p007", "b:p002"]


def test_a_section_nobody_cites_has_no_passages(client):
    body = get_passages(client, "V/B")
    assert body["total"] == 0 and body["passages"] == []


def test_passages_stay_unknown_for_a_docket_the_passage_stage_has_not_run_on(client):
    body = get_passages(client, "III/D", docket=WOTUS)
    assert body["total"] is None and body["passages"] is None


@pytest.mark.parametrize(
    ("docket", "params", "status"),
    [
        (LEAD, {"section_ref": "PART 141/§ 141.99"}, 404),
        ("EPA-HQ-NOPE", {"section_ref": "PART 141"}, 404),
        (LEAD, {}, 422),
        (LEAD, {"section_ref": "PART 141", "limit": 0}, 422),
        (LEAD, {"section_ref": "PART 141", "limit": 201}, 422),
    ],
)
def test_bad_requests_are_rejected(client, docket, params, status):
    assert client.get(f"/rules/{docket}/passages", params=params).status_code == status


def test_a_ref_only_matches_whole_levels():
    assert in_section("PART 141/§ 141.84", "PART 141")
    assert not in_section("PART 141/§ 141.84", "PART 14")
    assert not in_section(None, "PART 141")
