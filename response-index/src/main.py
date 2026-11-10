"""response-index: the agency's response-to-comments document as data.

Reads `data/raw/<docket>/rtc/rtc.pdf` and the processed letters, and writes to
`data/derived/responses/<docket>/`:

- codes.parquet: one row per topic code, with its title, first page and summary response
- entries.parquet: one row per commenter entry: code, organization, record_id, the excerpt, EPA's
  response to it, the codes that response refers to, and where the excerpt sits in our letter
- rule_diff.parquet: every paragraph of the regulatory text, proposed against final, marked
  unchanged, modified, added or removed, with a word diff for modified ones
- summary.json: counts, coverage and the sha256 of the inputs

The span lets every link from a comment to a response be checked against the letter itself, and the
entries are the labels the comment-to-response matcher is scored on.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from locate import locate, normalize
from parse import clean, parse, references
from rule_diff import diff

VERBATIM = 0.5  # share of 8-word chunks found for an excerpt to count as located


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pdf_text(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext (poppler-utils) is required")
    with tempfile.TemporaryDirectory(prefix="undersigned-rtc-") as d:
        out = Path(d) / "rtc.txt"
        subprocess.run(["pdftotext", "-layout", str(pdf), str(out)], check=True)
        return out.read_text(errors="replace")


def build(docket: str, text: str, letters: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    codes, entries = parse(text)
    code_rows = [
        {
            "docket_id": docket,
            "code": c.code,
            "title": c.title,
            "page": c.page,
            "summary_response": clean(c.summary),
        }
        for c in codes
    ]

    by_record: dict[str, list[tuple[str, str, tuple]]] = {}
    for lid, rid, body in zip(
        letters["letter_id"], letters["record_id"], letters["text"], strict=True
    ):
        by_record.setdefault(rid, []).append((lid, body or "", normalize(body or "")))

    rows = []
    for k, e in enumerate(entries):
        rid = f"{docket}-{e.doc_number:04d}"
        excerpt = clean(e.excerpt)
        response = clean(e.response) if e.response is not None else None
        best, best_lid = None, None
        for lid, body, norm in by_record.get(rid, []):
            found = locate(excerpt, body, norm)
            if best is None or found["share"] > best["share"]:
                best, best_lid = found, lid
        located = best is not None and best["share"] >= VERBATIM
        rows.append(
            {
                "entry_id": f"{docket}:rtc:{k:05d}",
                "docket_id": docket,
                "code": e.code,
                "organization": e.organization,
                "doc_number": e.doc_number,
                "record_id": rid,
                "doc_part": e.part,
                "sbc": e.sbc,
                "page": e.page,
                "excerpt": excerpt,
                "response": response,
                "response_refs": references(response),
                "letter_id": best_lid if located else None,
                "has_letter": rid in by_record,
                "verbatim_share": best["share"] if best else None,
                "span_start": best["start"] if located else None,
                "span_end": best["end"] if located else None,
            }
        )
    return pd.DataFrame(code_rows), pd.DataFrame(rows)


def summarize(docket, pdf, letters_path, data_dir, letters, codes, entries) -> dict:
    with_letter = entries[entries["has_letter"]]
    located = entries["span_start"].notna()
    return {
        "docket_id": docket,
        "codes": len(codes),
        "entries": len(entries),
        "entries_with_own_response": int(entries["response"].notna().sum()),
        "entries_referring_to_other_codes": int((entries["response_refs"].str.len() > 0).sum()),
        "records_cited": int(entries["record_id"].nunique()),
        "records_cited_with_letter": int(with_letter["record_id"].nunique()),
        "letters_cited_share": round(
            entries.loc[entries["has_letter"], "record_id"].nunique() / max(1, len(letters)), 4
        ),
        "entries_with_letter": len(with_letter),
        "entries_located": int(located.sum()),
        "entries_located_share_of_with_letter": round(
            int(located.sum()) / max(1, len(with_letter)), 4
        ),
        "verbatim_threshold": VERBATIM,
        "rtc_file": str(pdf.name),
        "rtc_sha256": sha256(pdf),
        "letters_file": str(letters_path.relative_to(data_dir)),
        "letters_sha256": sha256(letters_path),
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def rule_pair(docket: str, data_dir: Path) -> tuple[Path, Path] | None:
    """The final rule and the last proposal before it that printed regulatory text."""
    rule_dir = data_dir / "raw" / "federal_register" / docket
    docs = []
    for meta_path in sorted(rule_dir.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        docs.append((meta["publication_date"], meta["type"], meta_path.with_suffix(".txt")))
    finals = sorted(d for d in docs if d[1] == "Rule")
    if not finals:
        return None
    final = finals[-1]
    proposals = sorted(
        d
        for d in docs
        if d[1] == "Proposed Rule"
        and d[0] < final[0]
        and "PART 14" in d[2].read_text(errors="replace")
    )
    return (proposals[-1][2], final[2]) if proposals else None


def write_rule_diff(docket: str, data_dir: Path, out: Path) -> dict | None:
    pair = rule_pair(docket, data_dir)
    if pair is None:
        return None
    proposed, final = pair
    rows = diff(proposed.read_text(errors="replace"), final.read_text(errors="replace"))
    frame = pd.DataFrame([vars(r) for r in rows])
    frame.insert(0, "docket_id", docket)
    frame.to_parquet(out / "rule_diff.parquet", index=False)
    return {
        "proposed": proposed.stem,
        "final": final.stem,
        "sections": int(frame["section"].nunique()),
        "paragraphs": frame["op"].value_counts().to_dict(),
    }


def run(docket: str, data_dir: Path) -> dict | None:
    pdf = data_dir / "raw" / docket / "rtc" / "rtc.pdf"
    if not pdf.exists():
        print(f"[{docket}] no response-to-comments document at {pdf}, skipping")
        return None
    letters_path = data_dir / "derived" / "letters" / docket / "letters.parquet"
    letters = pd.read_parquet(letters_path, columns=["letter_id", "record_id", "text"])
    codes, entries = build(docket, pdf_text(pdf), letters)
    out = data_dir / "derived" / "responses" / docket
    out.mkdir(parents=True, exist_ok=True)
    codes.to_parquet(out / "codes.parquet", index=False)
    entries.to_parquet(out / "entries.parquet", index=False)
    summary = summarize(docket, pdf, letters_path, data_dir, letters, codes, entries)
    summary["rule_diff"] = write_rule_diff(docket, data_dir, out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[{docket}] {summary['codes']} codes, {summary['entries']} entries on "
        f"{summary['records_cited']} records, {summary['entries_located']} of "
        f"{summary['entries_with_letter']} excerpts located in our letters"
    )
    return summary


def main() -> int:
    dockets = [
        d.strip() for d in os.getenv("DOCKET_IDS", "EPA-HQ-OW-2022-0801").split(",") if d.strip()
    ]
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    for docket in dockets:
        run(docket, data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
