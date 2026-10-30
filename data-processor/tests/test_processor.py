import hashlib
import json

import pyarrow.parquet as pq
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordPiece
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing

from conftest import DOCKET, put_attachment, put_record
from extract import extract_body
from main import load_token_counter, main, read_record_ids, run, safe_path
from records import LETTER_SCHEMA, make_letter, signer_hash, utc_date


def process(raw, tmp_path, **kwargs):
    out = tmp_path / "out"
    report = run(raw, out, DOCKET, lambda text: len(text.split()), **kwargs)
    return report, pq.read_table(out / "letters.parquet").to_pylist()


@pytest.mark.parametrize(
    "body", [None, "", "See attached", "Please see attachment.", "Find attached comments"]
)
def test_attachment_pointer_is_not_letter(body):
    assert extract_body(body) is None


def test_preserve_arguments_and_remove_html():
    assert extract_body("<p>Protect &amp; preserve water.</p><script>bad</script>") == (
        "Protect & preserve water."
    )
    assert extract_body("See attached. I oppose this rule.") == (
        "See attached. I oppose this rule."
    )


def test_inline_schema_privacy_timezone_and_determinism(raw, tmp_path):
    put_record(
        raw,
        firstName="Example",
        lastName="Person",
        zip="01234-5678",
        email="private@example.invalid",
        address1="DO NOT COPY",
    )
    report, rows = process(raw, tmp_path, key="test-secret")
    assert report["records_failed"] == 0
    row = rows[0]
    assert row["letter_id"] == f"{DOCKET}-0001"
    assert row["epa_campaign_id"] is None
    assert row["attachment_id"] is None
    assert row["zip"] == "01234"
    assert row["receive_date"].hour == 4
    assert row["text_sha1"] == hashlib.sha1(row["text"].encode()).hexdigest()
    assert len(row["signer_hash"]) == 64
    assert "email" not in row and "firstName" not in row
    assert pq.read_schema(tmp_path / "out" / "letters.parquet") == LETTER_SCHEMA
    _, rerun = process(raw, tmp_path, key="test-secret")
    assert rows == rerun
    assert "Example" not in (tmp_path / "out" / "processing_report.json").read_text()


def test_docx_preferred_and_duplicate_manifest_does_not_duplicate_letter(raw, tmp_path):
    record = put_record(raw, body="See attached")
    put_attachment(raw, record, fmt="pdf", texts=["PDF duplicate"])
    put_attachment(raw, record, fmt="docx", texts=["Preferred DOCX"])
    report, rows = process(raw, tmp_path)
    assert report["letters"] == 1
    assert rows[0]["text"] == "Preferred DOCX"
    assert rows[0]["text_source"] == "docx"


def test_broken_docx_falls_back_to_pdf(raw, tmp_path):
    record = put_record(raw, body="See attached")
    path = put_attachment(raw, record, fmt="docx")
    path.write_bytes(b"broken")
    put_attachment(raw, record, fmt="pdf", texts=["Usable PDF"])
    report, rows = process(raw, tmp_path)
    assert rows[0]["text_source"] == "pdf_text"
    assert any(e["status"] == "format_failed" for e in report["events"])


def test_cover_is_not_substantive_attachment(raw, tmp_path):
    record = put_record(raw, body="See attached")
    put_attachment(raw, record, aid="cover", title="Cover page", texts=["Fax cover"])
    put_attachment(raw, record, aid="comment", order=2, texts=["Actual argument"])
    _, rows = process(raw, tmp_path)
    assert rows[0]["attachment_id"] == "comment"


def test_multiple_substantive_attachments_need_selection(raw, tmp_path):
    record = put_record(raw, body=None)
    put_attachment(raw, record, aid="first")
    put_attachment(raw, record, aid="second", order=2)
    report, rows = process(raw, tmp_path)
    assert not rows and report["records_failed"] == 1
    plan = {record["data"]["id"]: {"attachment_id": "second"}}
    _, rows = process(raw, tmp_path, plan=plan)
    assert rows[0]["attachment_id"] == "second"


def campaign_fixture(raw):
    record = put_record(
        raw,
        body="See attached",
        copies=100,
        title="Mass Comment Campaign sponsored by Test Coalition",
        firstName="Coordinator",
        lastName="Not a signer",
    )
    put_attachment(
        raw,
        record,
        fmt="pdf",
        texts=["Cover", "Protect water.", "Continuation.", "", "Protect water."],
    )
    rid = record["data"]["id"]
    plan = {
        rid: {
            "attachment_kind": "every_letter",
            "attachment_id": "attachment-A",
            "format": "pdf",
            "letters": [{"start": 2, "end": 3}, {"start": 5, "end": 5}],
        }
    }
    return rid, plan


