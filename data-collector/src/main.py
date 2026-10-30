"""data-collector: pull comments and attachments for one or more Regulations.gov dockets.

Three resumable stages per docket, all writing under DATA_DIR/raw/<docket>/:

  1. index      list every comment on the docket           -> comments_index.jsonl
  2. details    one detail call per comment (full text,
                receiveDate, attachment metadata)           -> details/<id>.json
                                                            + details_index.jsonl
  3. attachments download each attachment file              -> attachments/<id>/<file>

Every stage skips work that is already on disk, so the container can be stopped
and restarted at any point. Keys rotate round-robin; a key that gets a 429 is
rested for an hour.

Environment:
  API_DATA_GOV_KEYS   comma-separated api.data.gov keys (API_DATA_GOV_KEY also accepted)
  DOCKET_IDS          comma-separated, default EPA-HQ-OW-2018-0149
  DATA_DIR            default /app/data
  MAX_RECORDS         stop after this many comments per docket (smoke tests), default unlimited
  SKIP_ATTACHMENTS    set to 1 to skip stage 3
  RECORD_IDS_FILE     a list of comment ids, one per line (# starts a comment). When set, the
                      index stage is skipped and exactly those records are fetched for the
                      dockets in DOCKET_IDS. MAX_RECORDS is ignored. Every id must belong to a
                      docket in DOCKET_IDS and every docket needs at least one id, or the
                      collector exits 1 before any API call. Used for the fixed demo sample in
                      samples/ms2_ids.txt.
  SHARD               "k/n": this container handles every n-th comment starting at k (1-based),
                      e.g. SHARD=2/5. Lets five containers with five keys pull one docket
                      in parallel. Stage 1 (the index) always runs in full; stages 2 and 3
                      are sharded. Default 1/1. Also accepted as --shard k/n on the command line.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

API = "https://api.regulations.gov/v4"
PAGE_SIZE = 250
MAX_PAGES = 20  # the API caps any single query at 20 pages x 250 = 5,000 records
KEY_REST_SECONDS = 3600

log = logging.getLogger("data-collector")


# --------------------------------------------------------------------------- keys

RATE_MARGIN = 5  # switch keys when a key has fewer than this many calls left in its hour


@dataclass
class KeyPool:
    keys: list[str]
    rested_until: dict[str, float] = field(default_factory=dict)
    remaining: dict[str, int] = field(default_factory=dict)
    _i: int = 0

    def next(self) -> str:
        """Return the next usable key, sleeping if every key is resting."""
        for _ in range(len(self.keys)):
            key = self.keys[self._i % len(self.keys)]
            self._i += 1
            if self.rested_until.get(key, 0) <= time.time():
                return key
        wake = min(self.rested_until.values()) - time.time()
        log.warning(
            "all %d key(s) at their hourly limit; sleeping %.0fs, resuming at %s. "
            "This is a pause, not a hang. Another job on the same key will cause this too.",
            len(self.keys),
            wake,
            time.strftime("%H:%M:%S", time.localtime(time.time() + wake)),
        )
        time.sleep(max(wake, 1))
        return self.next()

    def rest(self, key: str, seconds: float = KEY_REST_SECONDS) -> None:
        self.rested_until[key] = time.time() + seconds
        log.warning("key ...%s rate-limited, resting %.0fs", key[-4:], seconds)

    def observe(self, key: str, remaining: int | None) -> None:
        """Record X-RateLimit-Remaining; rest the key early rather than wait for a 429."""
        if remaining is None:
            return
        self.remaining[key] = remaining
        if remaining < RATE_MARGIN:
            self.rest(key)


class Client:
    def __init__(self, pool: KeyPool):
        self.pool = pool
        self.session = requests.Session()
        # downloads.regulations.gov rejects the default python-requests User-Agent with a 403.
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36 Undersigned-AC215/0.1"
        )
        self.calls = 0
        self.failed_downloads: list[dict] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        for attempt in range(8):
            key = self.pool.next()
            try:
                r = self.session.get(
                    f"{API}{path}", params=params, headers={"X-Api-Key": key}, timeout=60
                )
            except requests.RequestException as e:
                log.warning("network error %s, retry %d", e, attempt)
                time.sleep(2**attempt)
                continue
            self.calls += 1
            rem = r.headers.get("X-RateLimit-Remaining")
            self.pool.observe(key, int(rem) if rem and rem.isdigit() else None)
            if r.status_code == 429:
                retry = r.headers.get("Retry-After")
                self.pool.rest(key, float(retry) if retry else KEY_REST_SECONDS)
                continue
            if r.status_code >= 500:
                log.warning("server %d on %s, retry %d", r.status_code, path, attempt)
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"gave up on {path}")

    def download(self, url: str, dest: Path) -> bool:
        """Fetch one attachment. Returns False (and records it) if the file can't be fetched."""
        # Attachment files are served from downloads.regulations.gov; no key needed.
        for attempt in range(5):
            try:
                with self.session.get(url, stream=True, timeout=120) as r:
                    if r.status_code in (403, 404):
                        log.warning("attachment %s returned %d, skipping", url, r.status_code)
                        self.failed_downloads.append({"url": url, "status": r.status_code})
                        return False
                    r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                    tmp.rename(dest)
                return True
            except requests.RequestException as e:
                log.warning("download error %s, retry %d", e, attempt)
                time.sleep(2**attempt)
        log.error("gave up downloading %s", url)
        self.failed_downloads.append({"url": url, "status": "error"})
        return False


