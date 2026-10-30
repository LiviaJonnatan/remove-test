"""Audit a docket's raw pull: completeness, attachment coverage, and likely scanned PDFs (#11).

  python scripts/audit_attachments.py [--docket EPA-HQ-OW-2018-0149] [--out docs/evidence/data-collector/attachments-audit.md]

Reads data/raw/<docket>/ as the collector wrote it and reports:
  - index vs details vs API total
  - attachment documents expected (from details) vs files downloaded (from the manifest)
  - files by format, documents with no file, download failures
  - PDFs with little or no extractable text per page: candidates for OCR
  - the same, restricted to campaign records (duplicateComments > 1), which are the ones that matter

Needs: pypdf
"""

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings are irrelevant here

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    raise SystemExit("pip install pypdf (or: uv add pypdf)") from None

SCAN_CHARS_PER_PAGE = 100  # below this, a PDF page is almost certainly an image


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p) as f:
        return [json.loads(line) for line in f if line.strip()]


def pdf_text_density(path: Path, max_pages: int = 3) -> tuple[int, float]:
    """(pages, mean extractable chars per page over the first max_pages)."""
    try:
        r = PdfReader(str(path))
        n = len(r.pages)
        if n == 0:
            return 0, 0.0
        chars = [len((r.pages[i].extract_text() or "").strip()) for i in range(min(n, max_pages))]
        return n, sum(chars) / len(chars)
    except Exception:  # noqa: BLE001 - corrupt or encrypted file; report it, don't die
        return -1, -1.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2018-0149")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="docs/evidence/data-collector/attachments-audit.md")
    ap.add_argument("--skip-pdf-scan", action="store_true", help="skip the text-density pass")
    a = ap.parse_args()

    raw = Path(a.data_dir) / "raw" / a.docket
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    index = read_jsonl(raw / "comments_index.jsonl")
    details_dir = raw / "details"
    detail_files = sorted(details_dir.glob("*.json"))
    ckpt = json.loads((raw / "index_checkpoint.json").read_text()) if (raw / "index_checkpoint.json").exists() else {}
    manifest = read_jsonl(raw / "attachments_manifest.jsonl")
    run_manifest = json.loads((raw / "manifest.json").read_text()) if (raw / "manifest.json").exists() else {}

    # ---- non-canonical detail files (a mirror pull stores some records twice as "<id>(1).json")
    canonical = re.compile(rf"^{re.escape(a.docket)}-\d+\.json$")
    odd_names = [f for f in detail_files if not canonical.match(f.name)]
    odd_dupes = 0
    for f in odd_names:
        twin = details_dir / (re.sub(r"\(\d+\)(?=\.json$)", "", f.name))
        if twin.exists() and twin.read_bytes() == f.read_bytes():
            odd_dupes += 1
    detail_files = [f for f in detail_files if canonical.match(f.name)]

    # ---- expected attachments, from details
    expected_docs: dict[str, set[str]] = defaultdict(set)  # comment_id -> attachment ids
    copies: dict[str, int] = {}
    listed_files = Counter()  # (comment_id, file name) -> times the API lists it
    for f in detail_files:
        d = json.loads(f.read_text())
        cid = d["data"]["id"]
        copies[cid] = d["data"]["attributes"].get("duplicateComments") or 1
        for inc in d.get("included", []):
            if inc.get("type") == "attachments":
                expected_docs[cid].add(inc["id"])
                for fmt in inc["attributes"].get("fileFormats") or []:
                    if fmt.get("fileUrl"):
                        listed_files[(cid, fmt["fileUrl"].rsplit("/", 1)[-1])] += 1
    n_expected_docs = sum(len(v) for v in expected_docs.values())
    expected_files = len(listed_files)  # unique files
    duplicate_listings = sorted(k for k, v in listed_files.items() if v > 1)

    # ---- downloaded, from the manifest and the disk
    have_docs: dict[str, set[str]] = defaultdict(set)
    formats = Counter()
    missing_on_disk = []
    for row in manifest:
        p = raw / row["path"]
        if p.exists():
            have_docs[row["comment_id"]].add(row["attachment_id"])
            formats[row["format"]] += 1
        else:
            missing_on_disk.append(row["path"])
    docs_without_file = [
        (cid, aid) for cid, aids in expected_docs.items() for aid in aids if aid not in have_docs.get(cid, set())
    ]
    failed = run_manifest.get("attachments_failed", [])

    # ---- scan detection on PDFs
    scans = []
    unreadable = []
    if not a.skip_pdf_scan:
        pdfs = [r for r in manifest if r["format"] == "pdf" and (raw / r["path"]).exists()]
        for i, r in enumerate(pdfs, 1):
            pages, density = pdf_text_density(raw / r["path"])
            if pages < 0:
                unreadable.append(r["path"])
            elif density < SCAN_CHARS_PER_PAGE:
                scans.append(
                    {
                        "comment_id": r["comment_id"],
                        "path": r["path"],
                        "pages": pages,
                        "chars_per_page": round(density),
                        "copies": copies.get(r["comment_id"], 1),
                        "size": r.get("size"),
                    }
                )
            if i % 500 == 0:
                print(f"  scanned {i}/{len(pdfs)} PDFs")
    campaign_scans = sorted([s for s in scans if s["copies"] > 1], key=lambda s: -s["copies"])

    # ---- report
    L = []
    L.append(f"# Attachment audit: {a.docket}\n")
    L.append(
        "Generated by `scripts/audit_attachments.py`. Counts are from `data/raw/<docket>/` as the collector wrote it.\n"
    )
    L.append("## Completeness\n")
    L.append("| check | value |\n| --- | --- |")
    L.append(f"| API `totalElements` | {ckpt.get('total_reported', 'n/a')} |")
    L.append(f"| index rows | {len(index)} |")
    L.append(f"| detail records on disk | {len(detail_files)} |")
    L.append(
        f"| detail files with non-canonical names (e.g. mirror `<id>(1).json`), excluded above | {len(odd_names)} |"
    )
    L.append(f"| of which byte-identical to their canonical twin | {odd_dupes} |")
    L.append(f"| index checkpoint | `{json.dumps(ckpt)}` |")
    L.append(f"| campaign records (duplicateComments > 1) | {sum(1 for c in copies.values() if c > 1)} |")
    L.append(f"| comments represented (sum of duplicateComments) | {sum(copies.values()):,} |\n")
    L.append("## Attachments\n")
    L.append("| check | value |\n| --- | --- |")
    L.append(f"| records with at least one attachment | {len(expected_docs)} |")
    L.append(f"| attachment documents expected (from details) | {n_expected_docs} |")
    L.append(f"| attachment files offered, unique (all formats) | {expected_files} |")
    L.append(f"| API entries listing the same file twice | {len(duplicate_listings)} |")
    L.append(f"| files in manifest and on disk | {sum(formats.values())} |")
    L.append(
        f"| unique files missing from disk | {sum(1 for k in listed_files if not (raw / 'attachments' / k[0] / k[1]).exists())} |"
    )
    L.append(f"| manifest rows whose file is missing on disk | {len(missing_on_disk)} |")
    L.append(f"| documents with no downloaded file | {len(docs_without_file)} |")
    L.append(f"| download failures recorded in manifest.json | {len(failed)} |\n")
    L.append("Files by format: " + ", ".join(f"{k} {v}" for k, v in formats.most_common()) + "\n")
    if duplicate_listings:
        L.append(
            "Duplicate listings (downloaded once each): " + ", ".join(f"{c}/{f}" for c, f in duplicate_listings) + "\n"
        )
    if odd_names:
        L.append("<details><summary>Non-canonical detail file names</summary>\n")
        L += [f"- {f.name}" for f in odd_names[:200]]
        L.append("\n</details>\n")
    if docs_without_file:
        L.append("<details><summary>Documents with no downloaded file</summary>\n")
        L += [f"- {cid} / {aid}" for cid, aid in docs_without_file[:200]]
        if len(docs_without_file) > 200:
            L.append(f"- … and {len(docs_without_file) - 200} more")
        L.append("\n</details>\n")
    if failed:
        L.append("<details><summary>Download failures</summary>\n")
        L += [f"- {f.get('status')}: {f.get('url')}" for f in failed]
        L.append("\n</details>\n")
    if not a.skip_pdf_scan:
        L.append("## Likely scanned PDFs (OCR candidates)\n")
        L.append(
            f"A PDF counts as a scan when its first pages average under {SCAN_CHARS_PER_PAGE} extractable characters per page. "
            f"{len(scans)} of {sum(formats.values()) - len(unreadable)} PDFs qualify; {len(unreadable)} could not be opened.\n"
        )
        L.append(f"**Campaign records that are scans ({len(campaign_scans)})**, the ones that matter for grouping:\n")
        L.append("| comment | copies | pages | chars/page | size | path |\n| --- | --- | --- | --- | --- | --- |")
        L += [
            f"| {s['comment_id']} | {s['copies']:,} | {s['pages']} | {s['chars_per_page']} | {s['size']} | `{s['path']}` |"
            for s in campaign_scans
        ]
        L.append("")
        L.append(f"Individual-comment scans: {len(scans) - len(campaign_scans)} (list in `{out.stem}-scans.jsonl`).\n")
        if unreadable:
            L.append("<details><summary>PDFs that could not be opened</summary>\n")
            L += [f"- {p}" for p in unreadable]
            L.append("\n</details>\n")
        L.append("## OCR quality\n")
        L.append(
            "_To fill in by hand: for each campaign scan above, run `scripts/ocr_sample.py <path>` on one page, "
            "read the output against the page image, and record words per 100 that are wrong and whether the "
            "template text and signer lines are recoverable._\n"
        )

    out.write_text("\n".join(L))
    scans_path = out.with_name(f"{out.stem}-scans.jsonl")  # e.g. attachments-audit-cpp-scans.jsonl
    with open(scans_path, "w") as f:
        for s in scans:
            f.write(json.dumps(s) + "\n")
    print("\n".join(L[:30]))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()