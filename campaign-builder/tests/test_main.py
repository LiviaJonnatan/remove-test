"""The container's default command: letters in, assignments out, at the schema's paths."""

import hashlib
import json

import pandas as pd

import main as m

LETTER = (
    "Please protect our drinking water. Lead pipes should be replaced within ten years, "
    "and every family in this state deserves to know what is in their tap."
)


def write_letters(data_dir, docket, rows):
    folder = data_dir / "derived" / "letters" / docket
    folder.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(folder / "letters.parquet", index=False)


def test_build_docket_writes_assignments_where_the_schema_says(tmp_path, capsys):
    rows = {"letter_id": ["a", "b", "c"], "text": [LETTER, LETTER, "A different comment."]}
    write_letters(tmp_path, "D-1", rows)

    assert m.build_docket("D-1", tmp_path, method="exact") is True

    written = pd.read_parquet(tmp_path / "derived" / "campaigns" / "D-1" / "assignments.parquet")
    assert written["campaign_id"].tolist()[:2] == ["a", "a"]
    assert pd.isna(written["campaign_id"][2])
    assert "[D-1] 3 letters: 2 in 1 exact-match groups, 1 individual" in capsys.readouterr().out


def test_build_docket_scores_only_when_epa_grouped_some_letters(tmp_path, capsys):
    rows = {"letter_id": ["a", "b"], "text": [LETTER, LETTER], "epa_campaign_id": [None, None]}
    write_letters(tmp_path, "D-1", rows)
    assert m.build_docket("D-1", tmp_path) is True
    assert "B-cubed" not in capsys.readouterr().out

    rows["epa_campaign_id"] = ["A", "A"]
    write_letters(tmp_path, "D-2", rows)
    assert m.build_docket("D-2", tmp_path) is True
    assert "B-cubed on 2 labeled letters" in capsys.readouterr().out


def test_empty_letters_fail_the_stage(tmp_path):
    write_letters(tmp_path, "D-1", {"letter_id": [], "text": []})
    assert m.build_docket("D-1", tmp_path) is False
    assert not (tmp_path / "derived" / "campaigns" / "D-1").exists()  # nothing written


def test_missing_letters_fail_the_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_IDS", "D-1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert m.main() == 1  # compose stops the chain here instead of serving nothing


def test_summary_records_counts_score_and_the_input_it_read(tmp_path):
    rows = {
        "letter_id": ["a", "b", "c"],
        "text": [LETTER, LETTER, "A different comment."],
        "epa_campaign_id": ["A", "A", None],
    }
    write_letters(tmp_path, "D-1", rows)
    assert m.build_docket("D-1", tmp_path, method="exact") is True

    summary = json.loads((tmp_path / "derived" / "campaigns" / "D-1" / "summary.json").read_text())
    assert (summary["letters"], summary["letters_grouped"], summary["groups"]) == (3, 2, 1)
    assert summary["individual"] == 1 and summary["method"] == "exact"
    assert summary["bcubed"] == {"n_scored": 2, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    letters_file = tmp_path / summary["letters_file"]
    assert summary["letters_sha256"] == hashlib.sha256(letters_file.read_bytes()).hexdigest()


def test_summary_has_no_score_when_epa_grouped_nothing(tmp_path):
    write_letters(tmp_path, "D-1", {"letter_id": ["a", "b"], "text": [LETTER, LETTER]})
    assert m.build_docket("D-1", tmp_path) is True
    summary = json.loads((tmp_path / "derived" / "campaigns" / "D-1" / "summary.json").read_text())
    assert summary["bcubed"] is None and summary["groups"] == 1


TEMPLATE = " ".join(f"template{i}" for i in range(150))


def test_containment_is_the_default_and_groups_personalized_letters(tmp_path, capsys):
    # Same template, 90 words of each sender's own: exact match would group none of them.
    texts = [TEMPLATE + " " + " ".join(f"s{i}w{j}" for j in range(90)) for i in range(3)]
    write_letters(tmp_path, "D-1", {"letter_id": ["a", "b", "c"], "text": texts})
    assert m.build_docket("D-1", tmp_path) is True
    folder = tmp_path / "derived" / "campaigns" / "D-1"
    written = pd.read_parquet(folder / "assignments.parquet")
    assert written["campaign_id"].tolist() == ["a", "a", "a"]
    assert (written["method"] == "containment").all()
    summary = json.loads((folder / "summary.json").read_text())
    assert summary["method"] == "containment" and summary["threshold"] == 0.5
    assert "3 letters: 3 in 1 containment groups" in capsys.readouterr().out


def test_an_empty_threshold_in_env_means_the_default(tmp_path, monkeypatch):
    write_letters(tmp_path, "D-1", {"letter_id": ["a", "b"], "text": [LETTER, LETTER]})
    monkeypatch.setenv("DOCKET_IDS", "D-1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GROUPING_METHOD", "")
    monkeypatch.setenv("CONTAINMENT_THRESHOLD", "")
    assert m.main() == 0
    summary = json.loads((tmp_path / "derived" / "campaigns" / "D-1" / "summary.json").read_text())
    assert summary["method"] == "containment" and summary["threshold"] == 0.5
