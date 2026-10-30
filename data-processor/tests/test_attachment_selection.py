import pyarrow.parquet as pq
import pytest

from conftest import DOCKET, put_attachment, put_record
from main import run


@pytest.mark.parametrize(
    "support_title",
    [
        "Attachment - letter dated 12/21/18 from Clean Water Action et al. "
        "to Michael McDavit et al.",
        "Attachment: Letter dated December 21, 2018 from Clean Water Action et al. "
        "to Michael McDavit et al.",
    ],
)
def test_primary_comment_selected_over_supporting_letter(raw, tmp_path, support_title):
    record = put_record(raw, body="See attached")
    put_attachment(
        raw,
        record,
        aid="primary",
        title="Comment",
        texts=["Our primary argument concerns the proposed water rule."],
    )
    put_attachment(
        raw,
        record,
        aid="supporting",
        title=support_title,
        order=2,
        texts=["Supporting correspondence from a different submission."],
    )
    report = run(raw, tmp_path / "out", DOCKET, len)
    rows = pq.read_table(tmp_path / "out" / "letters.parquet").to_pylist()
    assert report["records_failed"] == 0
    assert len(rows) == 1 and rows[0]["attachment_id"] == "primary"
    assert rows[0]["text"] == "Our primary argument concerns the proposed water rule."
    assert any(
        e["status"] == "supporting_attachment_not_selected" and e["attachment_id"] == "supporting"
        for e in report["events"]
    )


def test_primary_title_not_document_order_selects_comment(raw, tmp_path):
    record = put_record(raw, body="See attached")
    put_attachment(
        raw,
        record,
        aid="support",
        title="Attachment: supporting letter",
        texts=["Supplemental material"],
        order=1,
    )
    put_attachment(
        raw, record, aid="primary", title=" COMMENT ", texts=["Primary comment"], order=2
    )
    report = run(raw, tmp_path / "out", DOCKET, len)
    rows = pq.read_table(tmp_path / "out" / "letters.parquet").to_pylist()
    assert report["records_failed"] == 0
    assert rows[0]["attachment_id"] == "primary"


def test_unreadable_primary_does_not_silently_use_supporting_letter(raw, tmp_path):
    record = put_record(raw, body="See attached")
    path = put_attachment(raw, record, aid="primary", title="Comment")
    path.write_bytes(b"corrupt")
    put_attachment(
        raw,
        record,
        aid="support",
        title="Attachment: supporting letter",
        texts=["Other correspondence"],
        order=2,
    )
    report = run(raw, tmp_path / "out", DOCKET, len)
    assert report["letters"] == 0 and report["records_failed"] == 1