def test_reviewed_campaign_ranges_not_page_equals_letter(raw, tmp_path):
    rid, plan = campaign_fixture(raw)
    report, rows = process(raw, tmp_path, plan=plan)
    assert report["records_failed"] == 0
    assert [r["letter_id"] for r in rows] == [f"{rid}#2", f"{rid}#5"]
    assert rows[0]["text"] == "Protect water. Continuation."
    assert all(r["epa_campaign_id"] == rid for r in rows)
    assert all(r["signer_hash"] is None for r in rows)
    campaign = pq.read_table(tmp_path / "out" / "records.parquet").to_pylist()[0]
    assert campaign["copies_claimed"] == 100 and campaign["n_letters"] == 2
    assert campaign["sponsor_epa"] == "Test Coalition"
    # Changing an earlier boundary must not renumber the later letter.
    plan[rid]["letters"][0]["end"] = 2
    _, revised = process(raw, tmp_path, plan=plan)
    assert revised[1]["letter_id"] == rows[1]["letter_id"]
    assert revised[0]["text_sha1"] != rows[0]["text_sha1"]


def test_campaign_not_inferred_from_copy_count(raw, tmp_path):
    campaign_fixture(raw)
    report, rows = process(raw, tmp_path)
    assert not rows
    assert report["events"][-1]["reason"] == "campaign_requires_reviewed_plan"


@pytest.mark.parametrize("fault", ["overlap", "beyond_end", "hash"])
def test_bad_campaign_plan_rolls_back_whole_record(raw, tmp_path, fault):
    rid, plan = campaign_fixture(raw)
    second = plan[rid]["letters"][1]
    if fault == "overlap":
        second["start"] = 3
    elif fault == "beyond_end":
        second["end"] = 100
    else:
        second["text_sha1"] = "wrong"
    report, rows = process(raw, tmp_path, plan=plan)
    assert not rows and report["records_failed"] == 1
    assert not any(e["status"] == "extracted" for e in report["events"])


def test_campaign_sample_has_no_gold_label(raw, tmp_path):
    record = put_record(raw, copies=500)
    rid = record["data"]["id"]
    _, rows = process(raw, tmp_path, plan={rid: {"attachment_kind": "sample_letter"}})
    assert rows[0]["kind"] == "campaign_sample"
    assert rows[0]["epa_campaign_id"] is None


def test_signer_list_hashes_reviewed_names(raw, tmp_path):
    record = put_record(raw, copies=500)
    rid = record["data"]["id"]
    plan = {
        rid: {
            "attachment_kind": "signer_list",
            "signers": [{"firstName": "Synthetic", "lastName": "Signer", "zip": "01234-9999"}],
        }
    }
    report, rows = process(raw, tmp_path, key="secret", plan=plan)
    assert report["signers"] == 1 and rows[0]["epa_campaign_id"] is None
    signer = pq.read_table(tmp_path / "out" / "signers.parquet").to_pylist()[0]
    assert len(signer["signer_hash"]) == 64 and signer["zip"] == "01234"
    assert "firstName" not in signer


def test_missing_key_is_reported_without_leaking_name(raw, tmp_path):
    put_record(raw, firstName="PRIVATE-NAME")
    report, rows = process(raw, tmp_path)
    assert not rows and report["records_failed"] == 1
    assert "PRIVATE-NAME" not in json.dumps(report)
    assert report["events"][-1]["reason"] == "missing_signer_hash_key"


def test_missing_attachment_and_scanned_pdf_do_not_create_empty_letters(raw, tmp_path):
    record = put_record(raw, body="See attached")
    put_attachment(raw, record, fmt="pdf", texts=[""])
    report, rows = process(raw, tmp_path)
    assert not rows and report["records_failed"] == 1
    (raw / "attachments_manifest.jsonl").unlink()
    report, rows = process(raw, tmp_path)
    assert not rows and report["records_failed"] == 1


def test_bad_json_does_not_prevent_other_records(raw, tmp_path):
    put_record(raw)
    (raw / "details" / "broken.json").write_text("not json")
    report, rows = process(raw, tmp_path)
    assert len(rows) == 1 and report["records_failed"] == 1


def test_max_records_and_invalid_limit(raw, tmp_path):
    put_record(raw, suffix="0002")
    put_record(raw, suffix="0001")
    _, rows = process(raw, tmp_path, max_records=1)
    assert rows[0]["record_id"].endswith("0001")
    with pytest.raises(ValueError):
        process(raw, tmp_path, max_records=0)


def test_record_ids_choose_records_and_override_max_records(raw, tmp_path):
    for suffix in ("0001", "0002", "0003"):
        put_record(raw, suffix=suffix)
    # 0002 is on disk but not listed; the last id belongs to another docket.
    listed = [f"{DOCKET}-0003", f"{DOCKET}-0001", "EPA-HQ-OW-2022-0801-0775"]
    report, rows = process(raw, tmp_path, max_records=1, record_ids=listed)
    assert [row["record_id"] for row in rows] == [f"{DOCKET}-0001", f"{DOCKET}-0003"]
    assert report["records_attempted"] == 2


def test_listed_record_missing_from_disk_is_reported(raw, tmp_path):
    put_record(raw, suffix="0001")
    report, rows = process(raw, tmp_path, record_ids=[f"{DOCKET}-0001", f"{DOCKET}-0009"])
    assert len(rows) == 1 and report["records_failed"] == 1
    assert report["events"][-1] == {
        "record_id": f"{DOCKET}-0009",
        "status": "record_failed",
        "reason": "listed_record_not_on_disk",
    }


