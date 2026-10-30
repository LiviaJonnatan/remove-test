"""Exact-match grouping: the simplest campaign baseline.

Two letters are in the same group when their text is identical after normalizing: HTML tags
from the API removed, case and punctuation ignored, whitespace collapsed. A letter that matches
no other letter is an individual comment and gets no group (campaign_id is None).

Letters shorter than MIN_WORDS are never grouped. Empty bodies, and bodies that only say "See
attached", all normalize to the same few words and would otherwise come out as one campaign.

Reads the schema's letters.parquet (letter_id, text, and epa_campaign_id if EPA grouped it).
Writes the schema's assignments.parquet: letter_id, campaign_id, method, similarity.

    python src/exact_match.py --letters letters.parquet --out assignments.parquet

Add --score to also print B-cubed against epa_campaign_id.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path

import pandas as pd

from bcubed import score_frames

HTML_TAG = re.compile(r"<[^>]+>")
NOT_LETTER_OR_SPACE = re.compile(r"[^a-z0-9\s]")
WHITESPACE = re.compile(r"\s+")

# A form letter is at least a paragraph. Shorter texts ("See attached", "", "No") are not
# campaigns even when many letters share them.
MIN_WORDS = 20


def normalize(text: str) -> str:
    """The form of a letter that exact match compares.

    Comment bodies arrive as HTML ("<br/>", "&amp;"), and the same form letter can differ in
    case, punctuation and spacing between submissions. None of that is a different letter.
    """
    text = HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    text = text.lower()
    text = NOT_LETTER_OR_SPACE.sub("", text)
    text = WHITESPACE.sub(" ", text)
    return text.strip()


def group_exact(letters: pd.DataFrame, min_words: int = MIN_WORDS) -> pd.DataFrame:
    """One row per letter: the group it is in, or None if its text matches no other letter.

    A letter with fewer than `min_words` words after normalizing is an individual comment
    whatever it matches. A group is named after its earliest letter_id, so the name is stable
    across runs.
    """
    campaign_of: dict[str, str | None] = {}

    # Which letters share each normalized text. The hash is only to keep the dict keys short.
    letters_with_text: dict[str, list[str]] = {}
    for letter_id, text in zip(letters["letter_id"], letters["text"], strict=True):
        if not isinstance(text, str):  # a missing body comes through pandas as NaN
            text = ""
        normalized = normalize(text)
        if len(normalized.split()) < min_words:
            campaign_of[letter_id] = None  # too short to be a form letter
            continue
        key = hashlib.sha1(normalized.encode()).hexdigest()
        letters_with_text.setdefault(key, []).append(letter_id)

    for members in letters_with_text.values():
        if len(members) == 1:
            campaign_of[members[0]] = None  # an individual comment
            continue
        name = min(members)
        for letter_id in members:
            campaign_of[letter_id] = name

    return pd.DataFrame(
        {
            "letter_id": list(letters["letter_id"]),
            "campaign_id": [campaign_of[letter_id] for letter_id in letters["letter_id"]],
            "method": "exact",
            "similarity": 1.0,
        }
    )


def summarize(assignments: pd.DataFrame) -> str:
    """One line for the log: how many letters, groups and individual comments."""
    grouped = assignments["campaign_id"].notna()
    n_groups = assignments.loc[grouped, "campaign_id"].nunique()
    return (
        f"{len(assignments)} letters: {grouped.sum()} in {n_groups} exact-match groups, "
        f"{(~grouped).sum()} individual"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--letters", required=True, help="letters.parquet")
    parser.add_argument("--out", required=True, help="where to write assignments.parquet")
    parser.add_argument("--score", action="store_true", help="print B-cubed vs epa_campaign_id")
    parser.add_argument(
        "--min-words", type=int, default=MIN_WORDS, help="letters shorter than this stay ungrouped"
    )
    args = parser.parse_args(argv)

    letters = pd.read_parquet(args.letters)
    assignments = group_exact(letters, min_words=args.min_words)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(args.out, index=False)
    print(summarize(assignments))

    if args.score:
        scores = score_frames(assignments, letters)
        print(
            f"B-cubed on {scores.n_scored} labeled letters: "
            f"precision {scores.precision:.3f}  recall {scores.recall:.3f}  f1 {scores.f1:.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
