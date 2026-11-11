"""Rule watcher: keeps the `rules` table in step with the Federal Register.

Runs on a schedule (Cloud Scheduler -> Cloud Run Job in production; the `watcher` service in
compose.yaml locally). Each run:

1. Marks every rule with a built bundle `ready`, with its ask counts.
2. Asks the Federal Register API (public, no key) for EPA rules and proposed rules under 40 CFR 141,
   groups them by docket, and drops meeting notices, corrections and test-method approvals.
3. Gives every other docket a status:
     final rule out, no bundle                      awaiting_rtc (the response document is needed)
     proposed, comment period still open            open_for_comment
     proposed, comment period closed                proposed
   An awaiting_rtc rule whose response document is on disk is listed as ready to build; with
   --build the pipeline runs for it (parse, extract, match, build), with the per-rule spend caps
   the pipeline already has.

    uv run python src/jobs/watch_rules.py            # one pass
    uv run python src/jobs/watch_rules.py --loop 86400
"""

from __future__ import annotations

import argparse
import os
import datetime as dt
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import db  # noqa: E402
from store import available  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FR = "https://www.federalregister.gov/api/v1/documents.json"
SKIP = re.compile(r"public meeting|virtual engagement|expedited approval|correction|methods request|webinar|"
                  r"advisory council|delay of effective|extension of comment", re.I)  # fmt: skip


def fetch(pages: int = 3) -> list[dict]:
    out = []
    params = [("conditions[agencies][]", "environmental-protection-agency"), ("conditions[cfr][title]", "40"),
              ("conditions[cfr][part]", "141"), ("conditions[type][]", "RULE"), ("conditions[type][]", "PRORULE"),
              ("order", "newest"), ("per_page", "100")] + [
        ("fields[]", f) for f in ("title", "type", "publication_date", "docket_ids", "comments_close_on", "html_url")]  # fmt: skip
    with httpx.Client(timeout=30, headers={"User-Agent": "oversight-rule-watcher"}) as c:
        for page in range(1, pages + 1):
            r = c.get(FR, params=params + [("page", str(page))])
            r.raise_for_status()
            d = r.json()
            out += d.get("results", [])
            if page >= d.get("total_pages", 1):
                break
    return out


def docket_of(doc: dict) -> str | None:
    for d in doc.get("docket_ids") or []:
        m = re.search(r"EPA-(?:HQ-)?OW-\d{4}-\d{4}", d)
        if m:
            return m.group(0).replace("EPA-OW-", "EPA-HQ-OW-")
    return None


def statuses(docs: list[dict], built: dict[str, dict], today: dt.date) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for doc in docs:
        k = docket_of(doc)
        if k and not SKIP.search(doc["title"]):
            by.setdefault(k, []).append(doc)
    rows = []
    for docket, ds in by.items():
        ds.sort(key=lambda d: d["publication_date"])
        finals = [d for d in ds if d["type"] == "Rule"]
        props = [d for d in ds if d["type"] == "Proposed Rule"]
        latest = (finals or props)[-1]
        row = {"docket": docket, "title": latest["title"], "fr_url": latest.get("html_url"), "short": None,
               "proposed_on": props[0]["publication_date"] if props else None,
               "final_on": finals[0]["publication_date"] if finals else None,
               "comments_close": props[-1].get("comments_close_on") if props else None,
               "bundle_version": None, "asks": None, "changed": None}  # fmt: skip
        if docket in built:
            continue  # handled from the bundle
        if finals:
            row["status"] = "awaiting_rtc"
        elif row["comments_close"] and dt.date.fromisoformat(row["comments_close"]) >= today:
            row["status"] = "open_for_comment"
        else:
            row["status"] = "proposed"
        rows.append(row)
    return rows


def ready_rows(built: dict[str, dict]) -> list[dict]:
    rows = []
    for docket, m in built.items():
        g = (config.DATA_ROOT or ROOT / "data/derived") / "outcomes" / docket / "graph.json"
        rows.append({"docket": docket, "short": m.get("short"), "title": m.get("title") or docket, "status": "ready",
                     "proposed_on": None, "final_on": None, "comments_close": None, "fr_url": None,
                     "bundle_version": dt.datetime.fromtimestamp(g.stat().st_mtime).strftime("%Y%m%d%H%M"),
                     "asks": m.get("asks"), "changed": m.get("changed")})  # fmt: skip
    return rows


