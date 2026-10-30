"""Grouping behavior and the saved pipeline contract."""

import pandas as pd
import pytest

from minhash_grouping import group_minhash, main, representative_tables

BASE = " ".join(f"word{i}" for i in range(120))


def frame(texts):
    return pd.DataFrame({"letter_id": [f"id{i:03}" for i in range(len(texts))], "text": texts})


def test_near_copies_counts_and_singletons():
    letters = frame(
        [
            BASE,
            BASE.upper(),
            BASE + " please act now",
            "completely unrelated " * 30,
            "See attached",
            "",
            None,
        ]
    )
    assignments = group_minhash(letters)
    assert assignments.campaign_id.iloc[:3].tolist() == ["id000"] * 3
    assert assignments.campaign_id.iloc[3:].isna().all()
    assert assignments.similarity.iloc[2] >= 0.8
    campaigns, representatives = representative_tables(letters, assignments)
    assert campaigns.n_letters.tolist() == [3]
    assert representatives.n_letters.sum() == len(letters)
    assert len(representatives) == 5
    assert assignments.letter_id.tolist() == letters.letter_id.tolist()


def test_input_order_does_not_change_membership():
    letters = frame([BASE, BASE + " additional words", BASE, "unrelated " * 30])
    left = group_minhash(letters).sort_values("letter_id").reset_index(drop=True)
    right = group_minhash(letters.sample(frac=1, random_state=4))
    pd.testing.assert_frame_equal(left, right.sort_values("letter_id").reset_index(drop=True))


def test_candidate_verification_and_no_transitive_chains(monkeypatch):
    # Force every representative to be a candidate, isolating exact verification
    # from LSH's probabilistic retrieval. A-B and B-C pass; A-C does not.
    calls = iter([[], ["id000"], ["id000"]])
    monkeypatch.setattr("minhash_grouping.MinHashLSH.query", lambda self, sig: next(calls))
    a = " ".join(f"t{i}" for i in range(40))
    b = " ".join(f"t{i}" for i in range(10, 50))
    c = " ".join(f"t{i}" for i in range(20, 60))
    assignments = group_minhash(frame([a, b, c]), threshold=0.5, shingle_size=1)
    assert assignments.campaign_id.iloc[:2].tolist() == ["id000", "id000"]
    assert pd.isna(assignments.campaign_id.iloc[2])


def test_empty_input_and_duplicate_ids():
    letters = frame([])
    result = group_minhash(letters)
    campaigns, representatives = representative_tables(letters, result)
    assert result.empty and campaigns.empty and representatives.empty
    letters = frame([BASE, BASE])
    letters["letter_id"] = "duplicate"
    with pytest.raises(ValueError, match="unique"):
        group_minhash(letters)


@pytest.mark.parametrize(
    "kwargs",
    [{"threshold": 1}, {"threshold": 0}, {"num_perm": 1}, {"shingle_size": 0}, {"min_words": 0}],
)
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        group_minhash(frame([BASE]), **kwargs)


def test_multiple_dockets_rejected():
    letters = frame([BASE, BASE])
    letters["docket_id"] = ["D1", "D2"]
    with pytest.raises(ValueError, match="docket"):
        group_minhash(letters)


def test_cli_writes_counts_and_scores(tmp_path, capsys):
    letters = frame([BASE, BASE, "unrelated " * 30])
    letters["epa_campaign_id"] = ["epa1", "epa1", None]
    path = tmp_path / "letters.parquet"
    letters.to_parquet(path)
    out = tmp_path / "out"
    assert main(["--letters", str(path), "--out-dir", str(out), "--score"]) == 0
    assert pd.read_parquet(out / "campaigns.parquet").n_letters.tolist() == [2]
    assert len(pd.read_parquet(out / "assignments.parquet")) == 3
    assert pd.read_parquet(out / "representatives.parquet").n_letters.sum() == 3
    assert "B-cubed" in capsys.readouterr().out


def test_container_entrypoint_minhash(tmp_path):
    from main import build_docket

    folder = tmp_path / "derived/letters/D1"
    folder.mkdir(parents=True)
    frame([BASE, BASE + " extra words"]).to_parquet(folder / "letters.parquet")
    assert build_docket("D1", tmp_path, method="minhash")
    out = tmp_path / "derived/campaigns/D1"
    assert pd.read_parquet(out / "assignments.parquet").method.tolist() == ["minhash"] * 2
    assert pd.read_parquet(out / "representatives.parquet").n_letters.tolist() == [2]
