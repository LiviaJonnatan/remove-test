"""The stage end to end: a response document and letters in, codes, entries and a summary out."""

import json

import pandas as pd

import main as m
from test_parse import DOC

DOCKET = "EPA-HQ-OW-2022-0801"


def test_run_writes_entries_with_spans(tmp_path, monkeypatch):
    (tmp_path / "raw" / DOCKET / "rtc").mkdir(parents=True)
    (tmp_path / "raw" / DOCKET / "rtc" / "rtc.pdf").write_bytes(b"%PDF stand-in")
    letters_dir = tmp_path / "derived" / "letters" / DOCKET
    letters_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "letter_id": [f"{DOCKET}-0800", f"{DOCKET}-1378#1"],
            "record_id": [f"{DOCKET}-0800", f"{DOCKET}-1378"],
            "text": [
                "Dear EPA. We support the proposed rule but ask for more time. Thanks.",
                "Something unrelated to the excerpt.",
            ],
        }
    ).to_parquet(letters_dir / "letters.parquet", index=False)
    monkeypatch.setattr(m, "pdf_text", lambda pdf: DOC)

    summary = m.run(DOCKET, tmp_path)

    out = tmp_path / "derived" / "responses" / DOCKET
    entries = pd.read_parquet(out / "entries.parquet")
    codes = pd.read_parquet(out / "codes.parquet")
    assert list(codes["code"]) == ["1.1", "5.9.2"]
    assert len(entries) == 3
    first = entries.iloc[0]
    letter = "Dear EPA. We support the proposed rule but ask for more time. Thanks."
    assert first["letter_id"] == f"{DOCKET}-0800"
    assert letter[int(first["span_start"]) : int(first["span_end"])] == (
        "We support the proposed rule but ask for more time"
    )
    assert list(first["response_refs"]) == ["1.1"]
    assert entries.iloc[1]["span_start"] is None or pd.isna(entries.iloc[1]["span_start"])
    assert not entries.iloc[2]["has_letter"]
    assert summary["entries_located"] == 1 and summary["entries_with_letter"] == 2
    assert json.loads((out / "summary.json").read_text())["codes"] == 2


def test_docket_without_document_is_skipped(tmp_path):
    assert m.run(DOCKET, tmp_path) is None
