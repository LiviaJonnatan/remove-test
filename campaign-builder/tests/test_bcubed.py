"""Hand-worked examples for the B-cubed scorer."""

import pandas as pd
import pytest

from bcubed import bcubed, score_frames


def test_worked_example():
    # Six letters. Gold campaigns A and B; letter f is an individual comment (no gold).
    # Our grouper made groups 1 and 2.
    #
    #   letter  gold  predicted
    #   a       A     1
    #   b       A     1
    #   c       A     2
    #   d       B     2
    #   e       B     2
    #   f       None  1
    #
    # Group 1 = {a, b, f}, group 2 = {c, d, e}. Campaign A = {a, b, c}, campaign B = {d, e}.
    # f is not scored (no gold) but is still a member of group 1.
    #
    #   a: precision 2/3 (a, b of {a, b, f} are A)   recall 2/3 (a, b of {a, b, c} are in group 1)
    #   b: precision 2/3                              recall 2/3
    #   c: precision 1/3 (only c of {c, d, e} is A)   recall 1/3 (only c of {a, b, c} is in group 2)
    #   d: precision 2/3 (d, e of {c, d, e} are B)    recall 2/2 = 1
    #   e: precision 2/3                              recall 1
    #
    #   precision = (2/3 + 2/3 + 1/3 + 2/3 + 2/3) / 5 = (9/3) / 5 = 3/5 = 0.6
    #   recall    = (2/3 + 2/3 + 1/3 + 1 + 1) / 5     = (11/3) / 5 = 11/15 = 0.7333...
    #   f1        = 2 * 0.6 * (11/15) / (0.6 + 11/15) = 0.66
    gold = {"a": "A", "b": "A", "c": "A", "d": "B", "e": "B", "f": None}
    predicted = {"a": "1", "b": "1", "c": "2", "d": "2", "e": "2", "f": "1"}

    scores = bcubed(predicted, gold)

    assert scores.n_scored == 5
    assert scores.precision == pytest.approx(0.6)
    assert scores.recall == pytest.approx(11 / 15)
    assert scores.f1 == pytest.approx(0.66)


def test_perfect_grouping_scores_one():
    gold = {"a": "A", "b": "A", "c": "B"}
    predicted = {"a": "1", "b": "1", "c": "2"}
    scores = bcubed(predicted, gold)
    assert (scores.precision, scores.recall, scores.f1) == (1.0, 1.0, 1.0)


def test_everything_in_one_group_has_full_recall_but_low_precision():
    # Two campaigns of two letters, all lumped together: recall 1, precision 2/4 for each letter.
    gold = {"a": "A", "b": "A", "c": "B", "d": "B"}
    predicted = {"a": "1", "b": "1", "c": "1", "d": "1"}
    scores = bcubed(predicted, gold)
    assert scores.recall == 1.0
    assert scores.precision == pytest.approx(0.5)


def test_every_letter_alone_has_full_precision_but_low_recall():
    gold = {"a": "A", "b": "A", "c": "B", "d": "B"}
    predicted = {"a": "1", "b": "2", "c": "3", "d": "4"}
    scores = bcubed(predicted, gold)
    assert scores.precision == 1.0
    assert scores.recall == pytest.approx(0.5)


def test_none_prediction_is_a_group_of_one():
    # Letters b and c both got no group. They must not be lumped together as one "None" group:
    # if they were, b's precision would be 1/2, not 1.
    gold = {"a": "A", "b": "A", "c": "B"}
    predicted = {"a": "1", "b": None, "c": None}
    scores = bcubed(predicted, gold)
    assert scores.precision == 1.0
    # a: recall 1/2, b: recall 1/2, c: recall 1 -> mean 2/3
    assert scores.recall == pytest.approx(2 / 3)


def test_no_gold_at_all_is_an_error():
    with pytest.raises(ValueError, match="nothing to score"):
        bcubed({"a": "1"}, {"a": None})


def test_gold_letter_missing_from_predictions_is_an_error():
    with pytest.raises(ValueError, match="no prediction"):
        bcubed({"a": "1"}, {"a": "A", "b": "A"})


def test_score_frames_reads_the_schema_columns():
    # Same as the worked example, through the two parquet-shaped tables.
    letters = pd.DataFrame(
        {
            "letter_id": ["a", "b", "c", "d", "e", "f"],
            "epa_campaign_id": ["A", "A", "A", "B", "B", None],
        }
    )
    assignments = pd.DataFrame(
        {
            "letter_id": ["a", "b", "c", "d", "e", "f"],
            "campaign_id": ["1", "1", "2", "2", "2", "1"],
        }
    )
    scores = score_frames(assignments, letters)
    assert scores.precision == pytest.approx(0.6)
    assert scores.recall == pytest.approx(11 / 15)
