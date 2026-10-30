"""Containment grouping: personalized form letters, and the cases that must stay apart."""

import pandas as pd
import pytest

from containment import containment, core_without, group_containment
from exact_match import normalize
from minhash_grouping import group_minhash, shingles

TEMPLATE = " ".join(f"template{i}" for i in range(150))


def personal(i: int, words: int = 90) -> str:
    """What one sender adds: words no other letter uses."""
    return " ".join(f"sender{i}x{j}" for j in range(words))


def frame(texts: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"letter_id": [f"id{i:03}" for i in range(len(texts))], "text": texts})


def test_personalized_letters_group_where_jaccard_does_not():
    # Each letter is the template plus 90 words of its own: Jaccard between two is about 0.45,
    # containment about 0.6.
    letters = frame([TEMPLATE + " " + personal(i) for i in range(6)])
    grouped = group_containment(letters)
    assert grouped["campaign_id"].tolist() == ["id000"] * 6
    assert grouped["similarity"].iloc[1:].between(0.5, 1).all()
    assert group_minhash(letters, threshold=0.8)["campaign_id"].isna().all()


def test_unrelated_letters_stay_apart_even_with_shared_boilerplate():
    boiler = "thank you for the opportunity to comment on the proposed rule"
    letters = frame([boiler + " " + personal(i, 150) for i in range(5)])
    assert group_containment(letters)["campaign_id"].isna().all()


def test_a_long_letter_that_reprints_a_campaign_does_not_join_it():
    exhibit = " ".join([personal(99, 400), TEMPLATE, personal(98, 400)])  # 950 words around it
    letters = frame([TEMPLATE + " " + personal(0), TEMPLATE + " " + personal(1), exhibit])
    grouped = group_containment(letters)
    assert grouped["campaign_id"].tolist()[:2] == ["id000", "id000"]
    assert pd.isna(grouped["campaign_id"].iloc[2])


def test_two_campaigns_are_not_joined_through_a_letter_that_mixes_them():
    other = " ".join(f"second{i}" for i in range(150))
    half = " ".join(TEMPLATE.split()[:75] + other.split()[:75])
    letters = frame(
        [TEMPLATE, TEMPLATE + " " + personal(1), other, other + " " + personal(2), half]
    )
    grouped = group_containment(letters).set_index("letter_id")["campaign_id"]
    assert grouped["id000"] == grouped["id001"] == "id000"
    assert grouped["id002"] == grouped["id003"] == "id002"
    # The mixed letter joins at most one campaign and never merges the two.
    assert pd.isna(grouped["id004"]) or grouped["id004"] in ("id000", "id002")


def test_exact_copies_short_letters_and_empty_text():
    letters = frame([TEMPLATE, TEMPLATE.upper(), "See attached", "", None])
    grouped = group_containment(letters)
    assert grouped["campaign_id"].tolist()[:2] == ["id000", "id000"]
    assert grouped["campaign_id"].iloc[2:].isna().all()
    assert grouped["similarity"].tolist()[:2] == [1.0, 1.0]


