"""data-processor: Build one canonical record per letter; PDF text, OCR fallback, signer hashing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv

from extract import (
    clean_text,
    extract_body,
    extract_units,
    is_attachment_pointer,
    is_submission_header_only,
)
from records import (
    LETTER_SCHEMA,
    RECORD_SCHEMA,
    SIGNER_SCHEMA,
    make_letter,
    signer_hash,
    sponsor_from_title,
    utc_date,
)
from tokenization import load_token_counter


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("attachment_path_outside_raw")
    return path


def attachment_documents(record, manifest):
    """Deduplicate formats by attachment ID, order documents by API docOrder."""
    documents = {}
    for item in record.get("included", []):
        if item.get("type") == "attachments":
            attrs = item.get("attributes", {})
            documents[item["id"]] = {
                "id": item["id"],
                "order": int(attrs.get("docOrder") or 0),
                "title": attrs.get("title") or "",
                "files": [],
            }
    for entry in manifest:
        aid = entry["attachment_id"]
        if aid not in documents:
            documents[aid] = {"id": aid, "order": 0, "title": "", "files": []}
        documents[aid]["files"].append(entry)
    # Relationships still reveal missing downloads when included is absent.
    refs = record.get("data", {}).get("relationships", {}).get("attachments", {}).get("data", [])
    for ref in refs:
        aid = ref["id"]
        documents.setdefault(aid, {"id": aid, "order": 0, "title": "", "files": []})
    return sorted(documents.values(), key=lambda d: (d["order"], d["id"]))


def read_attachment(document, raw, events, record_id, required_format=None):
    priority = {"docx": 0, "pdf": 1}
    seen = set()
    entries = sorted(
        document["files"], key=lambda f: (priority.get(f["format"].lower(), 99), f["path"])
    )
    for entry in entries:
        fmt = entry["format"].lower()
        if required_format and fmt != required_format:
            continue
        if entry["path"] in seen:
            continue
        seen.add(entry["path"])
        try:
            path = safe_path(raw, entry["path"])
            units, source = extract_units(path, fmt)
            if not any(units):
                raise ValueError("no_extractable_text")
            text = clean_text(" ".join(units))
            if is_attachment_pointer(text) or is_submission_header_only(text):
                raise ValueError("attachment_has_only_pointer_or_submission_header")
            return units, source, entry["path"]
        except Exception as error:
            # Never write exception messages: PDF/JSON errors can contain raw text.
            events.append(
                {
                    "record_id": record_id,
                    "attachment_id": document["id"],
                    "path": entry["path"],
                    "status": "format_failed",
                    "error_type": type(error).__name__,
                    "reason": str(error)
                    if type(error) is ValueError
                    and str(error)
                    in {
                        "no_extractable_text",
                        "unsupported_format",
                        "attachment_path_outside_raw",
                        "attachment_has_only_pointer_or_submission_header",
                        "ocr_tools_unavailable",
                        "ocr_render_failed",
                        "ocr_recognition_failed",
                    }
                    else None,
                }
            )
    raise ValueError("no_usable_attachment_format")


def process_record(record, files, raw, docket, count_tokens, key, plan, events):
    data = record["data"]
    rid, attrs = data["id"], data["attributes"]
    if attrs.get("docketId") != docket:
        raise ValueError("wrong_docket")
    if attrs.get("withdrawn") or attrs.get("restrictReason"):
        raise ValueError("withdrawn_or_restricted")
    copies = int(attrs.get("duplicateComments") or 1)
    title = attrs.get("title") or ""
    campaign = copies > 1 or "mass comment campaign" in title.casefold()
    documents = attachment_documents(record, files)
    config = plan.get(rid, {})
    if campaign and not config:
        raise ValueError("campaign_requires_reviewed_plan")
    kind = config.get("attachment_kind") if campaign else None
    if campaign and kind not in {"every_letter", "sample_letter", "signer_list"}:
        raise ValueError("invalid_attachment_kind")

    letter_rows = []
    signer_rows = []
    if campaign and kind == "every_letter":
        # One reviewed full-letter attachment per record for U-04. Multiple
        # formats of it are fine; ranges must match the reviewed physical format.
        aid = config["attachment_id"]
        document = next(d for d in documents if d["id"] == aid)
        fmt = config["format"]
        if fmt not in {"pdf", "docx"}:
            raise ValueError("invalid_campaign_format")
        units, source, path = read_attachment(document, raw, events, rid, fmt)
        if fmt == "docx":
            from docx import Document

            if Document(safe_path(raw, path)).tables:
                raise ValueError("campaign_docx_tables_need_reviewed_parser")
        ranges = config.get("letters", [])
        if not ranges:
            raise ValueError("campaign_has_no_reviewed_boundaries")
        previous_end = 0
        for span in ranges:
            start, end = span["start"], span["end"]
            if (
                type(start) is not int
                or type(end) is not int
                or not (previous_end < start <= end <= len(units))
            ):
                raise ValueError("invalid_or_overlapping_letter_range")
            previous_end = end
            text = clean_text(" ".join(units[start - 1 : end]))
            if not text:
                raise ValueError("empty_campaign_letter")
            if (
                span.get("text_sha1")
                and span["text_sha1"] != hashlib.sha1(text.encode()).hexdigest()
            ):
                raise ValueError("reviewed_text_hash_mismatch")
            row = make_letter(
                rid, docket, attrs, text, source, aid, count_tokens, key, "campaign_letter", start
            )
            letter_rows.append(row)
            events.append(
                {
                    "record_id": rid,
                    "letter_id": row["letter_id"],
                    "attachment_id": aid,
                    "path": path,
                    "start": start,
                    "end": end,
                    "unit": "page" if fmt == "pdf" else "paragraph",
                    "text_sha1": row["text_sha1"],
                    "status": "extracted",
                }
            )
    else:
        body = extract_body(attrs.get("comment"))
        aid = config.get("attachment_id")
        source, path = "body", None
        if aid or not body:
            candidates = (
                [d for d in documents if d["id"] == aid]
                if aid
                else [
                    d
                    for d in documents
                    if not any(
                        marker in d["title"].casefold()
                        for marker in ("cover", "signer", "signature", "petition list")
                    )
                ]
            )
            if not aid and len(candidates) > 1:
                primary = [d for d in candidates if d["title"].strip().casefold() == "comment"]
                if len(primary) == 1:
                    for other in candidates:
                        if other["id"] != primary[0]["id"]:
                            events.append(
                                {
                                    "record_id": rid,
                                    "attachment_id": other["id"],
                                    "status": "supporting_attachment_not_selected",
                                    "reason": "unique_primary_comment_title",
                                }
                            )
                    candidates = primary
            if len(candidates) != 1:
                raise ValueError("attachment_selection_requires_review")
            document = candidates[0]
            units, source, path = read_attachment(document, raw, events, rid)
            body, aid = clean_text(" ".join(units)), document["id"]
        row_kind = "campaign_sample" if campaign else "individual"
        row = make_letter(rid, docket, attrs, body, source, aid, count_tokens, key, row_kind)
        letter_rows.append(row)
        events.append(
            {
                "record_id": rid,
                "letter_id": row["letter_id"],
                "status": "extracted",
                "path": path,
                "attachment_id": aid,
                "text_sha1": row["text_sha1"],
            }
        )

    if campaign and kind == "signer_list":
        # Reviewed structured signer fields, never names copied into output. Parsing
        # arbitrary petition layouts is deferred; raw plans must stay private.
        if not config.get("signers"):
            raise ValueError("signer_list_requires_reviewed_signers")
        for signer in config["signers"]:
            hashed = signer_hash(signer, key)
            if not hashed:
                raise ValueError("signer_without_name")
            import re

            zipcode = re.fullmatch(r"(\d{5})(?:-\d{4})?", str(signer.get("zip") or ""))
            signer_rows.append(
                {
                    "record_id": rid,
                    "signer_hash": hashed,
                    "city": signer.get("city"),
                    "state": signer.get("stateProvinceRegion"),
                    "zip": zipcode[1] if zipcode else None,
                }
            )
    campaign_row = None
    if campaign:
        campaign_row = {
            "record_id": rid,
            "title": title,
            "copies_claimed": copies,
            "sponsor_epa": sponsor_from_title(title),
            "sponsor_attachment": None,
            "attachment_kind": kind,
            "n_letters": len(letter_rows),
            "n_signers": len(signer_rows),
            "receive_date": utc_date(attrs.get("receiveDate")),
        }
    return letter_rows, campaign_row, signer_rows


def write_table(path, rows, schema):
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), temporary)
    temporary.replace(path)


def read_record_ids(path):
    """Comment ids from RECORD_IDS_FILE: one per line, blank lines and # comments ignored.

    The same format the collector reads, so both stages work from one list.
    """
    ids = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and line not in ids:
            ids.append(line)
    return ids


def run(raw, out, docket, count_tokens, key=None, plan=None, max_records=None, record_ids=None):
    if not (raw / "details").is_dir():
        raise ValueError("missing_raw_details_directory")
    if max_records is not None and max_records < 1:
        raise ValueError("max_records_must_be_positive")
    indexed = defaultdict(list)
    for entry in read_jsonl(raw / "attachments_manifest.jsonl"):
        indexed[entry["comment_id"]].append(entry)
    paths = sorted((raw / "details").glob("*.json"))
    if record_ids is not None:
        # A fixed list (the MS2 sample) decides which records are read. data/raw can hold more of
        # the docket than the collector just fetched, for example the whole docket after
        # `dvc pull`, and those other records must not leak into the run. As in the collector,
        # max_records does not apply while a list is set.
        listed = sorted(rid for rid in record_ids if rid.startswith(f"{docket}-"))
        paths = [raw / "details" / f"{rid}.json" for rid in listed]
    elif max_records is not None:
        paths = paths[:max_records]
    if not paths:
        raise ValueError("no_detail_records")
    letters, campaigns, signers, events = [], [], [], []
    seen = set()
    for path in paths:
        rid = path.stem
        record_events = []
        try:
            if not path.exists():
                raise ValueError("listed_record_not_on_disk")
            record = json.loads(path.read_text(encoding="utf-8"))
            rid = record["data"]["id"]
            if rid != path.stem or rid in seen:
                raise ValueError("duplicate_or_mismatched_record_id")
            seen.add(rid)
            rows, campaign, signer_rows = process_record(
                record, indexed[rid], raw, docket, count_tokens, key, plan or {}, record_events
            )
            # Transaction per record: no partial rows survive a later range failure.
            letters.extend(rows)
            if campaign:
                campaigns.append(campaign)
            signers.extend(signer_rows)
            events.extend(record_events)
        except Exception as error:
            # Only our known validation messages are safe to include.
            code = str(error) if type(error) is ValueError else type(error).__name__
            allowed = {
                "wrong_docket",
                "withdrawn_or_restricted",
                "missing_signer_hash_key",
                "campaign_requires_reviewed_plan",
                "invalid_attachment_kind",
                "invalid_campaign_format",
                "campaign_has_no_reviewed_boundaries",
                "invalid_or_overlapping_letter_range",
                "empty_campaign_letter",
                "reviewed_text_hash_mismatch",
                "attachment_selection_requires_review",
                "no_usable_attachment_format",
                "campaign_docx_tables_need_reviewed_parser",
                "signer_list_requires_reviewed_signers",
                "signer_without_name",
                "duplicate_or_mismatched_record_id",
                "listed_record_not_on_disk",
            }
            events.extend(e for e in record_events if e["status"] == "format_failed")
            events.append(
                {
                    "record_id": rid,
                    "status": "record_failed",
                    "reason": code if code in allowed else type(error).__name__,
                }
            )
    ids = [row["letter_id"] for row in letters]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_letter_id")
    out.mkdir(parents=True, exist_ok=True)
    write_table(out / "letters.parquet", letters, LETTER_SCHEMA)
    write_table(out / "records.parquet", campaigns, RECORD_SCHEMA)
    write_table(out / "signers.parquet", signers, SIGNER_SCHEMA)
    report = {
        "docket_id": docket,
        "records_attempted": len(paths),
        "records_failed": sum(e["status"] == "record_failed" for e in events),
        "letters": len(letters),
        "campaign_records": len(campaigns),
        "signers": len(signers),
        "events": events,
    }
    (out / "processing_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docket", default=os.getenv("DOCKET_IDS", "EPA-HQ-OW-2018-0149"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--tokenizer",
        type=Path,
        default=os.getenv("BGE_TOKENIZER_PATH", "/app/models/bge/tokenizer.json"),
    )
    parser.add_argument("--plan", type=Path, help="private reviewed campaign extraction JSON")
    parser.add_argument(
        "--max-records",
        type=int,
        default=int(os.environ["MAX_RECORDS"]) if os.getenv("MAX_RECORDS") else None,
    )
    parser.add_argument(
        "--record-ids-file",
        default=os.getenv("RECORD_IDS_FILE"),
        help="read only the comment ids listed here (the collector's list); overrides "
        "--max-records. Pass an empty string to turn off a list set in .env",
    )
    parser.add_argument("--strict", action="store_true", help="nonzero exit on skipped records")
    args = parser.parse_args(argv)
    try:
        count = load_token_counter(args.tokenizer)
        plan = json.loads(args.plan.read_text()) if args.plan else {}
        record_ids = read_record_ids(Path(args.record_ids_file)) if args.record_ids_file else None
        failed = False
        for docket in args.docket.split(","):
            docket = docket.strip()
            if not docket or Path(docket).name != docket or docket in {".", ".."}:
                raise ValueError("invalid_docket")
            out = args.data_root / "derived" / "letters" / docket
            report = run(
                args.data_root / "raw" / docket,
                out,
                docket,
                count,
                os.getenv("SIGNER_HASH_KEY"),
                plan,
                args.max_records,
                record_ids,
            )
            report["tokenizer_sha256"] = hashlib.sha256(args.tokenizer.read_bytes()).hexdigest()
            report["tokenizer_model"] = "BAAI/bge-small-en-v1.5 (checksum verified)"
            report["token_count_includes_special_tokens"] = True
            report["plan_sha256"] = (
                hashlib.sha256(args.plan.read_bytes()).hexdigest() if args.plan else None
            )
            dvc = args.data_root / "raw" / f"{docket}.dvc"
            report["raw_dvc_pointer_sha256"] = (
                hashlib.sha256(dvc.read_bytes()).hexdigest() if dvc.exists() else None
            )
            (out / "processing_report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({k: v for k, v in report.items() if k != "events"}))
            failed |= bool(report["records_failed"])
        return 2 if failed and args.strict else 0
    except Exception as error:
        print(
            f"Processor setup failed ({type(error).__name__}); check input/configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