# --------------------------------------------------------------------------- helpers

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

def append_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

def parse_shard(text: str | None) -> tuple[int, int]:
    """'k/n' -> (k, n), 1 <= k <= n. Missing or empty means (1, 1)."""
    if not text:
        return 1, 1
    k, n = (int(x) for x in text.split("/"))
    if not 1 <= k <= n:
        raise ValueError(f"bad SHARD {text!r}: need 1 <= k <= n")
    return k, n

def in_shard(i: int, shard: tuple[int, int]) -> bool:
    k, n = shard
    return i % n == (k - 1)

def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150] or "file"


# --------------------------------------------------------------------------- stage 1

def build_index(client: Client, docket: str, out: Path, max_records: int | None) -> int:
    """List every comment on the docket, walking lastModifiedDate windows past the 5,000 cap.

    Procedure from the API docs: sort by lastModifiedDate,documentId; after 20 pages,
    restart with filter[lastModifiedDate][ge] = last seen date. Records sharing that
    exact timestamp reappear and are deduplicated by id.
    """
    index_path = out / "comments_index.jsonl"
    ckpt_path = out / "index_checkpoint.json"
    seen = {row["id"] for row in read_jsonl(index_path)}
    ckpt = json.loads(ckpt_path.read_text()) if ckpt_path.exists() else {}
    if ckpt.get("complete") and _checkpoint_satisfies(ckpt, len(seen), max_records):
        log.info("[%s] index complete, %d comments", docket, len(seen))
        return len(seen)
    if ckpt.get("complete"):
        log.info(
            "[%s] index was capped at %d by an earlier MAX_RECORDS run; rebuilding it in full",
            docket,
            len(seen),
        )
        ckpt = {}

    window_start = ckpt.get("window_start")
    total = ckpt.get("total_reported")
    while True:
        params = {
            "filter[docketId]": docket,
            "sort": "lastModifiedDate,documentId",
            "page[size]": PAGE_SIZE,
        }
        if window_start:
            params["filter[lastModifiedDate][ge]"] = window_start
        last_date = None
        for page in range(1, MAX_PAGES + 1):
            params["page[number]"] = page
            data = client.get("/comments", params)
            if not window_start:
                # totalElements of the unfiltered query is the docket's true count; later
                # windows are filtered and report fewer.
                total = data.get("meta", {}).get("totalElements")
            rows = []
            for item in data.get("data", []):
                a = item["attributes"]
                last_date = a["lastModifiedDate"]
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                rows.append(
                    {
                        "id": item["id"],
                        "object_id": a.get("objectId"),
                        "title": a.get("title"),
                        "posted_date": a.get("postedDate"),
                        "last_modified": a["lastModifiedDate"],
                        "document_type": a.get("documentType"),
                        "agency_id": a.get("agencyId"),
                    }
                )
            append_jsonl(index_path, rows)
            log.info(
                "[%s] index page %d: +%d (%d so far of ~%s)",
                docket,
                page,
                len(rows),
                len(seen),
                total,
            )
            if max_records and len(seen) >= max_records:
                n = _trim_index(index_path, max_records)
                ckpt_path.write_text(json.dumps({"complete": True, "truncated": True}))
                log.info("[%s] index capped at MAX_RECORDS=%d (%d kept)", docket, max_records, n)
                return n
            if not data.get("meta", {}).get("hasNextPage"):
                return _finish_index(docket, ckpt_path, len(seen), total)
        # Hit the 20-page cap; open a new window at the last date seen.
        # Format the API accepts for this filter is "YYYY-MM-DD HH:MM:SS" in ET.
        window_start = _to_filter_date(last_date)
        ckpt_path.write_text(json.dumps({"window_start": window_start, "total_reported": total}))

def _checkpoint_satisfies(ckpt: dict, n_indexed: int, max_records: int | None) -> bool:
    """A complete checkpoint stands unless it was truncated by a cap the current run doesn't have.

    A smoke test writes {"complete": true, "truncated": true}; a later full run must not
    take that as the whole docket (review comment on #29).
    """
    if not ckpt.get("truncated"):
        return True
    return bool(max_records) and n_indexed >= max_records

