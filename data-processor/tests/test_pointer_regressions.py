import pytest

from conftest import DOCKET, put_attachment, put_record
from extract import extract_body, is_submission_header_only
from main import run


@pytest.mark.parametrize(
    "pointer",
    [
        "Find attached comments from Example Submitter offering a recommendation "
        "for a major revision of the proposed rule.",
        "See attached file(s)",
        "Please see attached comment letter on behalf of the Example Water Association (EWA), "
        "Example State Council (ESC), and Example Wildlife Association (EWA).",
    ],
)
def test_reported_pointer_shapes_use_attachment(raw, tmp_path, pointer):
    assert extract_body(pointer) is None
    record = put_record(raw, body=pointer)
    put_attachment(raw, record, texts=["We oppose weakening water protection standards."])
    out = tmp_path / "out"
    report = run(raw, out, DOCKET, lambda text: len(text.split()))
    import pyarrow.parquet as pq

    rows = pq.read_table(out / "letters.parquet").to_pylist()
    assert report["records_failed"] == 0
    assert rows[0]["text_source"] == "docx"
    assert rows[0]["text"] == "We oppose weakening water protection standards."


@pytest.mark.parametrize(
    "argument",
    [
        "See attached file(s). I oppose the rule because it harms waterways.",
        "See attached letter; I oppose weakening standards.",
        "Our waterways supply drinking water. Please see attached comments.",
        "See attached letter and I oppose weakening standards.",
        "Please see attached comment letter on behalf of EWA. We support the proposal.",
    ],
)
def test_inline_arguments_are_preserved(argument):
    assert extract_body(argument) == argument


def test_readable_stamp_on_scan_is_not_a_letter(raw, tmp_path):
    record = put_record(raw, body="See attached file(s)")
    put_attachment(
        raw, record, fmt="pdf", texts=["Originally submitted: Re-submitted February 14, 2019"]
    )
    report = run(raw, tmp_path / "out", DOCKET, len)
    assert report["letters"] == 0
    assert report["records_failed"] == 1
    assert report["events"][0]["reason"] == ("attachment_has_only_pointer_or_submission_header")


def test_header_with_actual_argument_is_not_rejected():
    assert not is_submission_header_only(
        "Originally submitted: February 14, 2019. Protect our waterways."
    )
    assert not is_submission_header_only("I oppose this rule.")


def test_unusable_docx_falls_back_to_substantive_pdf(raw, tmp_path):
    record = put_record(raw, body="See attached file(s)")
    put_attachment(raw, record, texts=["See attached file(s)"])
    put_attachment(raw, record, fmt="pdf", texts=["We support water protection standards."])
    report = run(raw, tmp_path / "out", DOCKET, len)
    import pyarrow.parquet as pq

    rows = pq.read_table(tmp_path / "out" / "letters.parquet").to_pylist()
    assert report["records_failed"] == 0
    assert rows[0]["text_source"] == "pdf_text"
