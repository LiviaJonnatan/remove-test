import json

import pytest
from docx import Document
from reportlab.pdfgen.canvas import Canvas

DOCKET = "EPA-HQ-OW-2018-0149"


@pytest.fixture
def raw(tmp_path):
    path = tmp_path / "raw" / DOCKET
    (path / "details").mkdir(parents=True)
    return path


def put_record(raw, suffix="0001", body="Protect clean water.", copies=1, **attrs):
    rid = f"{DOCKET}-{suffix}"
    record = {
        "data": {
            "id": rid,
            "attributes": {
                "docketId": DOCKET,
                "comment": body,
                "duplicateComments": copies,
                "receiveDate": "2018-05-01T00:00:00-04:00",
                **attrs,
            },
        },
        "included": [],
    }
    save_record(raw, record)
    return record


def save_record(raw, record):
    (raw / "details" / f"{record['data']['id']}.json").write_text(json.dumps(record))


def put_attachment(
    raw, record, aid="attachment-A", fmt="docx", texts=None, title="Comment", order=1
):
    texts = texts if texts is not None else ["Protect clean water."]
    rid = record["data"]["id"]
    relative = f"attachments/{rid}/attachment_{order}.{fmt}"
    path = raw / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "docx":
        document = Document()
        for text in texts:
            document.add_paragraph(text)
        document.save(path)
    elif fmt == "pdf":
        canvas = Canvas(str(path))
        for text in texts:
            if text:
                canvas.drawString(40, 750, text)
            canvas.showPage()
        canvas.save()
    else:
        path.write_text("unsupported fixture")
    if not any(d["id"] == aid for d in record["included"]):
        record["included"].append(
            {
                "id": aid,
                "type": "attachments",
                "attributes": {
                    "title": title,
                    "docOrder": order,
                },
            }
        )
    save_record(raw, record)
    with (raw / "attachments_manifest.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "comment_id": rid,
                    "attachment_id": aid,
                    "format": fmt,
                    "path": relative,
                    "file": path.name,
                }
            )
            + "\n"
        )
    return path
