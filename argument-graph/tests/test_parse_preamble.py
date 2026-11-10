"""The label parser on a 300-line excerpt of the LCRI final rule (2024-23549, lines 3700-3999)."""

from pathlib import Path

import parse_preamble as pp

EXCERPT = Path(__file__).resolve().parent / "fixtures" / "preamble_excerpt.txt"


def test_headings_in_the_excerpt():
    lines = pp.clean_lines(EXCERPT.read_text())
    heads = pp.find_headings(lines)
    assert [(h.enum, h.text[:30], h.level) for h in heads] == [
        ("b", "Summary of Public Comments and", "lower"),
        ("c", "Final Rule Requirements", "lower"),
        ("3", "Service Lines Under the Contro", "digit"),
        ("a", "Rationale and Proposed LCRI Re", "lower"),
    ]


def test_one_block_is_cut_at_the_next_heading_of_the_same_level():
    _, blocks, points = pp.parse(EXCERPT.read_text(), {"B01": ["141.84"]})
    assert len(blocks) == 1
    b = blocks[0]
    assert (b.heading_line, b.end) == (30, 207)  # 1-based lines of "b." and "c." in the excerpt
    assert b.section_refs == ["PART 141/§ 141.84"] and b.section_source == "hand_map"
    assert b.paragraphs == 7
    assert b.final_text.startswith("The final LCRI requires water systems to conduct full")
    assert points and all(p["block"] == "B01" for p in points)
    assert len(b.point_ids) == len(points)
    first = points[0]
    assert first["text"].startswith("Many commenters supported the proposed requirement")
    assert first["has_explicit_response"] is True  # "After consideration of all the comments"
    assert first["catch_all"] is False


def test_paragraph_classes_and_point_cut():
    assert pp.classify("The EPA received many comments on connectors.") == "summary"
    assert pp.classify("Some commenters supported the proposal because it is clear.") == "summary"
    assert pp.classify("One commenter noted the cost.") == "summary"
    assert pp.classify("The EPA disagrees with commenters that suggested an exclusion.") == (
        "response"
    )
    assert pp.classify("In the final rule, the EPA is requiring replacement.") == "response"
    assert pp.classify("As discussed in section IV.B, the proposal covered connectors.") == "other"
    para = (
        "Many commenters supported the proposed requirement to replace every line. A few "
        "commenters stated that corrosion control is effective and so replacement should not "
        "be required. After consideration of all the comments, the agency is requiring full "
        "replacement in the final rule."
    )
    sentences, explicit = pp.points_of(para)
    assert explicit is True
    assert len(sentences) == 2
    assert sentences[1].startswith("A few commenters stated")
    sentences, explicit = pp.points_of("Commenters asked for more time to build inventories.")
    assert (len(sentences), explicit) == (1, False)


def test_cut_uses_every_response_opener_but_not_summary_sentences():
    # "The EPA also received ..." is what commenters said; "The EPA also intends ..." is the answer.
    para = (
        "Commenters asked that the agency exclude closed school buildings from sampling. The EPA "
        "also received comments requesting clarification about child care facilities in homes. "
        "The EPA also intends to provide updated templates to assist water systems with this. "
        "The EPA has determined that the exclusion is not needed in the final rule."
    )
    sentences, explicit = pp.points_of(para)
    assert explicit is True
    assert [s[:20] for s in sentences] == ["Commenters asked tha", "The EPA also receive"]
    for opener in ("The EPA recognizes", "The EPA is finalizing", "The EPA has", "The EPA also"):
        assert pp.is_response_sentence(f"{opener} something about the rule.")
    assert not pp.is_response_sentence("The EPA also heard from States about the burden.")
    assert pp.is_response_sentence("In addition, the EPA has already provided templates.")
    assert pp.is_response_sentence("Therefore, the EPA is retaining the option.")
    assert not pp.is_response_sentence("The EPA proposed that systems replace lines.")
    assert not pp.is_response_sentence("The EPA's proposal drew many comments.")
    assert pp.classify("The EPA also received comments on connectors.") == "summary"


def test_response_in_the_next_paragraph_counts():
    assert pp.response_follows(["summary", "response"], 0)
    assert pp.response_follows(["summary", "other", "response"], 0)
    assert not pp.response_follows(["summary", "summary", "response"], 0)  # the next point's
    assert not pp.response_follows(["summary", "other", "other", "response"], 0)  # too far
    assert not pp.response_follows(["summary"], 0)
    _, _, points = pp.parse(EXCERPT.read_text(), {"B01": ["141.84"]})
    where = {p["response_where"] for p in points}
    assert where <= {"same_paragraph", "next_paragraph", "none"}
    assert all(p["has_explicit_response"] == (p["response_where"] != "none") for p in points)


def test_leveller_tells_letters_from_numerals():
    lv = pp.Leveller()
    assert [lv.level(e) for e in ("I", "A", "1", "a", "i", "ii", "b", "B", "H", "I", "J")] == [
        "roman", "upper", "digit", "lower", "roman_lower", "roman_lower", "lower", "upper",
        "upper", "upper", "upper",
    ]  # fmt: skip
    lv = pp.Leveller()
    assert [lv.level(e) for e in ("1", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j")][-2:] == [
        "lower", "lower"
    ]