def test_read_record_ids(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("# sample\nA-1\n\nA-2  # org letter\nA-1\n")
    assert read_record_ids(path) == ["A-1", "A-2"]


def test_restricted_record_is_skipped(raw, tmp_path):
    put_record(raw, withdrawn=True)
    report, rows = process(raw, tmp_path)
    assert not rows and report["records_failed"] == 1


def test_path_traversal_rejected(raw):
    with pytest.raises(ValueError):
        safe_path(raw, "../../outside.pdf")


def test_signer_hash_normalization_and_secret():
    attrs = {"firstName": " EXAMPLE ", "lastName": "Person"}
    assert signer_hash(attrs, "secret") == signer_hash(
        {"firstName": "example", "lastName": "person"}, "secret"
    )
    assert signer_hash(attrs, "secret") != signer_hash(attrs, "other")
    with pytest.raises(ValueError):
        signer_hash(attrs, " ")


def test_date_naive_is_eastern_and_aware_is_preserved():
    assert utc_date("2018-05-01T00:00:00").hour == 4
    assert utc_date("2018-12-01T00:00:00").hour == 5
    assert utc_date("2018-05-01T05:00:00Z").hour == 5


def test_campaign_position_required():
    with pytest.raises(ValueError):
        make_letter("r", DOCKET, {}, "text", "pdf_text", "a", len, kind="campaign_letter")


def tiny_tokenizer(path):
    # Synthetic WordPiece fixture tests counting mechanics, not the bge vocabulary.
    tokenizer = Tokenizer(
        WordPiece({"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "water": 3}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.post_processor = TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    tokenizer.enable_truncation(4)
    tokenizer.enable_padding(length=10)
    tokenizer.save(str(path))


def test_token_count_untruncated_with_special_tokens(tmp_path):
    path = tmp_path / "tokenizer.json"
    tiny_tokenizer(path)
    assert load_token_counter(path, verify_model=False)(" ".join(["water"] * 600)) == 602


def test_cli_strict_writes_report_and_returns_failure(raw, tmp_path, monkeypatch):
    put_record(raw, body="See attached")
    tokenizer = tmp_path / "tokenizer.json"
    tiny_tokenizer(tokenizer)
    monkeypatch.setattr(
        "main.load_token_counter", lambda _: load_token_counter(tokenizer, verify_model=False)
    )
    monkeypatch.delenv("MAX_RECORDS", raising=False)
    # Set, not deleted: main() loads the repo's .env, which would otherwise fill in the demo list.
    monkeypatch.setenv("RECORD_IDS_FILE", "")
    assert (
        main(
            [
                "--docket",
                DOCKET,
                "--data-root",
                str(tmp_path),
                "--tokenizer",
                str(tokenizer),
                "--strict",
            ]
        )
        == 2
    )
    assert (tmp_path / "derived" / "letters" / DOCKET / "processing_report.json").exists()


def test_cli_reads_record_ids_file_from_env(raw, tmp_path, monkeypatch):
    put_record(raw, suffix="0001")
    put_record(raw, suffix="0002")
    ids = tmp_path / "ids.txt"
    ids.write_text(f"{DOCKET}-0002\n")
    tokenizer = tmp_path / "tokenizer.json"
    tiny_tokenizer(tokenizer)
    monkeypatch.setattr(
        "main.load_token_counter", lambda _: load_token_counter(tokenizer, verify_model=False)
    )
    monkeypatch.setenv("RECORD_IDS_FILE", str(ids))
    args = ["--docket", DOCKET, "--data-root", str(tmp_path), "--tokenizer", str(tokenizer)]
    assert main(args) == 0
    letters = pq.read_table(tmp_path / "derived" / "letters" / DOCKET / "letters.parquet")
    assert letters.column("record_id").to_pylist() == [f"{DOCKET}-0002"]


def test_docx_campaign_ranges(raw, tmp_path):
    record = put_record(raw, body=None, copies=50)
    put_attachment(raw, record, texts=["Cover", "First letter", "", "Second letter"])
    rid = record["data"]["id"]
    plan = {
        rid: {
            "attachment_kind": "every_letter",
            "attachment_id": "attachment-A",
            "format": "docx",
            "letters": [{"start": 2, "end": 2}, {"start": 4, "end": 4}],
        }
    }
    _, rows = process(raw, tmp_path, plan=plan)
    assert [row["letter_id"] for row in rows] == [f"{rid}#2", f"{rid}#4"]


def test_record_id_filename_must_match(raw, tmp_path):
    record = put_record(raw)
    original_id = record["data"]["id"]
    record["data"]["id"] = "another-id"
    (raw / "details" / f"{original_id}.json").write_text(json.dumps(record))
    report, rows = process(raw, tmp_path)
    assert report["records_failed"] >= 1
    assert not any(r["record_id"].endswith("0001") for r in rows)
