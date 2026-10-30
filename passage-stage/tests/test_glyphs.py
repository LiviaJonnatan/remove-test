"""Repairing letter pairs that PDF extraction lost (glyphs.py)."""

from collections import Counter

import pytest

from glyphs import repair, repair_word, spell_out_ligatures, vocabulary

L = "�"
KNOWN = vocabulary(
    ["After the action, often a draft. Setting time. Straightforward association, definition."]
)


@pytest.mark.parametrize(
    ("damaged", "whole"),
    [
        (f"Associa{L}on", "Association"),  # ti
        (f"a{L}er", "after"),  # ft, because "after" is a word the letters use
        (f"se{L}ng", "Setting".lower()),  # tti
        (f"straigh{L}orward", "straightforward"),  # tf
        (f"{L}me", "time"),  # at the start of a word
        (f"Sec{L}on", "Section"),  # ti when no candidate is known: the most common pair
        (f"defini{L}on", "definition"),
    ],
)
def test_each_lost_pair_is_restored(damaged, whole):
    assert repair_word(damaged, KNOWN) == whole


def test_two_lost_pairs_in_one_word_are_chosen_separately():
    known = Counter({"aftertime": 3})
    assert repair_word(f"a{L}er{L}me", known) == "aftertime"


def test_unknown_words_fall_back_to_ti():
    assert repair_word(f"zz{L}zz", Counter()) == "zztizz"


def test_a_lost_glyph_on_its_own_is_left_alone():
    # A bullet or symbol that did not decode, not part of a word.
    text, changed = repair(f"Inventory {L} Service lines", KNOWN)
    assert text == f"Inventory {L} Service lines" and changed == 0


def test_repair_counts_the_words_it_changed_and_cites_become_readable():
    text, changed = repair(f"See Sec{L}on 141.84 a{L}er the ac{L}on.", KNOWN)
    assert text == "See Section 141.84 after the action."
    assert changed == 3


def test_typographic_ligatures_are_spelled_out():
    assert spell_out_ligatures("deﬁnition, eﬀect, oﬃce") == "definition, effect, office"
    assert repair("deﬁnition", Counter()) == ("definition", 0)


def test_undamaged_text_is_unchanged():
    text = "Lead service lines, § 141.84(b)(2), 15 ppb."
    assert repair(text, KNOWN) == (text, 0)


def test_the_vocabulary_ignores_damaged_words():
    assert f"associa{L}on" not in vocabulary([f"Associa{L}on"])
    assert vocabulary(["deﬁnition"])["definition"] == 1


def test_a_letter_whose_damaged_words_mostly_do_not_resolve_is_left_alone():
    # A lost apostrophe or another font's "fi", not Calibri's ligatures.
    text = f"EPA{L}s rule. The agency{L}s view. De{L}ne the scope."
    assert repair(text, KNOWN) == (text, 0)


def test_most_damaged_words_resolving_is_enough_to_repair_all_of_them():
    # "action" and "after" are known, "Section" is not; it still gets the "ti" fallback.
    assert repair(f"Sec{L}on, a{L}er, ac{L}on", KNOWN) == ("Section, after, action", 3)


def test_symbol_font_letters_are_not_turned_into_bullets():
    # In Symbol, U+F06D draws μ and U+F0B3 draws ≥: only code points seen as bullets are mapped.
    text = "15 \uf06dg/L, \uf0b3 10 ppb"
    assert spell_out_ligatures(text) == text


def test_word_symbol_font_bullets_become_bullets():
    text = "listed below.  Clarify the definition  and the scope"
    assert spell_out_ligatures(text) == "listed below. • Clarify the definition • and the scope"