def once(build: bool = False) -> dict:
    db.migrate()
    run = db.one("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")["id"]
    log = []
    built = available(config.DATA_ROOT)
    prev = {r["docket"]: r["status"] for r in db.rules()}
    for r in ready_rows(built):
        db.upsert_rule(r)
    before = set(prev)
    try:
        docs = fetch()
    except httpx.HTTPError as e:
        log.append(f"Federal Register fetch failed: {e}")
        docs = []
    rows = statuses(docs, built, dt.date.today())
    for r in rows:
        db.upsert_rule(r)
        if r["status"] == "awaiting_rtc" and (ROOT / f"data/raw/{r['docket']}/rtc/rtc.pdf").exists():
            log.append(f"{r['docket']}: response document on disk, ready to build")
            if build:
                log.append(_build(r["docket"]))
    new = [r["docket"] for r in rows if r["docket"] not in before]
    try:
        log.append(notify(prev, rows + ready_rows(built), dt.date.today()))
        log.append(email_digest())
    except Exception as e:  # noqa: BLE001  (the inbox must never stop the watcher)
        log.append(f"notifications failed: {e}")
    log.append(f"{len(docs)} Federal Register documents, {len(rows)} unbuilt dockets, new: {', '.join(new) or 'none'}")
    db.q("UPDATE ingest_runs SET finished_at = now(), seen = %s, new = %s, log = %s WHERE id = %s",
         len(docs), len(new), "\n".join(log), run)  # fmt: skip
    return {"seen": len(docs), "new": new, "log": log}


LABEL = {"open_for_comment": "Open for comment", "proposed": "Comment period closed", "awaiting_rtc": "Final rule published",
         "ready": "Mapped: see what EPA did with every comment", "processing": "Being mapped"}  # fmt: skip


def _push(user_ids, kind: str, title: str, body: str, url: str, key: str) -> int:
    n = 0
    for uid in user_ids:
        n += len(db.q("""INSERT INTO notifications (user_id, kind, title, body, url, dedupe_key) VALUES (%s, %s, %s, %s, %s, %s)
                         ON CONFLICT (user_id, dedupe_key) DO NOTHING RETURNING id""", uid, kind, title, body, url, key))  # fmt: skip
    return n


def notify(prev: dict[str, str], rows: list[dict], today: dt.date) -> str:
    """Write inbox items: a rule opens for comment (everyone), a followed rule changes status or is a
    week from its deadline, and a rule an organization you follow commented on gets mapped."""
    everyone = [u["id"] for u in db.q("SELECT id FROM users")]
    followers = lambda d: [r["user_id"] for r in db.q("SELECT user_id FROM rule_follows WHERE docket = %s", d)]  # noqa: E731
    sent = 0
    for r in rows:
        d, status, title = r["docket"], r["status"], r["title"][:140]
        close = dt.date.fromisoformat(str(r["comments_close"])) if r.get("comments_close") else None
        if status == "open_for_comment" and prev.get(d) != "open_for_comment":
            sent += _push(everyone, "open", f"Open for comment: {title}",
                          f"Comments close {close:%b %-d, %Y}." if close else "", f"/prepare/{d}", f"open:{d}")  # fmt: skip
        if prev.get(d) and prev[d] != status:
            sent += _push(followers(d), "status", f"{LABEL.get(status, status)}: {title}", "", f"/prepare/{d}" if status != "ready"
                          else f"/rule/{r.get('short') or d}", f"status:{d}:{status}")  # fmt: skip
        if status == "open_for_comment" and close and 0 <= (close - today).days <= 7:
            sent += _push(followers(d), "deadline", f"{(close - today).days} days left to comment: {title}", f"Closes {close:%b %-d}.",
                          f"/prepare/{d}", f"deadline7:{d}")  # fmt: skip
    newly_ready = [r for r in rows if r["status"] == "ready" and prev.get(r["docket"]) not in (None, "ready")]
    if newly_ready:  # tell people following an organization that its record on the new rule is in
        import hub
        from store import Store
        hub.setup(lambda dk: Store(dk, data_root=config.DATA_ROOT), None)
        ix = hub.org_index()["orgs"]
        for f in db.q("SELECT user_id, org_key FROM org_follows"):
            o = ix.get(f["org_key"])
            for r in newly_ready:
                rr = o and o["rules"].get(r.get("short") or "")
                if rr:
                    rec = rr["record"]
                    sent += _push([f["user_id"]], "outcome", f"{o['name']} on {r['short']}: {rec['won']} won, {rec['lost']} lost",
                                  "EPA's response to comments is mapped. See each ask and EPA's answer.", f"/org/{o['slug']}",
                                  f"outcome:{f['org_key']}:{r['docket']}")  # fmt: skip
    return f"notifications: {sent} new"


