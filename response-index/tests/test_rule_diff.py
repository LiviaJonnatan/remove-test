"""Aligning proposed and final regulatory text, on two short documents shaped like the LCRI."""

from rule_diff import diff, sections, word_diff

PROPOSED = """\
Preamble text that mentions Sec.  141.84 is not regulation.
PART 141--NATIONAL PRIMARY DRINKING WATER REGULATIONS

0
8. Revise Sec.  141.84 to read as follows:


Sec.  141.84  Service line inventory and replacement requirements.

    (a) Inventory. All water systems must develop an inventory.
    (b) Deferral. A system may defer if replacements per household
served exceed 0.039, as described in
Sec.  141.86 of this chapter.
    (c) Removed later. This paragraph does not survive.

[[Page 1]]

* * * * *
    (d) * * *
"""

FINAL = """\
PART 141--NATIONAL PRIMARY DRINKING WATER REGULATIONS

0
8. Revise Sec.  141.84 to read as follows:


Sec.  141.84   Service line inventory and replacement requirements.

    (a) Inventory. All water systems must develop an inventory.
    (b) Deferral. A system may defer if replacements exceed 39 per 1,000
service connections, as described in
Sec.  141.86 of this chapter.
    (e) New. Systems must report < 0.010 mg/L results > annually.
"""


def test_sections_skip_instructions_placeholders_and_references():
    secs = sections(PROPOSED)
    assert list(secs) == ["141.84"]  # the wrapped "Sec.  141.86 of" is not a heading
    title, paragraphs = secs["141.84"]
    assert title.startswith("Service line inventory")
    assert [p[:3] for p in paragraphs] == ["(a)", "(b)", "(c)"]
    assert paragraphs[1].endswith("Sec. 141.86 of this chapter.")


def test_less_than_sign_is_not_a_tag():
    _, paragraphs = sections(FINAL)["141.84"]
    assert "< 0.010 mg/L results > annually" in paragraphs[-1]


def test_alignment_ops_and_word_diff():
    rows = diff(PROPOSED, FINAL)
    assert [(r.marker, r.op) for r in rows] == [
        ("(a)", "unchanged"),
        ("(b)", "modified"),
        ("(c)", "removed"),
        ("(e)", "added"),
    ]
    assert rows[1].diff == (
        "(b) Deferral. A system may defer if replacements {+exceed 39+} per "
        "[-household served exceed 0.039,-] {+1,000 service connections,+} as described in "
        "Sec. 141.86 of this chapter."
    )


def test_word_diff_marks():
    assert word_diff("a b c", "a x c") == "a [-b-] {+x+} c"
