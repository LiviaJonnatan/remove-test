"""Extraction only: preserve case and punctuation for downstream algorithms."""

import html
import re
import shutil
import subprocess
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from pypdf import PdfReader


def clean_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract_body(value: str | None) -> str | None:
    parser = BodyParser()
    parser.feed(html.unescape(value or ""))
    text = clean_text("".join(parser.parts))
    return None if not text or is_attachment_pointer(text) else text


def is_attachment_pointer(text: str) -> bool:
    # Match a whole referral, including submitter/organization descriptions.
    # Additional sentences or clauses with arguments must remain usable body text.
    pointer = re.fullmatch(
        r"(?:please\s+)?(?:see|find|refer to)\s+(?:the\s+)?"
        r"attach(?:ed|ments?)"
        r"(?:\s+(?:(?:my|our|the)\s+)?"
        r"(?:comments?|(?:comment\s+)?letters?|documents?|files?(?:\(s\))?))?"
        r"(?:\s+(?:from|on behalf of|by|for|offering|regarding)\s+[^.!?;]+)?[.!\s]*",
        text,
        re.IGNORECASE,
    )
    return bool(pointer)


def is_submission_header_only(text: str) -> bool:
    """Reject date-only re-submission headers; do not impose a minimum letter length.

    A scan can yield a readable stamp while the actual letter remains an image.
    This detects the observed header case, not every partially extracted scan.
    """
    if not re.search(r"\b(?:originally submitted|re-?submitted)\b", text, re.IGNORECASE):
        return False
    remaining = re.sub(r"\b(?:originally submitted|re-?submitted)\b", "", text, flags=re.IGNORECASE)
    remaining = re.sub(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|"
        r"November|December|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
        "",
        remaining,
        flags=re.IGNORECASE,
    )
    return not re.sub(r"[\d\s:,.\-/]", "", remaining)


def ocr_pdf_page(path: Path, page_number: int) -> str:
    """Render one page locally; OCR images never leave the container or survive the call."""
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ValueError("ocr_tools_unavailable")
    with TemporaryDirectory(prefix="undersigned-ocr-") as directory:
        prefix = Path(directory) / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-r",
                    "300",
                    "-singlefile",
                    "-png",
                    str(path.resolve()),
                    str(prefix),
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError("ocr_render_failed") from error
        try:
            result = subprocess.run(
                ["tesseract", str(prefix.with_suffix(".png")), "stdout", "-l", "eng", "--psm", "3"],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError("ocr_recognition_failed") from error
        return clean_text(result.stdout)


def extract_units(path: Path, file_format: str) -> tuple[list[str], str]:
    """Units are physical PDF pages or DOCX paragraphs, including empty ones.

    Blank units must remain: letter IDs are tied to source positions.
    DOCX table cells are retained for individual comments. Campaign ranges
    use paragraphs only and reject tables pending an explicit reviewed parser.
    """
    if file_format == "pdf":
        units = []
        used_ocr = False
        for number, page in enumerate(PdfReader(path).pages, start=1):
            text = clean_text(page.extract_text() or "")
            unusable = not text or is_attachment_pointer(text) or is_submission_header_only(text)
            # Image presence avoids OCRing true blank pages or text-only covers.
            # Page.images.keys() inspects image IDs without decoding raster bytes.
            if unusable and page.images.keys():
                text = ocr_pdf_page(path, number)
                used_ocr = True
            units.append(text)
        return units, "ocr" if used_ocr else "pdf_text"
    if file_format == "docx":
        document = Document(path)
        units = []
        for block in document.iter_inner_content():
            if hasattr(block, "text"):
                units.append(clean_text(block.text))
            else:
                units.append(
                    clean_text(" ".join(cell.text for row in block.rows for cell in row.cells))
                )
        return units, "docx"
    raise ValueError("unsupported_format")
