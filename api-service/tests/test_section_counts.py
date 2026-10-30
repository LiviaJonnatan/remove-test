"""Citation counts on GET /rules/{docket_id}/sections, from passage-stage's links.parquet."""

import logging

from fastapi.testclient import TestClient

from conftest import DEV_DOCKET as WOTUS
from conftest import LEAD, write_links
from main import PassageIndex, create_app


def get_sections(store, passages_dir, docket=LEAD):
    with TestClient(create_app(lambda: PassageIndex(store, passages_dir))) as client:
        response = client.get(f"/rules/{docket}/sections")
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {s["section_ref"]: s for s in body["sections"]}


def counts(section):
    return section["citing_passages"], section["citing_letters"]


def test_counts_are_distinct_passages_and_letters_rolled_up_into_parents(lead_store, tmp_path):
    write_links(tmp_path, LEAD, [
        ("p1", "letter-a", "PART 141/§ 141.84"),
        ("p2", "letter-a", "PART 141/§ 141.84"),
        ("p3", "letter-b", "PART 141/§ 141.85"),
        # One passage citing two sections counts in both, and once in the part above them.
        ("p1", "letter-a", "PART 141/§ 141.85"),
    ])  # fmt: skip
    _, by_ref = get_sections(lead_store, tmp_path)
    assert counts(by_ref["PART 141/§ 141.84"]) == (2, 1)
    assert counts(by_ref["PART 141/§ 141.85"]) == (2, 2)
    assert counts(by_ref["PART 141"]) == (3, 2)


def test_a_section_nobody_cites_is_zero_once_links_exist(lead_store, tmp_path):
    write_links(tmp_path, LEAD, [("p1", "letter-a", "PART 141/§ 141.84")])
    _, by_ref = get_sections(lead_store, tmp_path)
    assert counts(by_ref["V/B"]) == (0, 0)
    assert counts(by_ref["V"]) == (0, 0)


def test_a_repeated_link_counts_once(lead_store, tmp_path):
    # A range ("§ 141.84-141.86") and a direct citation in one passage can both link § 141.85.
    write_links(tmp_path, LEAD, [("p1", "letter-a", "PART 141/§ 141.85")] * 2)
    _, by_ref = get_sections(lead_store, tmp_path)
    assert counts(by_ref["PART 141/§ 141.85"]) == (1, 1)


def test_citations_outside_the_rule_are_reported_not_counted(lead_store, tmp_path):
    write_links(tmp_path, LEAD, [
        ("p1", "letter-a", "PART 141/§ 141.84"),
        ("p2", "letter-b", None),
    ])  # fmt: skip
    body, by_ref = get_sections(lead_store, tmp_path)
    assert body["unresolved_citations"] == 1
    assert counts(by_ref["PART 141"]) == (1, 1)


def test_counts_stay_unknown_for_a_docket_the_passage_stage_has_not_run_on(lead_store, tmp_path):
    write_links(tmp_path, LEAD, [("p1", "letter-a", "PART 141/§ 141.84")])
    body, by_ref = get_sections(lead_store, tmp_path, WOTUS)
    assert body["unresolved_citations"] is None
    assert counts(by_ref["III/D"]) == (None, None)


def test_without_a_passages_folder_every_count_is_unknown(lead_store):
    body, by_ref = get_sections(lead_store, None)
    assert body["unresolved_citations"] is None
    assert {counts(s) for s in by_ref.values()} == {(None, None)}


def test_a_link_to_an_unlisted_section_is_logged_not_fatal(lead_store, tmp_path, caplog):
    write_links(tmp_path, LEAD, [("p1", "letter-a", "PART 141/§ 141.99")])
    with caplog.at_level(logging.WARNING):
        _, by_ref = get_sections(lead_store, tmp_path)
    assert "PART 141/§ 141.99" in caplog.text
    # Its part is listed, so the citation still counts there.
    assert counts(by_ref["PART 141"]) == (1, 1)
