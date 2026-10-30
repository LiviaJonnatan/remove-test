"""B-cubed precision, recall and F1 for a campaign grouping.

B-cubed scores a grouping letter by letter and averages, so a big campaign counts for more than
a small one, which is what we want: getting a 60,000-letter campaign wrong matters more than
getting a 3-letter one wrong.

For one letter L:
  precision(L) = share of the letters in L's predicted group that have the same gold campaign as L
  recall(L)    = share of the letters in L's gold campaign that are in the same predicted group as L
Both include L itself, so a letter alone in both is 1.0 and 1.0.

Precision and recall for the grouping are the means over scored letters. F1 is the harmonic
mean of those two means.

Which letters are scored:
  - A letter whose gold campaign is None (an individual comment, nothing to check against) is
    not scored. It still counts as a member of its predicted group when scoring other letters,
    because the grouper did put it there.
  - A letter whose predicted group is None (the grouper matched it with nothing) is treated as
    a group of one.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Scores:
    precision: float
    recall: float
    f1: float
    n_scored: int  # letters with a gold campaign, i.e. the ones the means are over


def bcubed(predicted: dict[str, str | None], gold: dict[str, str | None]) -> Scores:
    """Score a grouping.

    predicted: letter_id -> the group our grouper put it in, or None for no group
    gold:      letter_id -> the campaign EPA put it in, or None when EPA did not group it
    Every letter in `gold` must also be in `predicted`.
    """
    missing = [letter for letter in gold if letter not in predicted]
    if missing:
        raise ValueError(f"{len(missing)} gold letters have no prediction, e.g. {missing[0]!r}")

    # A letter with no predicted group is a group of itself. Give it a private group name.
    predicted_group = {}
    for letter, group in predicted.items():
        predicted_group[letter] = group if group is not None else f"single:{letter}"

    # Members of every predicted group and every gold campaign.
    members_of_predicted: dict[str, set[str]] = {}
    for letter, group in predicted_group.items():
        members_of_predicted.setdefault(group, set()).add(letter)

    members_of_gold: dict[str, set[str]] = {}
    for letter, campaign in gold.items():
        if campaign is not None:
            members_of_gold.setdefault(campaign, set()).add(letter)

    scored = [letter for letter in predicted_group if gold.get(letter) is not None]
    if not scored:
        raise ValueError("no letter has a gold campaign, so there is nothing to score")

    precision_sum = 0.0
    recall_sum = 0.0
    for letter in scored:
        my_campaign = gold[letter]
        my_group = members_of_predicted[predicted_group[letter]]
        my_campaign_members = members_of_gold[my_campaign]

        # Of the letters grouped with me, how many truly belong to my campaign?
        same_campaign_in_group = sum(1 for other in my_group if gold.get(other) == my_campaign)
        precision_sum += same_campaign_in_group / len(my_group)

        # Of the letters truly in my campaign, how many were grouped with me?
        in_my_group = sum(1 for other in my_campaign_members if other in my_group)
        recall_sum += in_my_group / len(my_campaign_members)

    precision = precision_sum / len(scored)
    recall = recall_sum / len(scored)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return Scores(precision, recall, f1, len(scored))


def score_frames(assignments: pd.DataFrame, letters: pd.DataFrame) -> Scores:
    """Score an assignments table against the letters table it was built from.

    assignments: the schema's assignments.parquet, columns letter_id and campaign_id
    letters:     the schema's letters.parquet, columns letter_id and epa_campaign_id
    """
    predicted = _column_as_dict(assignments, "campaign_id")
    gold = _column_as_dict(letters, "epa_campaign_id")
    return bcubed(predicted, gold)


def _column_as_dict(frame: pd.DataFrame, column: str) -> dict[str, str | None]:
    """letter_id -> value, with pandas missing values turned into None."""
    result = {}
    for letter_id, value in zip(frame["letter_id"], frame[column], strict=True):
        result[letter_id] = None if pd.isna(value) else value
    return result
