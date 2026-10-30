"""OCR one page of a scanned PDF and print the text plus a rough quality proxy.

  python scripts/ocr_sample.py data/raw/<docket>/attachments/<id>/attachment_1.pdf [--page 1] [--dpi 300]

Writes <pdf stem>.p<page>.png (the rendered page, so we can compare by eye) and
<pdf stem>.p<page>.ocr.txt next to the PDF, and prints:
  - word count, and the share of words that are plain dictionary words (a proxy; real
    quality is judged by reading a paragraph against the image and counting errors)
  - the first 40 lines of text

Needs: brew install tesseract poppler   (or apt install tesseract-ocr poppler-utils)
       pip install pdf2image pytesseract
"""

import argparse
import re
from pathlib import Path

try:
    import pytesseract
    from pdf2image import convert_from_path
except ImportError:  # pragma: no cover
    raise SystemExit("pip install pdf2image pytesseract; and install tesseract + poppler") from None

# Small built-in word list: enough to estimate whether OCR output is mostly real words.
COMMON = set(
    [
        "the",
        "of",
        "and",
        "to",
        "in",
        "a",
        "is",
        "that",
        "for",
        "on",
        "with",
        "as",
        "by",
        "this",
        "be",
        "are",
        "from",
        "at",
        "or",
        "an",
        "it",
        "which",
        "we",
        "not",
        "have",
        "has",
        "water",
        "waters",
        "rule",
        "proposed",
        "definition",
        "clean",
        "act",
        "epa",
        "states",
        "united",
        "navigable",
        "wetlands",
        "streams",
        "protection",
        "agency",
        "comment",
        "comments",
        "support",
        "oppose",
        "urge",
        "please",
        "dear",
        "sincerely",
        "regards",
        "thank",
        "you",
        "federal",
        "state",
        "public",
        "health",
        "environment",
        "rivers",
        "lakes",
        "drinking",
        "pollution",
        "regulation",
        "administrator",
        "docket",
        "revised",
        "jurisdiction",
        "tributaries",
        "ephemeral",
        "intermittent",
        "adjacent",
        "ditches",
        "ground",
        "i",
        "my",
        "our",
        "your",
        "their",
        "his",
        "her",
        "they",
        "them",
        "these",
        "those",
        "will",
        "would",
        "should",
        "could",
        "must",
        "can",
        "may",
        "also",
        "more",
        "most",
        "all",
        "any",
        "some",
        "each",
        "other",
        "than",
        "about",
        "into",
        "over",
        "under",
        "through",
        "between",
        "name",
        "city",
        "zip",
        "address",
        "signed",
        "petition",
        "undersigned",
    ]
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--lang", default="eng")
    a = ap.parse_args()

    pdf = Path(a.pdf)
    images = convert_from_path(str(pdf), dpi=a.dpi, first_page=a.page, last_page=a.page)
    img = images[0]
    png = pdf.with_suffix(f".p{a.page}.png")
    img.save(png)

    text = pytesseract.image_to_string(img, lang=a.lang)
    txt = pdf.with_suffix(f".p{a.page}.ocr.txt")
    txt.write_text(text)

    words = re.findall(r"[A-Za-z']+", text)
    lower = [w.lower() for w in words]
    common = sum(1 for w in lower if w in COMMON)
    alpha_ratio = sum(len(w) for w in words) / max(1, len(re.sub(r"\s", "", text)))

    print(f"file:            {pdf}")
    print(f"page:            {a.page} of {len(convert_from_path(str(pdf), dpi=20))}")
    print(f"words:           {len(words)}")
    print(f"common-word share: {common / max(1, len(words)):.0%}  (typical clean English text: 40-60%)")
    print(f"letters share:   {alpha_ratio:.0%} of non-space characters (low means symbol noise)")
    print(f"image:           {png}")
    print(f"text:            {txt}")
    print("-" * 60)
    print("\n".join(text.splitlines()[:40]))


if __name__ == "__main__":
    main()