"""The citation reader: the three families, lists, and what it must not match."""

from citations import find_citations, mask


def numbers(text, rule=None):
    return [(c.number, c.family) for c in find_citations(text, rule)]


def test_section_sign_and_word():
    assert numbers("We oppose § 141.84(b)(2) as written.") == [("141.84", "R1_sign")]
    assert numbers("Section 141.85 should allow mail.") == [("141.85", "R1_section")]
    assert numbers("see sec. 141.2") == [("141.2", "R1_section")]


def test_cfr_reference():
    assert numbers("Under 40 CFR 141.85(a), systems must ...") == [("141.85", "R2_cfr")]
    assert numbers("40 C.F.R. § 141.2 defines it") == [("141.2", "R2_cfr")]


def test_a_list_gives_one_citation_per_section():
    found = find_citations("Sections 141.84 and 141.85, and § 141.86(d)")
    assert [c.number for c in found] == ["141.84", "141.85", "141.86"]


def test_bare_number_only_counts_for_a_section_of_the_rule():
    text = "The requirement in 141.84(a) and the one in 330.5(b)."
    assert numbers(text) == []  # no rule given, no bare matches
    assert numbers(text, {"141.84"}) == [("141.84", "R3_bare")]


def test_raw_text_is_the_citation_as_written():
    (cite,) = find_citations("We ask EPA to revise § 141.84(b)(2) now.")
    assert cite.raw == "§ 141.84(b)(2)"


def test_numbers_that_are_not_citations():
    text = "It costs $1.5 million, a 15.5% increase, on 1.2 million lines, version 2.0 of the plan."
    assert numbers(text, {"141.84", "1.5", "15.5", "1.2", "2.0"}) == []


def test_the_word_section_in_capitals_is_matched():
    # Organization letters often put citations in all-caps headings.
    assert numbers("SECTION 141.84 SERVICE LINE INVENTORY") == [("141.84", "R1_section")]
    assert numbers("SEC. 141.85 PUBLIC EDUCATION") == [("141.85", "R1_section")]


def test_a_measurement_after_to_is_not_a_second_citation():
    found = find_citations("lowering the action level in 40 CFR 141.80(c) to 0.010 mg/L")
    assert [c.number for c in found] == ["141.80"]


def test_a_later_number_from_another_part_counts_if_it_is_a_rule_section():
    found = find_citations("§§ 141.84 and 142.16", {"141.84", "142.16"})
    assert [c.number for c in found] == ["141.84", "142.16"]


def test_a_range_marks_its_end():
    found = find_citations("§ 141.80–141.93 and §§ 141.84 through 141.86")
    assert [(c.number, c.range_end) for c in found] == [
        ("141.80", False),
        ("141.93", True),
        ("141.84", False),
        ("141.86", True),
    ]
    assert [c.range_end for c in find_citations("Sections 141.84 and 141.85")] == [False, False]


def test_mask_removes_every_citation():
    text = "We oppose § 141.84(b) and § 141.84(c), and 40 CFR 141.85 too."
    masked = mask(text, find_citations(text))
    assert "141" not in masked
    assert masked.count("[citation removed]") == 3


def test_mask_also_hides_bare_rule_section_numbers():
    # PDF extraction can garble "Section" into "Sec\ufffdon", which no citation pattern matches.
    text = "Define these terms in Sec\ufffdon 141.2, and in 141.90(e) too. It costs $141.2 billion."
    masked = mask(text, find_citations(text), {"141.2", "141.90", "141.202"})
    assert "141.2," not in masked and "141.90" not in masked
    assert masked.count("[citation removed]") == 2
    assert "141.202" not in mask("see 141.202 now", [], {"141.2", "141.202"})
