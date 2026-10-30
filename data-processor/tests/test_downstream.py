"""Exercise the real campaign-builder CLI when installed alongside this component."""

import os
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from conftest import DOCKET, put_attachment, put_record
from main import run


def test_aadil_exact_match_and_bcubed_consume_processor_output(raw, tmp_path):
    default = Path(__file__).resolve().parents[2] / "campaign-builder" / "src"
    builder = Path(os.environ.get("CAMPAIGN_BUILDER_SRC", default))
    if not (builder / "exact_match.py").exists():
        pytest.skip("place component in repo or set CAMPAIGN_BUILDER_SRC")
    campaign = put_record(raw, suffix="0001", body="See attached", copies=20)
    # Exact match leaves letters under 20 words ungrouped (#40), so the form letter is longer.
    letter = (
        "Please protect our drinking water. Lead pipes should be replaced within ten years, "
        "and every family in this state deserves to know what is in their tap."
    )
    put_attachment(raw, campaign, fmt="pdf", texts=[letter, letter])
    put_record(raw, suffix="0002", body="A separate argument about implementation costs.")
    rid = campaign["data"]["id"]
    plan = {
        rid: {
            "attachment_kind": "every_letter",
            "attachment_id": "attachment-A",
            "format": "pdf",
            "letters": [{"start": 1, "end": 1}, {"start": 2, "end": 2}],
        }
    }
    output = tmp_path / "letters"
    report = run(raw, output, DOCKET, lambda text: len(text.split()), plan=plan)
    assert report["records_failed"] == 0
    assignments = tmp_path / "assignments.parquet"
    result = subprocess.run(
        [
            sys.executable,
            str(builder / "exact_match.py"),
            "--letters",
            str(output / "letters.parquet"),
            "--out",
            str(assignments),
            "--score",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "3 letters: 2 in 1 exact-match groups, 1 individual" in result.stdout
    assert "B-cubed on 2 labeled letters: precision 1.000  recall 1.000  f1 1.000" in result.stdout
    assert pq.read_table(assignments).to_pylist()[-1]["campaign_id"] is None
