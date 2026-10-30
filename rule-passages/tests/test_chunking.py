from __future__ import annotations

from rule_passages.chunking import (
    MIN_WORDS,
    Heading,
    Paragraph,
    chunk_document,
    clean_markup,
    is_procedural,
    pack,
    parse_paragraphs,
    split_sentences,
)


def test_clean_markup_strips_html_and_latex_quotes():
    raw = "<pre>the term ``waters of the United States'' <a href=\"x\">www.epa.gov</a> &amp; more"
    assert clean_markup(raw) == "the term “waters of the United States” www.epa.gov & more"


def test_clean_markup_keeps_less_than_and_greater_than_in_the_text():
    # The lead and copper proposal: a bare "<" before a number and a later ">" once read as one
    # tag, and everything between them was deleted.
    raw = (
        "For systems serving <1,000 people, see below.\n\n"
        "Sec.  141.82  Description of corrosion control treatment requirements.\n\n"
        "A system with a P90 > 0.010 mg/L must act. Lead <INF>x</INF> stays."
    )
    text = clean_markup(raw)
    assert "Sec.  141.82  Description" in text
    assert "serving <1,000 people" in text and "P90 > 0.010" in text
    assert "Lead x stays." in text


def test_clean_markup_keeps_gpo_symbols():
    assert clean_markup("plan elements:\n    <bullet> a list") == "plan elements:\n    • a list"
    assert clean_markup("level <ls-thn-eq> 0.005") == "level ≤ 0.005"


def test_clean_markup_turns_line_break_tags_into_newlines_not_nothing():
    assert (
        clean_markup("ditch<br/>on my farm<br />Thanks</p>Bye") == "ditch\non my farm\nThanks\nBye"
    )


def test_table_of_contents_is_dropped(raw_excerpt):
    texts = [p.text for p in parse_paragraphs(raw_excerpt)]
    assert not any("Table of Contents" in t for t in texts)
    assert not any(t.startswith("B. Under what legal authority") for t in texts)


# The layout of the lead and copper proposal (2023-26148): the contents list has no title, starts
# right after the label, and a page marker splits it.
UNTITLED_CONTENTS = """SUMMARY: EPA proposes changes to the lead and copper rule.

SUPPLEMENTARY INFORMATION:

I. Executive Summary
II. Public Participation
    A. Written Comments
    B. Participation in a Virtual Public Hearing

[[Page 84879]]

    C. Previous Opportunities for Public Engagement

I. Executive Summary

    EPA is proposing to require the replacement of lead service lines.

II. Public Participation

A. Written Comments

    Submit your comments by the deadline.
"""


def test_an_untitled_table_of_contents_is_dropped():
    paragraphs = parse_paragraphs(UNTITLED_CONTENTS)
    paths = ["/".join(h.ref for h in p.path) for p in paragraphs]
    assert paths == ["SUMMARY", "I", "II/A"]
    assert paragraphs[1].text.startswith("EPA is proposing")
    assert paragraphs[1].path[0].title == "I. Executive Summary"


def test_a_heading_right_after_a_page_marker_starts_a_new_section():
    raw = (
        "SUMMARY: A proposal.\n\n"
        "V. Definitions\n\n"
        "    EPA is seeking comment on all aspects of the \nproposed definitions.\n\n"
        "[[Page 84967]]\n\n"
        "VI. Rule Areas for Which EPA Is Not Proposing Revisions\n\n"
        "    EPA is not proposing changes to these areas.\n"
    )
    paragraphs = parse_paragraphs(raw)
    assert [p.path[-1].ref for p in paragraphs] == ["SUMMARY", "V", "VI"]
    assert paragraphs[1].text.endswith("proposed definitions.")
    assert paragraphs[2].page == 84967


def test_a_marker_like_line_mid_sentence_still_continues_the_paragraph():
    raw = (
        "SUMMARY: A proposal.\n\n"
        "    Systems must follow the steps in paragraph\n\n"
        "[[Page 12]]\n\n"
        "B. of this section and report\nthe results.\n"
    )
    (para,) = [p for p in parse_paragraphs(raw) if "Systems must" in p.text]
    assert para.text.endswith("paragraph B. of this section and report the results.")


def test_front_matter_before_the_summary_is_skipped(raw_excerpt):
    assert not any("Department of Defense" in p.text for p in parse_paragraphs(raw_excerpt))


def test_preamble_labels_become_sections_and_agency_is_dropped(raw_excerpt):
    refs = {"/".join(h.ref for h in p.path) for p in parse_paragraphs(raw_excerpt)}
    assert {"SUMMARY", "DATES", "ADDRESSES"} <= refs
    assert not any(r.startswith(("AGENCY", "ACTION")) for r in refs)


def test_page_marker_inside_a_sentence_does_not_split_the_paragraph(raw_excerpt):
    paragraphs = parse_paragraphs(raw_excerpt)
    (para,) = [p for p in paragraphs if "creating a new website" in p.text]
    assert "provide information on the rulemaking. See" in para.text
    assert "[[Page" not in para.text


