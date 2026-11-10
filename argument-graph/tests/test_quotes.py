"""The quote check: normalisation, substring test, fragments."""

from quotes import is_fragment, norm, verified

PASSAGE = (
    "The “deﬁnition” of a lead service line — in § 141.2 — should cover goosenecks. "
    "We ask that EPA clarify this point."
)


def test_norm_folds_quotes_dashes_nbsp_and_ligatures():
    assert norm("“deﬁnition” — here now") == '"definition" - here now'
    assert norm("  Two   spaces\tand\nlines ") == "two spaces and lines"


def test_verified_is_a_substring_test_after_normalising():
    assert verified('The "definition" of a lead service line - in § 141.2 - should cover', PASSAGE)
    assert verified("we ask that EPA clarify this point", PASSAGE)  # case and trailing period
    assert verified('"We ask that EPA clarify this point."', PASSAGE)  # wrapped in quotes
    assert not verified("EPA should define goosenecks as lead service lines", PASSAGE)
    assert not verified("", PASSAGE)
    assert not verified(None, PASSAGE)


def test_fragment_rules():
    assert is_fragment("Recommendation For EPA In Exhibit One Of Our Letter Today")  # heading
    assert is_fragment("six words is too short here")  # fewer than 8 words
    assert is_fragment("§ 141.84(b)(2), 141.85(a), 141.86, 141.90, 141.92, 141.93, 142.14, 142.15")
    assert is_fragment(None)
    assert not is_fragment(
        "Replacing every lead service line in ten years is not feasible for systems with more "
        "than 10,000 lines."
    )
