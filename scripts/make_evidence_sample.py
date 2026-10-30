"""Build the de-identified evidence sample for data-collector.

  python scripts/make_evidence_sample.py [--docket EPA-HQ-OW-2018-0149] [--id EPA-...-0123]

Picks one detail record submitted by an organization (or the --id given), blanks the
submitter name fields, redacts names from titles, and writes the sample under
docs/evidence/data-collector/. Prints the chosen record's body so you can confirm by eye
that it names no individual before committing. See CONTRIBUTING.md: no personal names in git.
"""

import argparse
import json
import re
import shutil
from pathlib import Path

NAME_FIELDS = ("firstName", "lastName", "submitterRep", "submitterRepAddress", "submitterRepCityState")
TITLE_RE = re.compile(r"(submitted by )(.+?)(?=,|$)", re.IGNORECASE)


def redact_title(title: str | None) -> str | None:
    if not title:
        return title
    # "Comment submitted by Jane Doe, Org Name" -> "Comment submitted by [redacted], Org Name"
    return TITLE_RE.sub(r"\1[redacted]", title, count=1)


def scrub_detail(detail: dict) -> dict:
    a = detail["data"]["attributes"]
    for f in NAME_FIELDS:
        if f in a:
            a[f] = None
    a["title"] = redact_title(a.get("title"))
    return detail


def scrub_index_line(row: dict) -> dict:
    row = dict(row)
    row["title"] = redact_title(row.get("title"))
    return row


def pick_org_record(details_dir: Path) -> Path:
    for f in sorted(details_dir.glob("*.json")):
        a = json.loads(f.read_text())["data"]["attributes"]
        if (a.get("organization") or "").strip() and not (a.get("firstName") or a.get("lastName")):
            return f
    raise SystemExit("no organization-submitted record found; pass --id")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2018-0149")
    ap.add_argument("--id", help="use this record instead of auto-picking")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="docs/evidence/data-collector")
    a = ap.parse_args()

    raw = Path(a.data_dir) / "raw" / a.docket
    out = Path(a.out)
    sample = out / "sample"
    sample.mkdir(parents=True, exist_ok=True)

    detail_file = raw / "details" / f"{a.id}.json" if a.id else pick_org_record(raw / "details")
    detail = scrub_detail(json.loads(detail_file.read_text()))
    (sample / detail_file.name).write_text(json.dumps(detail, indent=2))

    with open(raw / "comments_index.jsonl") as f:
        head = [scrub_index_line(json.loads(line)) for line, _ in zip(f, range(5))]
    (sample / "comments_index.head.jsonl").write_text("".join(json.dumps(r) + "\n" for r in head))

    for name in ("details_index.jsonl", "attachments_manifest.jsonl"):
        src = raw / name
        if src.exists():
            with open(src) as f:
                lines = [line for line, _ in zip(f, range(5))]
            (sample / name.replace(".jsonl", ".head.jsonl")).write_text("".join(lines))

    if (raw / "manifest.json").exists():
        shutil.copy(raw / "manifest.json", out / "collector-manifest.json")

    body = detail["data"]["attributes"].get("comment") or "(no body; attachment only)"
    print(f"chose {detail_file.name}")
    print(f"organization: {detail['data']['attributes'].get('organization')}")
    print(f"title:        {detail['data']['attributes'].get('title')}")
    print("body (check for names before committing):")
    print("  " + body[:600].replace("\n", "\n  "))
    print(f"\nwrote {out}/")


if __name__ == "__main__":
    main()