def test_pages_come_from_the_last_marker_before_a_paragraph(raw_excerpt):
    pages = {p.path[-1].ref: p.page for p in parse_paragraphs(raw_excerpt) if p.path}
    assert pages["D"] == 4153  # begins before the 4163 marker
    assert pages["1"] == 4163  # begins after it


def test_roman_i_and_letter_i_are_told_apart(raw_excerpt):
    refs = [[h.ref for h in p.path] for p in parse_paragraphs(raw_excerpt)]
    assert ["I", "A"] in refs  # roman I, then letter A
    assert ["I", "I"] in refs  # roman I, then letter I


def test_cfr_part_and_section_headings(raw_excerpt):
    refs = {"/".join(h.ref for h in p.path) for p in parse_paragraphs(raw_excerpt)}
    assert "PART 328" in refs
    assert "PART 328/§ 328.3" in refs


def test_amendatory_instructions_are_not_headings(raw_excerpt):
    (para,) = [p for p in parse_paragraphs(raw_excerpt) if "authority citation for part" in p.text]
    assert [h.ref for h in para.path] == ["PART 328"]
    assert not para.text.startswith("0 ")


def test_sentences_do_not_split_on_abbreviations_or_initials():
    text = "The rule cites 33 U.S.C. 1251 et seq. in full. The agencies disagree with J. Smith."
    assert split_sentences(text) == [
        "The rule cites 33 U.S.C. 1251 et seq. in full.",
        "The agencies disagree with J. Smith.",
    ]


def _paragraph(n_sentences: int, words_each: int = 10, page: int = 1) -> Paragraph:
    sentences = [
        " ".join(f"W{i}x{j}" for j in range(words_each - 1)) + "." for i in range(n_sentences)
    ]
    return Paragraph(" ".join(sentences), (), page)


def test_pack_keeps_chunks_near_the_limit_and_loses_nothing():
    chunks = pack([_paragraph(40)], max_words=100, overlap_words=0)
    assert all(len(text.split()) <= 100 + MIN_WORDS for text, _ in chunks)
    joined = " ".join(text for text, _ in chunks).split()
    assert joined == _paragraph(40).text.split()


def test_pack_repeats_the_closing_sentence_at_the_start_of_the_next_chunk():
    chunks = pack([_paragraph(40)], max_words=100, overlap_words=10)
    first, second = chunks[0][0], chunks[1][0]
    closing_sentence = split_sentences(first)[-1]
    assert second.startswith(closing_sentence)


def test_pack_folds_a_short_remainder_into_the_previous_chunk():
    chunks = pack([_paragraph(11)], max_words=100, overlap_words=0)
    assert len(chunks) == 1  # 110 words, the last 10 are a stub


def test_pack_joins_pieces_of_a_paragraph_with_spaces_and_paragraphs_with_newlines():
    chunks = pack([_paragraph(4), _paragraph(4)], max_words=200, overlap_words=0)
    ((text, _),) = chunks
    assert text.count("\n") == 1
    assert "\n" not in text.split("\n")[0]


def test_pack_splits_a_single_oversized_sentence_by_words():
    long = Paragraph(" ".join(f"w{i}" for i in range(450)) + ".", (), 1)
    chunks = pack([long], max_words=200, overlap_words=0)
    assert [len(t.split()) for t, _ in chunks] == [200, 200, 50]


def test_chunks_carry_their_section_and_start_page(document):
    chunks = chunk_document(document, max_words=80, overlap_words=10)
    wetlands = [c for c in chunks if c.section_ref == "I/H/1"]
    assert wetlands and wetlands[0].page == 4163
    assert wetlands[0].heading == (
        "I. General Information > H. Waters and Features That Are Not Waters of the United States"
        " > 1. What are the agencies proposing?"
    )


def test_chunk_ids_are_unique_ordered_and_stable(document):
    first = chunk_document(document)
    again = chunk_document(document)
    assert [c.id for c in first] == [c.id for c in again]
    assert len({c.id for c in first}) == len(first)
    assert first[0].id == "2019-00791:0000"


def test_embed_text_puts_the_heading_before_the_passage(document):
    chunk = chunk_document(document)[0]
    assert chunk.embed_text == f"{chunk.heading}\n{chunk.text}"


def test_preamble_and_general_information_sections_are_flagged_in_the_fixture(document):
    flagged = {c.section_ref: c.procedural for c in chunk_document(document)}
    assert flagged["SUMMARY"] and flagged["DATES"] and flagged["ADDRESSES"]
    assert flagged["I/A"]  # how to get copies of the document, under General Information
    assert not flagged["PART 328/§ 328.3"]  # the regulatory text itself


def test_is_procedural_on_headings_from_the_real_rules():
    def path(*titles: str) -> tuple[Heading, ...]:
        return tuple(Heading(i + 1, t.split(".")[0], t) for i, t in enumerate(titles))

    assert is_procedural(path("I. General Information", "C. How should I submit comments?"))
    assert is_procedural(path("II. Public Hearing", "A. Participation in Public Hearing"))
    assert not is_procedural(path("II. Background", "D. Summary of Stakeholder Outreach"))
    assert not is_procedural(path("III. Proposed Definition", "G. Wetlands"))
    assert not is_procedural(path("PART 328--DEFINITION OF WATERS OF THE UNITED STATES"))