def email_digest() -> str:
    """Email unread, unsent inbox items, if an email provider is configured (RESEND_API_KEY, EMAIL_FROM).
    Without one the inbox in the app is the only channel."""
    key, sender, base = os.environ.get("RESEND_API_KEY"), os.environ.get("EMAIL_FROM"), os.environ.get("PUBLIC_URL", "")
    if not (key and sender):
        return "email: not configured"
    rows = db.q("""SELECT n.id, n.title, n.body, n.url, u.email FROM notifications n JOIN users u ON u.id = n.user_id
                   WHERE n.emailed_at IS NULL AND n.read_at IS NULL AND n.kind <> 'welcome' AND u.email IS NOT NULL
                   ORDER BY u.email, n.created_at""")  # fmt: skip
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["email"], []).append(r)
    sent = 0
    for to, items in by.items():
        html = "".join(f'<p><a href="{base}{i["url"]}"><b>{i["title"]}</b></a><br>{i["body"] or ""}</p>' for i in items)
        r = httpx.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": f"Bearer {key}"},
                       json={"from": sender, "to": [to], "subject": items[0]["title"] if len(items) == 1 else f"{len(items)} updates from Oversight",
                             "html": html + f'<p style="color:#888">From Oversight. <a href="{base}/#yours">Manage what you follow</a>.</p>'})  # fmt: skip
        if r.status_code < 300:
            db.q("UPDATE notifications SET emailed_at = now() WHERE id = ANY(%s)", [i["id"] for i in items])
            sent += 1
    return f"email: {sent} sent"


def _build(docket: str) -> str:
    """Run the pipeline for one rule. Each step caches its model calls and has a spend cap."""
    import subprocess
    steps = [
        ["uv", "run", "--project", "response-index", "python", "response-index/src/main.py"],
        ["uv", "run", "--project", "outcome-graph", "python", "outcome-graph/src/extract.py", "--docket", docket, "--budget", "25"],
        ["uv", "run", "--project", "outcome-graph", "python", "outcome-graph/src/assign.py", "--docket", docket, "--budget", "22"],
        ["uv", "run", "--project", "outcome-graph", "python", "outcome-graph/src/build.py", "--docket", docket],
    ]  # fmt: skip
    db.q("UPDATE rules SET status = 'processing', updated_at = now() WHERE docket = %s", docket)
    for cmd in steps:
        env = {"DOCKET_IDS": docket, "DATA_DIR": str(ROOT / "data")}
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, **env})
        if r.returncode:
            db.q("UPDATE rules SET status = 'failed', error = %s WHERE docket = %s", r.stderr[-1500:], docket)
            return f"{docket}: failed at {cmd[-3] if len(cmd) > 3 else cmd}"
    return f"{docket}: built"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, help="seconds between runs; omit for one pass")
    ap.add_argument("--build", action="store_true", help="run the pipeline for rules whose response document is on disk")
    a = ap.parse_args()
    while True:
        out = once(a.build)
        print("\n".join(out["log"]), flush=True)
        if not a.loop:
            db.close()
            return 0
        time.sleep(a.loop)


if __name__ == "__main__":
    raise SystemExit(main())
