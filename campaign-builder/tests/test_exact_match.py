"""The grouper on a handful of letters whose groups are known."""

import pandas as pd

from exact_match import group_exact, main, normalize, summarize

# A form letter long enough to group (MIN_WORDS is 20; this is 27 words).
TEMPLATE = (
    "Please protect our streams and wetlands. Don't repeal the Clean Water Rule! "
    "Clean water is not a partisan issue, and every family in this state depends on it."
)


def test_normalize_ignores_markup_case_punctuation_and_spacing():
    variants = [
        TEMPLATE,
        TEMPLATE.lower(),
        TEMPLATE.replace("! ", "!<br/><br/>").replace("Don't", "Don’t").replace("  ", " "),
        TEMPLATE.replace("streams and wetlands", "streams &amp; wetlands"),
    ]
    normalized = {normalize(v) for v in variants}
    # The "&amp;" variant says "and" differently, so it is a different letter.
    assert len(normalized) == 2
    assert normalize(variants[0]) == normalize(variants[1]) == normalize(variants[2])


def test_group_exact_groups_copies_and_leaves_singletons_alone():
    letters = pd.DataFrame(
        {
            "letter_id": ["0005", "0002", "0009", "0003"],
            "text": [
                TEMPLATE,
                TEMPLATE.upper(),
                "I kayak and fish near Hampton, VA, and I oppose this rule.",
                TEMPLATE + "<br/>",
            ],
        }
    )
    assignments = group_exact(letters)

    assert list(assignments.columns) == ["letter_id", "campaign_id", "method", "similarity"]
    by_id = dict(zip(assignments["letter_id"], assignments["campaign_id"], strict=True))
    # The three copies share one group, named after the earliest id among them.
    assert by_id["0005"] == by_id["0002"] == by_id["0003"] == "0002"
    # The unrelated letter is an individual comment. pandas stores a missing string as NaN.
    assert pd.isna(by_id["0009"])
    assert set(assignments["method"]) == {"exact"}
    assert set(assignments["similarity"]) == {1.0}


def test_group_exact_keeps_input_order():
    letters = pd.DataFrame({"letter_id": ["b", "a"], "text": ["x", "y"]})
    assert list(group_exact(letters)["letter_id"]) == ["b", "a"]


def test_short_and_empty_texts_are_never_grouped():
    # Two empty bodies and two "See attached" bodies are identical after normalizing, but a
    # shared stub is not a campaign (#40). They all stay individual comments.
    letters = pd.DataFrame(
        {
            "letter_id": ["a", "b", "c", "d"],
            "text": [None, "", "See attached.", "<p>See attached</p>"],
        }
    )
    assignments = group_exact(letters)
    assert assignments["campaign_id"].isna().all()


def test_min_words_is_a_threshold_on_the_normalized_text():
    # Nineteen words stay apart; the same text with one more word groups.
    nineteen = " ".join(["word"] * 19)
    twenty = nineteen + " more"
    letters = pd.DataFrame(
        {"letter_id": ["a", "b", "c", "d"], "text": [nineteen, nineteen, twenty, twenty]}
    )
    assignments = group_exact(letters)
    assert assignments["campaign_id"].isna().tolist() == [True, True, False, False]
    assert assignments["campaign_id"].tolist()[2:] == ["c", "c"]
    # The threshold can be lowered, which is what --min-words does.
    assert group_exact(letters, min_words=1)["campaign_id"].tolist() == ["a", "a", "c", "c"]


def test_summarize_counts():
    assignments = pd.DataFrame({"letter_id": ["a", "b", "c"], "campaign_id": ["a", "a", None]})
    assert summarize(assignments) == "3 letters: 2 in 1 exact-match groups, 1 individual"


def test_main_writes_assignments_and_scores(tmp_path, capsys):
    letters = pd.DataFrame(
        {
            "letter_id": ["a", "b", "c"],
            "text": [TEMPLATE, TEMPLATE, "something else"],
            "epa_campaign_id": ["A", "A", None],
        }
    )
    letters_path = tmp_path / "letters.parquet"
    out_path = tmp_path / "assignments.parquet"
    letters.to_parquet(letters_path, index=False)

    assert main(["--letters", str(letters_path), "--out", str(out_path), "--score"]) == 0

    written = pd.read_parquet(out_path)
    assert written["campaign_id"].tolist()[:2] == ["a", "a"]
    assert pd.isna(written["campaign_id"][2])
    printed = capsys.readouterr().out
    assert "3 letters: 2 in 1 exact-match groups, 1 individual" in printed
    assert "precision 1.000  recall 1.000  f1 1.000" in printed


def test_main_creates_the_output_folder(tmp_path):
    letters_path = tmp_path / "letters.parquet"
    pd.DataFrame({"letter_id": ["a"], "text": [TEMPLATE]}).to_parquet(letters_path, index=False)
    out_path = tmp_path / "campaigns" / "D" / "assignments.parquet"

    assert main(["--letters", str(letters_path), "--out", str(out_path)]) == 0
    assert out_path.exists()
