import json
import shutil
import subprocess

import pyarrow.parquet as pq
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from conftest import DOCKET, put_attachment, put_record
from extract import extract_units, ocr_pdf_page
from main import run


def scanned_attachment(raw, *, header=False, mixed=False):
    record = put_record(raw, body="See attached file(s)")
    path = put_attachment(raw, record, fmt="pdf")
    image = Image.new("RGB", (1400, 500), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 38)
    except OSError:
        font = ImageFont.load_default(size=38)
    draw.text((60, 60), "Dear agency reviewer,", fill="black", font=font)
    draw.text((60, 140), "Protect clean water for all communities.", fill="black", font=font)
    draw.text(
        (60, 220), "Please retain strong water protection standards.", fill="black", font=font
    )
    canvas = Canvas(str(path))
    if mixed:
        canvas.drawString(40, 750, "Text-based first page with a substantive argument.")
        canvas.showPage()
    if header:
        canvas.drawString(40, 780, "Originally submitted: Re-submitted February 14, 2019")
    canvas.drawImage(ImageReader(image), 20, 480, width=570, height=204)
    canvas.showPage()
    canvas.save()
    return path


def test_scanned_page_requests_ocr_with_source_position(raw, monkeypatch):
    path = scanned_attachment(raw, header=True, mixed=True)
    calls = []

    def fake_ocr(path, number):
        calls.append(number)
        return "Protect clean water."

    monkeypatch.setattr("extract.ocr_pdf_page", fake_ocr)
    units, source = extract_units(path, "pdf")
    assert calls == [2]
    assert len(units) == 2 and units[1] == "Protect clean water."
    assert source == "ocr"
    assert units[0] == "Text-based first page with a substantive argument."


def test_missing_native_tools_reported(raw, tmp_path, monkeypatch):
    scanned_attachment(raw)
    monkeypatch.setattr("extract.shutil.which", lambda name: None)
    report = run(raw, tmp_path / "out", DOCKET, len)
    assert report["letters"] == 0 and report["records_failed"] == 1
    assert report["events"][0]["reason"] == "ocr_tools_unavailable"


def test_ocr_subprocess_failure_has_safe_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("extract.shutil.which", lambda name: f"/usr/bin/{name}")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "pdftoppm", stderr="PRIVATE CONTENT")

    monkeypatch.setattr("extract.subprocess.run", fail)
    with pytest.raises(ValueError, match="ocr_render_failed"):
        ocr_pdf_page(tmp_path / "scan.pdf", 1)


@pytest.mark.skipif(
    not shutil.which("tesseract") or not shutil.which("pdftoppm"),
    reason="optional native OCR integration needs container tools",
)
@pytest.mark.parametrize("header", [False, True])
def test_actual_scan_becomes_letter_with_ocr_provenance(raw, tmp_path, header):
    scanned_attachment(raw, header=header)
    report = run(raw, tmp_path / "out", DOCKET, lambda text: len(text.split()))
    assert report["records_failed"] == 0
    rows = pq.read_table(tmp_path / "out" / "letters.parquet").to_pylist()
    assert len(rows) == 1
    assert "protect clean water" in rows[0]["text"].lower()
    assert rows[0]["text_source"] == "ocr"
    assert rows[0]["attachment_id"] == "attachment-A"
    assert rows[0]["epa_campaign_id"] is None
    assert "PRIVATE CONTENT" not in json.dumps(report)
