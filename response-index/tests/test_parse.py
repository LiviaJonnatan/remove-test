"""Parsing the response-to-comments layout, on a small page shaped like the LCRI document."""

from locate import locate
from parse import parse, references

DOC = """\
                                   Table of Contents
1       General Matters.................................................... 1-1
    1.1 General Comments .................................................. 1-1
    5.9.2 Action Level .................................................... 5-185
Response to Public Comments on the Lead and Copper Rule Improvements          October 2024
                                                                                  xxxii
1       General Matters
1.1 General Comments

EPA Response to Comment Code 1.1

The EPA appreciates the comments submitted by the public.
Pennsylvania Section, American Water Works Association (PA-
AWWA) (Doc. #0800, SBC-048531)
We support the proposed rule but ask for more time.
         EPA Response: Please see the EPA response to comment code 1.1 in this Response
to Comments document.


Response to Public Comments on the Lead and Copper Rule Improvements          October 2024
Topic 1. General Matters                                                              1-2
5.9.2   Action Level

EPA Response to Comment Code 5.9.2

The EPA is lowering the action level to 0.010 mg/L.
Mass Comment Campaign sponsored by Natural Resources Defense Council (NRDC). (web) (Doc.
#1378, SBC-052000)
Lower the action level to 5 ppb.
EPA Response: Please see the EPA responses to comment codes 9.2, 9.7, and 9.8 in this
Response to Comments document.
Plastic Pollution Coalition (Doc. #2268.0002, SBC-052118)
Ban plastic pipes.
"""


def test_codes_and_summaries():
    codes, _ = parse(DOC)
    assert [c.code for c in codes] == ["1.1", "5.9.2"]
    assert codes[1].title == "Action Level"
    assert " ".join(" ".join(codes[0].summary).split()) == (
        "The EPA appreciates the comments submitted by the public."
    )


def test_entries_with_wrapped_names_and_headers():
    _, entries = parse(DOC)
    assert [(e.code, e.doc_number) for e in entries] == [
        ("1.1", 800),
        ("5.9.2", 1378),
        ("5.9.2", 2268),
    ]
    assert (
        entries[0].organization
        == "Pennsylvania Section, American Water Works Association (PA-AWWA)"
    )
    assert entries[1].organization.startswith("Mass Comment Campaign sponsored by")
    assert entries[1].sbc == "SBC-052000" and entries[1].page == "1-2"
    assert entries[2].part == 2 and entries[2].response is None


def test_excerpt_and_response_split_without_page_furniture():
    _, entries = parse(DOC)
    excerpt = " ".join(" ".join(entries[0].excerpt).split())
    response = " ".join(" ".join(entries[0].response).split())
    assert excerpt == "We support the proposed rule but ask for more time."
    assert response.startswith("Please see the EPA response to comment code 1.1")
    assert "Response to Public Comments on the Lead" not in response
    assert "5.9.2" not in response  # the next heading belongs to no entry


def test_references_singular_and_plural():
    assert references("see the EPA response to comment code 1.4 in this document") == ["1.4"]
    assert references("see the EPA responses to comment codes 9.2, 9.7, and 9.8") == [
        "9.2",
        "9.7",
        "9.8",
    ]
    assert references("see section 9.11 in this Response to Comments document") == ["9.11"]
    assert references("see section IV.G of the final LCRI preamble") == []
    assert references(None) == []


def test_locate_ignores_layout_differences():
    letter = (
        "Dear Administrator,\n\nThe proposed rule should require water systems to replace "
        "lead service lines within ten years, and it should fund the work.\nThank you."
    )
    excerpt = (
        "The proposed rule should require water sys-\ntems to replace lead service lines within "
        "ten years, and it should fund the work."
    )
    found = locate(excerpt, letter)
    assert found["share"] == 1.0
    assert letter[found["start"] : found["end"]].startswith("The proposed rule")
    assert letter[found["start"] : found["end"]].endswith("fund the work")


def test_locate_reports_text_not_in_letter():
    found = locate("A sentence about something else entirely, not in the letter.", "Lead pipes.")
    assert found["share"] == 0.0 and found["start"] is None
