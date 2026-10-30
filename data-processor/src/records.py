"""Typed Parquet contracts matching schema.md, section 2."""

import hashlib
import hmac
import re
import unicodedata

import pandas as pd
import pyarrow as pa

LETTER_SCHEMA = pa.schema(
    [
        ("letter_id", pa.string()),
        ("text_sha1", pa.string()),
        ("record_id", pa.string()),
        ("docket_id", pa.string()),
        ("kind", pa.string()),
        ("text", pa.string()),
        ("text_source", pa.string()),
        ("attachment_id", pa.string()),
        ("n_tokens", pa.int64()),
        ("receive_date", pa.timestamp("us", tz="UTC")),
        ("signer_hash", pa.string()),
        ("city", pa.string()),
        ("state", pa.string()),
        ("zip", pa.string()),
        ("epa_campaign_id", pa.string()),
    ]
)
RECORD_SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("title", pa.string()),
        ("copies_claimed", pa.int64()),
        ("sponsor_epa", pa.string()),
        ("sponsor_attachment", pa.string()),
        ("attachment_kind", pa.string()),
        ("n_letters", pa.int64()),
        ("n_signers", pa.int64()),
        ("receive_date", pa.timestamp("us", tz="UTC")),
    ]
)
SIGNER_SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("signer_hash", pa.string()),
        ("city", pa.string()),
        ("state", pa.string()),
        ("zip", pa.string()),
    ]
)


def utc_date(value):
    if not value:
        return None
    date = pd.Timestamp(value)
    # Already offset-aware API dates must not be localized a second time.
    if date.tzinfo is None:
        date = date.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise")
    return date.tz_convert("UTC").to_pydatetime()


def signer_hash(attrs: dict, key: str | None) -> str | None:
    name = " ".join(str(attrs.get(k) or "") for k in ("firstName", "lastName"))
    name = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    if not name:
        return None
    if not key or not key.strip():
        raise ValueError("missing_signer_hash_key")
    return hmac.new(key.encode(), name.encode(), hashlib.sha256).hexdigest()


def make_letter(
    record_id,
    docket,
    attrs,
    text,
    source,
    attachment_id,
    count_tokens,
    key=None,
    kind="individual",
    position=None,
):
    full = kind == "campaign_letter"
    if full and (not attachment_id or not isinstance(position, int) or position < 1):
        raise ValueError("campaign_letter_requires_source_position")
    zip_match = re.fullmatch(r"(\d{5})(?:-\d{4})?", str(attrs.get("zip") or "").strip())
    # Campaign-level submitter/location is not the individual letter's signer.
    personal = attrs if kind == "individual" else {}
    return {
        "letter_id": f"{record_id}#{position}" if full else record_id,
        "text_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
        "record_id": record_id,
        "docket_id": docket,
        "kind": kind,
        "text": text,
        "text_source": source,
        "attachment_id": attachment_id,
        "n_tokens": count_tokens(text),
        "receive_date": utc_date(attrs.get("receiveDate")),
        "signer_hash": signer_hash(personal, key),
        "city": personal.get("city"),
        "state": personal.get("stateProvinceRegion"),
        "zip": zip_match[1] if zip_match and kind == "individual" else None,
        "epa_campaign_id": record_id if full else None,
    }


def sponsor_from_title(title: str) -> str | None:
    match = re.search(r"Mass Comment Campaign sponsored by\s+(.+)", title, re.IGNORECASE)
    return match[1].strip() if match else None