def _finish_index(docket: str, ckpt_path: Path, n_indexed: int, total: int | None) -> int:
    """Mark the index complete only if it holds every comment the API reported (#27)."""
    if total is not None and n_indexed != total:
        ckpt_path.write_text(
            json.dumps({"complete": False, "indexed": n_indexed, "total_reported": total})
        )
        raise RuntimeError(
            f"[{docket}] index has {n_indexed} comments but the API reports {total}; "
            "not marking complete. Delete index_checkpoint.json and re-run to retry."
        )
    ckpt_path.write_text(json.dumps({"complete": True, "total_reported": total}))
    log.info("[%s] index complete, %d comments (API reports %s)", docket, n_indexed, total)
    return n_indexed

def _trim_index(index_path: Path, max_records: int) -> int:
    """Keep the first max_records index lines, so a smoke test fetches that many details."""
    rows = read_jsonl(index_path)[:max_records]
    index_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


def _to_filter_date(iso: str, back_off_seconds: int = 60) -> str:
    """UTC ISO timestamp from the API -> the Eastern-time string its date filter expects.

    The API returns lastModifiedDate in UTC ("2019-04-15T19:03:11Z") but the
    filter[lastModifiedDate][ge] parameter is interpreted in Eastern time, so passing
    the UTC string restarts the window four or five hours late and skips records
    (#27). We also back off by a minute, since duplicates are dropped by id anyway.
    """
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    t = t.astimezone(ZoneInfo("America/New_York")) - timedelta(seconds=back_off_seconds)
    return t.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- stage 2

def read_record_ids(path: Path) -> list[str]:
    """Comment ids from a list file: one per line, blank lines and # comments ignored."""
    ids: list[str] = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and line not in ids:
            ids.append(line)
    return ids


def belongs_to(record_id: str, docket: str) -> bool:
    """A comment id is its docket id plus a number: EPA-HQ-OW-2022-0801-1264."""
    return record_id.startswith(f"{docket}-")


def check_record_ids(record_ids: list[str], dockets: list[str]) -> list[str]:
    """What is wrong with a fixed list for these dockets. An empty list means nothing.

    Without this, a list for one docket with DOCKET_IDS set to another fetches nothing and exits
    0, and the processor then reads whatever an earlier run left in data/raw.
    """
    problems: list[str] = []
    for docket in dockets:
        if not any(belongs_to(cid, docket) for cid in record_ids):
            problems.append(f"no id in the list belongs to {docket}")

    unmatched = []
    for cid in record_ids:
        if not any(belongs_to(cid, docket) for docket in dockets):
            unmatched.append(cid)
    if unmatched:
        problems.append(f"ids for no docket in DOCKET_IDS: {len(unmatched)}, first {unmatched[0]}")
    return problems


def shard_ids(out: Path, shard: tuple[int, int], record_ids: list[str] | None = None) -> list[str]:
    """The comments this container owns: from the fixed list if given, otherwise from the index."""
    source = (
        record_ids
        if record_ids is not None
        else [row["id"] for row in read_jsonl(out / "comments_index.jsonl")]
    )
    return [cid for i, cid in enumerate(source) if in_shard(i, shard)]


def fetch_details(
    client: Client,
    docket: str,
    out: Path,
    shard: tuple[int, int] = (1, 1),
    record_ids: list[str] | None = None,
) -> int:
    details_dir = out / "details"
    details_dir.mkdir(exist_ok=True)
    ids = shard_ids(out, shard, record_ids)
    todo = [i for i in ids if not (details_dir / f"{i}.json").exists()]
    log.info(
        "[%s] details: %d of %d already on disk, %d to fetch",
        docket,
        len(ids) - len(todo),
        len(ids),
        len(todo),
    )
    details_index = out / "details_index.jsonl"
    for n, cid in enumerate(todo, 1):
        data = client.get(f"/comments/{cid}", {"include": "attachments"})
        (details_dir / f"{cid}.json").write_text(json.dumps(data))
        a = data["data"]["attributes"]
        append_jsonl(
            details_index,
            [
                {
                    "id": cid,
                    "receive_date": a.get("receiveDate"),
                    "posted_date": a.get("postedDate"),
                    "has_body": bool((a.get("comment") or "").strip()),
                    "n_attachments": sum(
                        1 for i in data.get("included", []) if i.get("type") == "attachments"
                    ),
                }
            ],
        )
        if n % 100 == 0:
            log.info(
                "[%s] details %d/%d (%d API calls this run)", docket, n, len(todo), client.calls
            )
    return len(ids)


# --------------------------------------------------------------------------- stage 3

