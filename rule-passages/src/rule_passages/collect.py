"""Download the Federal Register documents that belong to a docket.

The Federal Register API needs no key. Each document is saved twice under
DATA_DIR/raw/federal_register/<docket>/: the raw text as served, and a small JSON file with the
fields we cite later. Files already on disk are skipped, so a rerun makes no download calls.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

API = "https://www.federalregister.gov/api/v1/documents.json"
META_FIELDS = (
    "document_number",
    "title",
    "type",
    "publication_date",
    "citation",
    "html_url",
    "raw_text_url",
    "docket_ids",
    "action",
    "dates",
    "abstract",
)

log = logging.getLogger("rule-passages")


@dataclass(frozen=True)
class RuleDocument:
    """One Federal Register document as saved on disk."""

    docket_id: str
    document_number: str
    title: str
    doc_type: str
    publication_date: str
    citation: str
    url: str
    raw_text: str


def list_documents(docket_id: str, session: requests.Session) -> list[dict]:
    """All documents the Federal Register files under one docket id, following pagination."""
    params: dict | None = {
        "conditions[docket_id]": docket_id,
        "per_page": 50,
        "order": "oldest",
        "fields[]": list(META_FIELDS),  # the listing omits raw_text_url unless asked for
    }
    url: str | None = API
    found: list[dict] = []
    while url:
        r = session.get(url, params=params, timeout=60)
        r.raise_for_status()
        page = r.json()
        found.extend(page.get("results", []))
        url, params = page.get("next_page_url"), None
    return found


def collect(docket_id: str, rule_dir: Path, session: requests.Session | None = None) -> list[Path]:
    """Save every document of the docket and return the paths of the text files."""
    session = session or requests.Session()
    out = rule_dir / docket_id
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for doc in list_documents(docket_id, session):
        number = doc["document_number"]
        text_path, meta_path = out / f"{number}.txt", out / f"{number}.json"
        if not text_path.exists():
            r = session.get(doc["raw_text_url"], timeout=120)
            r.raise_for_status()
            text_path.write_text(r.text, encoding="utf-8")
            log.info("[%s] downloaded %s (%s)", docket_id, number, doc["title"][:60])
        if not meta_path.exists():
            meta = {k: doc.get(k) for k in META_FIELDS}
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        paths.append(text_path)
    log.info("[%s] %d documents on disk", docket_id, len(paths))
    return paths


def load_documents(docket_id: str, rule_dir: Path) -> list[RuleDocument]:
    """Read back what `collect` saved."""
    docs = []
    for text_path in sorted((rule_dir / docket_id).glob("*.txt")):
        meta = json.loads(text_path.with_suffix(".json").read_text(encoding="utf-8"))
        docs.append(
            RuleDocument(
                docket_id=docket_id,
                document_number=meta["document_number"],
                title=meta["title"],
                doc_type=meta["type"],
                publication_date=meta["publication_date"],
                citation=meta.get("citation") or "",
                url=meta["html_url"],
                raw_text=text_path.read_text(encoding="utf-8"),
            )
        )
    return docs