def test_input_order_does_not_change_membership():
    texts = [TEMPLATE + " " + personal(i) for i in range(4)] + [personal(9, 150)]
    forward = group_containment(frame(texts)).sort_values("letter_id").reset_index(drop=True)
    shuffled = frame(texts).sample(frac=1, random_state=3)
    backward = group_containment(shuffled).sort_values("letter_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(forward, backward)


def test_bad_input_is_rejected():
    with pytest.raises(ValueError):
        group_containment(frame([TEMPLATE]), threshold=0)
    with pytest.raises(ValueError):
        group_containment(pd.DataFrame({"letter_id": ["a", "a"], "text": [TEMPLATE, TEMPLATE]}))


def test_small_groups_do_not_chain_into_an_unrelated_campaign():
    # A short campaign, a long one, and middle-sized letters that each share part of both. Merging
    # everything connected at once joined the short campaign to the long one through the middle.
    short = " ".join(f"short{i}" for i in range(40))
    long_ = " ".join(f"long{i}" for i in range(200))
    middle = " ".join(short.split()[:30] + long_.split()[:40])
    texts = [short + " " + personal(i, 10) for i in range(3)]
    texts += [middle + " " + personal(10 + i, 10) for i in range(3)]
    texts += [long_ + " " + personal(20 + i, 60) for i in range(4)]
    grouped = group_containment(frame(texts))["campaign_id"]
    assert grouped.iloc[:3].nunique() == 1 and grouped.iloc[6:].nunique() == 1
    assert grouped.iloc[0] != grouped.iloc[6]


def words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def assert_every_member_fits_the_others(letters: pd.DataFrame, grouped: pd.DataFrame) -> None:
    sets = {
        lid: shingles(normalize(text))
        for lid, text in zip(letters.letter_id, letters.text, strict=True)
    }
    for _, members in grouped.dropna(subset=["campaign_id"]).groupby("campaign_id"):
        group = list(members.letter_id)
        assert len(group) >= 2
        for lid, similarity in zip(members.letter_id, members.similarity, strict=True):
            others = core_without(group, lid, sets)
            assert similarity == round(containment(sets[lid], others), 4) >= 0.5


def test_containment_divides_by_the_smaller_set():
    assert containment({"a", "b"}, {"a", "b", "c", "d"}) == 1.0
    assert containment({"a", "b", "c", "d"}, {"a", "e"}) == 0.5
    assert containment(set(), {"a"}) == 0.0


def test_every_grouped_letter_fits_the_template_of_the_others():
    texts = [TEMPLATE + " " + personal(i, 20 + 15 * i) for i in range(8)]
    texts += [" ".join(TEMPLATE.split()[:100]) + " " + personal(50 + i) for i in range(4)]
    letters = frame(texts)
    grouped = group_containment(letters)
    assert grouped["campaign_id"].notna().sum() >= 8
    assert_every_member_fits_the_others(letters, grouped)


def test_a_letter_does_not_join_a_pair_through_one_members_own_words():
    # A and B share the template. C shares only B's own 100 words. Taking a pair's template as
    # everything either letter has let C in; it is the phrases both have.
    own = words("bonly", 100)
    letters = frame(
        [TEMPLATE + " " + personal(1, 60), TEMPLATE + " " + own, own + " " + personal(3, 60)]
    )
    grouped = group_containment(letters)
    assert grouped["campaign_id"].tolist()[:2] == ["id000", "id000"]
    assert pd.isna(grouped["campaign_id"].iloc[2])
    # A pair's similarity is the containment between its two letters, not 1.0 for both.
    assert grouped["similarity"].iloc[0] == grouped["similarity"].iloc[1] < 0.9
    assert_every_member_fits_the_others(letters, grouped)


def test_two_letters_are_not_joined_through_a_third_that_shares_a_little_with_each():
    # X holds U and V. Y shares only U with it, Z only V. Y and Z share nothing.
    u, v = words("upart", 100), words("vpart", 100)
    letters = frame([u + " " + v, u + " " + personal(1, 60), v + " " + personal(2, 60)])
    assert group_containment(letters)["campaign_id"].tolist()[:2] == ["id000", "id000"]
    assert pd.isna(group_containment(letters)["campaign_id"].iloc[2])


def test_a_variant_that_fit_the_early_template_is_split_off_and_regrouped():
    # Three early letters share the first 60 words of the template and 40 words of their own, and
    # nine later ones the whole template. The later letters fit the early group's template and join
    # it, the template becomes the full one, and the early three no longer fit it (0.41). They are
    # dropped, and then grouped among themselves.
    variant = " ".join(TEMPLATE.split()[:60]) + " " + words("variant", 40)
    texts = [variant + " " + personal(i, 40) for i in range(3)]
    texts += [TEMPLATE + " " + personal(10 + i, 30) for i in range(9)]
    letters = frame(texts)
    grouped = group_containment(letters)
    campaigns = grouped["campaign_id"]
    assert campaigns.iloc[:3].notna().all() and campaigns.iloc[:3].nunique() == 1
    assert campaigns.iloc[3:].notna().all() and campaigns.iloc[3:].nunique() == 1
    assert campaigns.iloc[0] != campaigns.iloc[3]
    assert_every_member_fits_the_others(letters, grouped)


def test_a_member_must_fit_what_the_others_share_not_a_template_its_own_words_help_make():
    # X has the template and 100 words of its own; Y has the template and a block S; Z has 80
    # words of the template and S. With all three counted, the template plus S is the core, and X
    # fits it. Without X, the core is Y and Z's shared text, of which X holds 0.43.
    block = words("block", 100)
    letters = frame(
        [
            TEMPLATE + " " + personal(0, 100),
            TEMPLATE + " " + block,
            " ".join(TEMPLATE.split()[:80]) + " " + block,
        ]
    )
    assert_every_member_fits_the_others(letters, group_containment(letters))


@pytest.mark.parametrize(("first", "second"), [(10, 10), (10, 30)])
def test_a_letter_holding_two_templates_does_not_bridge_their_campaigns(first, second):
    # The earliest letter carries both campaigns' templates. Comparing later letters with it, rather
    # than with a template the group shares, joined both campaigns into one group of 21; with 10 and
    # 30 the smaller campaign was pruned and left ungrouped.
    one, two = words("first", 150), words("second", 150)
    texts = [one + " " + two]
    texts += [one + " " + personal(i, 30) for i in range(first)]
    texts += [two + " " + personal(100 + i, 30) for i in range(second)]
    letters = frame(texts)
    grouped = group_containment(letters)
    campaigns = grouped["campaign_id"]
    a, b = campaigns.iloc[1 : 1 + first], campaigns.iloc[1 + first :]
    assert a.notna().all() and a.nunique() == 1
    assert b.notna().all() and b.nunique() == 1
    assert a.iloc[0] != b.iloc[0]
    assert_every_member_fits_the_others(letters, grouped)


def test_a_campaign_the_first_pass_splits_is_rejoined_by_its_template():
    # Letters 0 and 1 each add 200 words of their own, so they do not fit each other (0.42).
    # Letter 2 shares letter 1's first words and joins it; letter 3 joins letter 0. Only merging
    # the two groups by their templates (0.88) makes one campaign.
    own0, own1 = personal(0, 200), personal(1, 200)
    first20 = lambda own: " ".join(own.split()[:20])  # noqa: E731
    letters = frame(
        [
            TEMPLATE + " " + own0,
            TEMPLATE + " " + own1,
            TEMPLATE + " " + first20(own1),
            TEMPLATE + " " + first20(own0),
        ]
    )
    grouped = group_containment(letters)
    assert grouped["campaign_id"].notna().all() and grouped["campaign_id"].nunique() == 1


def test_a_letter_left_out_of_the_first_pass_joins_the_template_it_fits():
    # Letter 1 does not fit letter 0 (0.42), and the letters after it join letter 0's group.
    # It fits that group's template, which is all it shares with letter 0.
    letters = frame(
        [TEMPLATE + " " + personal(0, 200), TEMPLATE + " " + personal(1, 200)]
        + [TEMPLATE + " " + personal(i, 10) for i in (2, 3)]
    )
    grouped = group_containment(letters)
    assert grouped["campaign_id"].tolist() == ["id000"] * 4


def test_a_group_is_named_after_the_member_holding_the_most_of_its_template():
    # The earliest letter has only the first 100 of the template's 150 words.
    short = " ".join(TEMPLATE.split()[:100])
    letters = frame(
        [short + " " + personal(0, 20)] + [TEMPLATE + " " + personal(i, 20) for i in (1, 2, 3, 4)]
    )
    assert group_containment(letters)["campaign_id"].tolist() == ["id001"] * 5


def test_input_order_does_not_change_a_result_that_depends_on_order():
    # Taken in this order, X groups with Y and Z is left out; taken as Z, X, Y, X would go with Z.
    u, v = words("upart", 100), words("vpart", 100)
    texts = [u + " " + v, u + " " + personal(1, 60), v + " " + personal(2, 60)]
    forward = group_containment(frame(texts)).sort_values("letter_id").reset_index(drop=True)
    for seed in range(3):
        shuffled = frame(texts).sample(frac=1, random_state=seed)
        backward = group_containment(shuffled).sort_values("letter_id").reset_index(drop=True)
        pd.testing.assert_frame_equal(forward, backward)
    assert forward["campaign_id"].tolist()[:2] == ["id000", "id000"]