def fetch_attachments(
    client: Client,
    docket: str,
    out: Path,
    shard: tuple[int, int] = (1, 1),
    record_ids: list[str] | None = None,
) -> tuple[int, int]:
    details_dir = out / "details"
    att_root = out / "attachments"
    att_root.mkdir(exist_ok=True)
    manifest_path = out / "attachments_manifest.jsonl"
    have = {(r["comment_id"], r["file"]) for r in read_jsonl(manifest_path)}
    n_files = n_new = 0
    # Shard on the same index order as stage 2, so each container owns the same comments throughout.
    index_ids = shard_ids(out, shard, record_ids)
    for cid_from_index in index_ids:
        detail_file = details_dir / f"{cid_from_index}.json"
        if not detail_file.exists():
            continue
        detail = json.loads(detail_file.read_text())
        cid = detail["data"]["id"]
        for inc in detail.get("included", []):
            if inc.get("type") != "attachments":
                continue
            for fmt in inc["attributes"].get("fileFormats") or []:
                url = fmt.get("fileUrl")
                if not url:
                    continue
                fname = safe_name(url.rsplit("/", 1)[-1])
                dest = att_root / cid / fname
                n_files += 1
                if (cid, fname) in have and dest.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not client.download(url, dest):
                    continue
                append_jsonl(
                    manifest_path,
                    [
                        {
                            "comment_id": cid,
                            "attachment_id": inc["id"],
                            "file": fname,
                            "format": fmt.get("format"),
                            "size": fmt.get("size"),
                            "url": url,
                            "path": str(dest.relative_to(out)),
                        }
                    ],
                )
                have.add((cid, fname))
                n_new += 1
                if n_new % 50 == 0:
                    log.info("[%s] attachments: %d downloaded this run", docket, n_new)
    return n_files, n_new


# --------------------------------------------------------------------------- main

def collect_docket(
    client: Client,
    docket: str,
    data_dir: Path,
    max_records: int | None,
    skip_att: bool,
    shard: tuple[int, int],
    record_ids: list[str] | None = None,
) -> dict:
    out = data_dir / "raw" / docket
    out.mkdir(parents=True, exist_ok=True)
    if record_ids is not None:
        # A fixed list: no index pass, and an index already on disk is left alone.
        record_ids = [cid for cid in record_ids if belongs_to(cid, docket)]
        log.info("[%s] fixed list of %d records, index stage skipped", docket, len(record_ids))
        n_index = len(record_ids)
    else:
        n_index = build_index(client, docket, out, max_records)
    n_details = fetch_details(client, docket, out, shard, record_ids)
    n_att, n_att_new = (
        (0, 0) if skip_att else fetch_attachments(client, docket, out, shard, record_ids)
    )
    summary = {
        "docket": docket,
        "shard": f"{shard[0]}/{shard[1]}",
        "comments_indexed": n_index,
        "details_on_disk": n_details,
        "attachment_files": n_att,
        "attachments_downloaded_this_run": n_att_new,
        "attachments_failed": client.failed_downloads,
        "api_calls_this_run": client.calls,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_name = (
        "manifest.json" if shard == (1, 1) else f"manifest_shard_{shard[0]}_of_{shard[1]}.json"
    )
    (out / manifest_name).write_text(json.dumps(summary, indent=2))
    log.info("[%s] done: %s", docket, summary)
    return summary


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )

    raw_keys = os.getenv("API_DATA_GOV_KEYS") or os.getenv("API_DATA_GOV_KEY") or ""
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        log.error("no API keys: set API_DATA_GOV_KEYS in .env (https://api.data.gov/signup/)")
        return 1

    dockets = [
        d.strip() for d in os.getenv("DOCKET_IDS", "EPA-HQ-OW-2018-0149").split(",") if d.strip()
    ]
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    max_records = int(os.getenv("MAX_RECORDS") or 0) or None
    skip_att = os.getenv("SKIP_ATTACHMENTS", "0") == "1"
    shard_text = os.getenv("SHARD")
    if len(sys.argv) >= 3 and sys.argv[1] == "--shard":
        shard_text = sys.argv[2]
    shard = parse_shard(shard_text)
    ids_file = os.getenv("RECORD_IDS_FILE")
    record_ids = read_record_ids(Path(ids_file)) if ids_file else None
    if record_ids is not None:
        problems = check_record_ids(record_ids, dockets)
        for problem in problems:
            log.error("RECORD_IDS_FILE %s: %s", ids_file, problem)
        if problems:
            log.error(
                "set DOCKET_IDS to the docket the list is for, or empty RECORD_IDS_FILE "
                "(see samples/README.md)"
            )
            return 1

    log.info(
        "keys=%d dockets=%s max_records=%s skip_attachments=%s shard=%d/%d",
        len(keys),
        dockets,
        max_records,
        skip_att,
        shard[0],
        shard[1],
    )
    client = Client(KeyPool(keys))
    for docket in dockets:
        collect_docket(client, docket, data_dir, max_records, skip_att, shard, record_ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())