"""Features that span every rule: organization scorecards, the methods page and its accuracy review,
"this looks wrong" reports, preparing for a rule that is open for comment, the deadline calendar,
the inbox, first-party usage events, and the search behind the command palette.

server.py calls `setup(store, coach)` and includes `router`. Nothing here calls a model: all of it
works while the AI is offline.
"""

from __future__ import annotations

import io
import json
import math
import os
import random
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

import config
import db
from auth import Caller, caller, require_user
from store import Store, _outcome, available, org_key

router = APIRouter()
_S = _C = None  # store(docket) and coach(docket) from server.py

ADMINS = {e.strip().lower() for e in re.split(r"[,;]", os.environ.get("ADMIN_EMAILS", "")) if e.strip()}  # ";" works inside gcloud --set-env-vars
GROUP = {"utility": "Utilities", "advocacy": "Advocacy groups", "trade": "Trade groups", "state": "States",
         "local": "Local governments", "federal": "Federal agencies", "industry": "Industry", "labor": "Labor",
         "academic": "Academics", "tribal": "Tribes", "other": "Other or untagged", "unknown": "Other or untagged"}  # fmt: skip


def setup(store_fn, coach_fn) -> None:
    global _S, _C
    _S, _C = store_fn, coach_fn


def stores() -> list[Store]:
    return [_S(d) for d in available(config.DATA_ROOT)]


def _share(r: dict) -> float | None:
    dec = r["won"] + r["lost"] + r["partly"]
    return (r["won"] + 0.5 * r["partly"]) / dec if dec else None


def _blank() -> dict:
    return {"won": 0, "partly": 0, "lost": 0, "no_change": 0}


# ------------------------------------------------------------------ organizations across rules
_ORG_LOCK = threading.Lock()
_ORG_INDEX: dict | None = None


def org_index() -> dict:
    """Every organization that commented on any mapped rule, built once. Concurrent first callers
    wait for the one build instead of each running it (a cold instance gets several at once)."""
    global _ORG_INDEX
    if _ORG_INDEX is None:
        with _ORG_LOCK:
            if _ORG_INDEX is None:
                _ORG_INDEX = _build_org_index()
    return _ORG_INDEX


def _build_org_index() -> dict:
    """Every organization that commented on any mapped rule, merged across rules and spellings."""
    sts = {st.docket: st for st in stores()}
    idx: dict[str, dict] = {}
    for st in sts.values():
        for n in st.nodes.values():
            k = n.get("slug")
            if n["kind"] != "org" or not k:
                continue
            o = idx.setdefault(k, {"slug": k, "names": Counter(), "groups": Counter(), "excerpts": 0, "rules": {}})
            o["names"][n["label"]] += 1 + n.get("comments", 0)
            o["groups"][n.get("stakeholder") or "unknown"] += 1 + n.get("comments", 0)
            o["excerpts"] += n.get("comments", 0)
            r = o["rules"].setdefault(st.short, {"short": st.short, "docket": st.docket, "title": st.meta.get("title"),
                                                 "final": st.meta.get("final"), "excerpts": 0, "positions": {}})  # fmt: skip
            r["excerpts"] += n.get("comments", 0)
            r.setdefault("ids", []).append((n.get("comments", 0), n["id"]))
            for a, e in st.adj[n["id"]]:
                if st.nodes[a]["kind"] == "ask" and e["kind"] in ("supports", "opposes"):
                    r["positions"].setdefault(a, "for" if e["kind"] == "supports" else "against")
    # a commenter filed under its acronym alone ("AWWA") is the organization that acronym belongs to
    owner: dict[str, str] = {}
    for k, o in idx.items():
        for name in o["names"]:
            m = re.search(r"\(([A-Z][A-Za-z&.\-]{1,9})\)\s*$", name)
            if m and m.group(1).lower() != k:
                owner.setdefault(m.group(1).lower().replace(".", ""), k)
    for k in [k for k in idx if k in owner and owner[k] in idx]:
        src, dst = idx.pop(k), idx[owner[k]]
        dst["names"].update(src["names"]); dst["groups"].update(src["groups"]); dst["excerpts"] += src["excerpts"]
        for short, r in src["rules"].items():
            d = dst["rules"].setdefault(short, {**r, "positions": {}, "excerpts": 0, "ids": []})
            d["excerpts"] += r["excerpts"]; d["ids"] += r["ids"]
            for a, side in r["positions"].items():
                d["positions"].setdefault(a, side)
    acr: dict[str, str] = {}
    for o in idx.values():
        names = [n for n, _ in o["names"].most_common()]
        o["name"] = re.sub(r"\s*\([^)]*\)\s*$", "", names[0]).strip()
        o["acronym"] = next((m.group(1) for n in names if (m := re.search(r"\(([A-Z][A-Za-z&.\-]{1,9})\)\s*$", n))), None)
        if o["acronym"]:
            acr.setdefault(o["acronym"].lower(), o["slug"])
        o["group"] = o["groups"].most_common(1)[0][0]
        if o["group"] == "unknown":
            o["group"] = "other"
        tot = _blank()
        for short, r in o["rules"].items():
            st = sts[r["docket"]]
            rec = _blank()
            for a, side in r["positions"].items():
                rec[_outcome(st.nodes[a].get("verdict"), side)] += 1
            r["record"] = rec
            for k in tot:
                tot[k] += rec[k]
        o["record"] = tot
        o["asks"] = sum(tot.values())
        o["decided"] = tot["won"] + tot["lost"] + tot["partly"]
        o["share"] = _share(tot)
    # each group's average, and a rank among organizations with enough decided asks to compare
    peers: dict[str, list[float]] = defaultdict(list)
    ranked = sorted((o for o in idx.values() if o["decided"] >= 8), key=lambda o: -o["share"])
    for i, o in enumerate(ranked):
        o["rank"] = i + 1
        peers[o["group"]].append(o["share"])
    return {"orgs": idx, "acronyms": acr, "ranked_n": len(ranked),
            "peers": {g: {"mean": sum(v) / len(v), "n": len(v)} for g, v in peers.items()}}


def _org_summary(o: dict) -> dict:
    return {"slug": o["slug"], "name": o["name"], "acronym": o["acronym"], "group": o["group"],
            "group_label": GROUP.get(o["group"], o["group"]), "rules": sorted(o["rules"]), "asks": o["asks"],
            "decided": o["decided"], "share": o["share"], "excerpts": o["excerpts"], "record": o["record"]}  # fmt: skip


def find_orgs(q: str, limit: int = 8) -> list[dict]:
    ix = org_index()
    q = q.strip().lower()
    if not q:
        return [_org_summary(o) for o in sorted(ix["orgs"].values(), key=lambda o: -o["excerpts"])[:limit]]
    hits = []
    if q in ix["acronyms"]:
        hits.append((100, ix["orgs"][ix["acronyms"][q]]))
    for o in ix["orgs"].values():
        name = o["name"].lower()
        if q in name or (o["acronym"] and q == o["acronym"].lower()):
            score = (50 if name.startswith(q) else 20) + math.log10(1 + o["excerpts"]) * 5
            hits.append((score, o))
    seen, out = set(), []
    for _, o in sorted(hits, key=lambda x: -x[0]):
        if o["slug"] not in seen:
            seen.add(o["slug"])
            out.append(_org_summary(o))
    return out[:limit]


@router.get("/api/orgs")
def orgs(q: str = "", limit: int = 8) -> list[dict]:
    return find_orgs(q, min(limit, 50))


@router.get("/api/org/{slug}")
def org(slug: str) -> dict:
    ix = org_index()
    o = ix["orgs"].get(slug) or ix["orgs"].get(ix["acronyms"].get(slug.lower(), ""))
    if not o:
        raise HTTPException(404, "No organization by that name in the mapped rules")
    rules = []
    for short, r in sorted(o["rules"].items(), key=lambda x: x[1].get("final") or "", reverse=True):
        st = _S(r["docket"])
        asks = []
        for a, side in r["positions"].items():
            n, d = st.nodes[a], st.details.get(a, {})
            asks.append({"id": a, "label": n["label"], "verdict": n.get("verdict"), "side": side,
                         "outcome": _outcome(n.get("verdict"), side), "changed": bool(n.get("changed")),
                         "code": n.get("code"), "quote": d.get("quote"), "final_rule_change": d.get("final_rule_change"),
                         "page": st.cites.get(a, {}).get("page"),
                         "with": sum(1 for x, e in st.adj[a] if st.nodes[x]["kind"] == "org")})  # fmt: skip
        order = {"won": 0, "partly": 1, "lost": 2, "no_change": 3}
        asks.sort(key=lambda x: (order[x["outcome"]], not x["changed"], x["code"] or ""))
        rules.append({k: r[k] for k in ("short", "docket", "title", "final", "excerpts", "record")}
                     | {"asks": asks, "node": max(r["ids"])[1]})
    peer = ix["peers"].get(o["group"])
    return _org_summary(o) | {"names": [n for n, _ in o["names"].most_common(6)], "rank": o.get("rank"),
                              "ranked_n": ix["ranked_n"], "peer": peer and {**peer, "label": GROUP.get(o["group"])},
                              "rule_list": rules}  # fmt: skip


@router.get("/og/org/{slug}.png")
def og_org(slug: str) -> Response:
    """A share card for an organization's scorecard (1200x630), drawn with Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    o = org(slug)
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), (7, 9, 15))
    dr = ImageDraw.Draw(im)
    F = lambda s: ImageFont.load_default(size=s)  # noqa: E731
    dr.text((72, 64), "OVERSIGHT", fill=(143, 182, 255), font=F(26))
    name = o["name"] if len(o["name"]) <= 46 else o["name"][:45] + "…"
    dr.text((72, 118), name, fill=(231, 235, 243), font=F(54))
    dr.text((72, 190), f"{o['group_label']} · {', '.join(o['rules'])}", fill=(138, 150, 173), font=F(28))
    pct = f"{round(100 * o['share'])}%" if o["share"] is not None else "n/a"
    dr.text((72, 270), pct, fill=(61, 220, 151), font=F(150))
    dr.text((72, 440), f"of {o['decided']} decided asks went their way", fill=(201, 209, 224), font=F(32))
    x, y, w, h = 72, 520, W - 144, 26
    cols = {"won": (61, 220, 151), "partly": (245, 196, 81), "lost": (255, 107, 107), "no_change": (91, 101, 121)}
    tot = sum(o["record"].values()) or 1
    for k in ("won", "partly", "lost", "no_change"):
        ww = round(w * o["record"][k] / tot)
        if ww:
            dr.rectangle([x, y, x + ww, y + h], fill=cols[k])
            x += ww
    dr.text((72, 566), "What EPA did with their comments, from EPA's own response documents", fill=(111, 122, 144), font=F(22))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


class FollowOrg(BaseModel):
    slug: str
    on: bool = True


@router.post("/api/follow-org")
def follow_org(body: FollowOrg, c: Caller = Depends(require_user)) -> dict:
    if body.slug not in org_index()["orgs"]:
        raise HTTPException(404, "No such organization")
    if body.on:
        db.q("INSERT INTO org_follows (user_id, org_key) VALUES (%s, %s) ON CONFLICT DO NOTHING", c.user["id"], body.slug)
    else:
        db.q("DELETE FROM org_follows WHERE user_id = %s AND org_key = %s", c.user["id"], body.slug)
    return {"org_follows": org_follows(c.user["id"])}


def org_follows(user_id) -> list[str]:
    return [r["org_key"] for r in db.q("SELECT org_key FROM org_follows WHERE user_id = %s ORDER BY created_at", user_id)]


# ------------------------------------------------------------------ methods, accuracy, review
def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


@router.get("/api/methods")
def methods() -> dict:
    """What the record is built from, and the checks on it: automated ones for every ask, and
    people's reviews of a random sample."""
    rules = []
    for st in stores():
        asks = [n for n in st.nodes.values() if n["kind"] == "ask"]
        orgs = [n for n in st.nodes.values() if n["kind"] == "org"]
        named = sum(1 for a in asks if any(st.nodes[x]["kind"] == "org" for x, _ in st.adj[a["id"]]))
        verified = sum(1 for a in asks if st.details.get(a["id"], {}).get("quote_verified"))
        tagged = sum(1 for o in orgs if (o.get("stakeholder") or "unknown") not in ("unknown", "other"))
        s = st.stats
        rules.append({"short": st.short, "title": st.meta.get("title"), "docket": st.docket, "final": st.meta.get("final"),
                      "asks": len(asks), "quotes_verified": verified, "cited": sum(1 for a in asks if a["id"] in st.cites),
                      "named": named, "commenters": len(orgs), "tagged": tagged, "excerpts": s.get("comments") or 0,
                      "excerpts_tied": s.get("excerpts_tied_to_ask") or 0,
                      "usd": round((s.get("usd_extraction") or 0) + (s.get("usd_assign") or 0), 2)})  # fmt: skip
    rev = {"n": 0}
    if db.enabled():
        r = db.one("""SELECT count(*) n, count(*) FILTER (WHERE verdict_ok) v, count(*) FILTER (WHERE ask_ok) a,
                      count(DISTINCT user_id) people FROM reviews""") or {}  # fmt: skip
        n = r.get("n") or 0
        rev = {"n": n, "people": r.get("people") or 0,
               "verdict": {"ok": r.get("v") or 0, "rate": (r.get("v") or 0) / n if n else None, "ci": _wilson(r.get("v") or 0, n)},
               "ask": {"ok": r.get("a") or 0, "rate": (r.get("a") or 0) / n if n else None, "ci": _wilson(r.get("a") or 0, n)},
               "reports": (db.one("SELECT count(*) n FROM reports") or {}).get("n", 0)}  # fmt: skip
    return {"rules": rules, "review": rev, "model": os.environ.get("EXTRACT_MODEL", "Claude (via Google Vertex AI)")}


@router.get("/api/review/next")
def review_next(c: Caller = Depends(caller)) -> dict:
    """A random ask to check, preferring ones nobody has reviewed. Context is EPA's own paragraph."""
    done: set[tuple[str, str]] = set()
    counts: Counter = Counter()
    if db.enabled():
        for r in db.q("SELECT docket, ask_id, user_id FROM reviews"):
            counts[(r["docket"], r["ask_id"])] += 1
            if c.user and r["user_id"] == c.user["id"]:
                done.add((r["docket"], r["ask_id"]))
    pool = [(st, a) for st in stores() for a in st.nodes.values() if a["kind"] == "ask" and (st.docket, a["id"]) not in done]
    if not pool:
        raise HTTPException(404, "You've reviewed every ask. Thank you.")
    least = min(counts[(st.docket, a["id"])] for st, a in pool)
    st, a = random.choice([(st, a) for st, a in pool if counts[(st.docket, a["id"])] == least])
    d, ci = st.details.get(a["id"], {}), st.cites.get(a["id"], {})
    return {"docket": st.docket, "rule": st.short, "id": a["id"], "code": a.get("code"), "ask": a["label"],
            "verdict": a.get("verdict"), "quote": d.get("quote"), "final_rule_change": d.get("final_rule_change"),
            "context": ci.get("context"), "page": ci.get("page"), "reviewed_by_you": len(done)}  # fmt: skip


class Review(BaseModel):
    docket: str
    ask_id: str
    verdict_ok: bool
    ask_ok: bool
    right_verdict: str | None = None
    note: str | None = None


@router.post("/api/review")
def review(body: Review, c: Caller = Depends(require_user)) -> dict:
    st = _S(body.docket)
    if body.ask_id not in st.nodes:
        raise HTTPException(404, "No such ask")
    db.q("""INSERT INTO reviews (user_id, docket, ask_id, verdict_ok, ask_ok, right_verdict, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, docket, ask_id) DO UPDATE SET verdict_ok = EXCLUDED.verdict_ok,
              ask_ok = EXCLUDED.ask_ok, right_verdict = EXCLUDED.right_verdict, note = EXCLUDED.note""",
         c.user["id"], st.docket, body.ask_id, body.verdict_ok, body.ask_ok, body.right_verdict, (body.note or "")[:1000])  # fmt: skip
    return {"ok": True}


class Report(BaseModel):
    docket: str | None = None
    node_id: str | None = None
    problem: str
    note: str | None = None
    url: str | None = None


@router.post("/api/report")
def report(body: Report, c: Caller = Depends(caller)) -> dict:
    if not db.enabled():
        raise HTTPException(503, "Reports need the database")
    if not db.take(c.who, "report", 20):
        raise HTTPException(429, "That's a lot of reports for one day. Thank you; try again tomorrow.")
    db.q("INSERT INTO reports (who, docket, node_id, problem, note, url) VALUES (%s, %s, %s, %s, %s, %s)",
         c.user["email"] if c.user else c.who, body.docket, body.node_id, body.problem[:80], (body.note or "")[:2000],
         (body.url or "")[:500])  # fmt: skip
    return {"ok": True}


# ------------------------------------------------------------------ preparing for an open rule
_FR_CACHE: dict[str, tuple[float, dict]] = {}


def fr_doc(docket: str) -> dict:
    """The Federal Register's abstract for a docket's newest document. Public API, cached a day."""
    hit = _FR_CACHE.get(docket)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    out: dict = {}
    try:
        r = httpx.get("https://www.federalregister.gov/api/v1/documents.json", timeout=8,
                      headers={"User-Agent": "oversight"},
                      params=[("conditions[docket_id]", docket), ("order", "newest"), ("per_page", "5")] +
                             [("fields[]", f) for f in ("title", "abstract", "type", "publication_date",
                                                        "comments_close_on", "html_url", "action")])  # fmt: skip
        res = r.json().get("results", []) if r.status_code == 200 else []
        out = next((x for x in res if x.get("abstract")), res[0] if res else {})
    except Exception:  # noqa: BLE001  (the page still works without the abstract)
        out = {}
    _FR_CACHE[docket] = (time.time(), out)
    return out


@router.get("/api/prepare/{docket}")
def prepare(docket: str) -> dict:
    """For a proposed rule: its timeline, and the closest past asks across every mapped rule, split
    into what EPA adopted and what it declined."""
    row = db.one("SELECT * FROM rules WHERE docket = %s", docket) if db.enabled() else None
    if not row:
        raise HTTPException(404, "That docket isn't on the watch list")
    fr = fr_doc(docket)
    # Match each point of the abstract on its own, as the coach does with a draft: one long abstract
    # embedded whole drifts toward generic process asks. An ask's score is its best match to any point.
    abstract = fr.get("abstract") or ""
    points = [row["title"]] + [p.strip() for p in re.split(r"(?<=[.;])\s+(?=[A-Z])", abstract) if len(p.strip()) >= 50][:10]
    co = _C(next(iter(available(config.DATA_ROOT))))
    best: dict[str, dict] = {}
    for p in points:
        for h in co.similar_asks(p, limit=12):
            if h["match"] >= 0.62 and (h["id"] not in best or h["match"] > best[h["id"]]["match"]):
                best[h["id"]] = {**h, "point": p}
    hits = sorted(best.values(), key=lambda h: -h["match"])[:30]
    for h in hits:  # plain ids plus the rule's short name, so the page can link to the map
        st_, aid = co.resolve(h["id"]) or (None, h["id"])
        h["rule_short"], h["id"] = (st_.short if st_ else ""), aid
    tally = Counter(h["verdict"] for h in hits)
    today = date.today()
    close = row["comments_close"]
    return {"docket": docket, "title": row["title"], "status": row["status"],
            "proposed_on": str(row["proposed_on"] or ""), "final_on": str(row["final_on"] or ""),
            "comments_close": str(close or ""), "days_left": (close - today).days if close and close >= today else None,
            "fr_url": row["fr_url"] or fr.get("html_url"), "abstract": fr.get("abstract"), "action": fr.get("action"),
            "regs_url": f"https://www.regulations.gov/docket/{docket}",
            "related": hits, "tally": dict(tally)}  # fmt: skip


# ------------------------------------------------------------------ calendar of deadlines
def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/calendar.ics")
def calendar(request: Request) -> Response:
    """Comment deadlines and final rules as all-day events. Subscribe once; the watcher keeps it current."""
    base = str(request.base_url).rstrip("/")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Undersigned//Oversight//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:EPA drinking water rules (Oversight)", "X-PUBLISHED-TTL:PT12H"]  # fmt: skip
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for r in (db.rules() if db.enabled() else []):
        for kind, day, label in (("close", r["comments_close"], "Comments close"), ("final", r["final_on"], "Final rule")):
            if not day or day.year < 2019:
                continue
            url = f"{base}/prepare/{r['docket']}" if kind == "close" else f"https://www.regulations.gov/docket/{r['docket']}"
            nxt = date.fromordinal(day.toordinal() + 1)
            lines += ["BEGIN:VEVENT", f"UID:{r['docket']}-{kind}@oversight", f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{nxt:%Y%m%d}",
                      f"SUMMARY:{_ics_escape(label + ': ' + r['title'][:120])}",
                      f"DESCRIPTION:{_ics_escape('Docket ' + r['docket'] + '. ' + url)}", f"URL:{url}", "END:VEVENT"]  # fmt: skip
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})  # fmt: skip


# ------------------------------------------------------------------ inbox
@router.get("/api/notifications")
def notifications(c: Caller = Depends(require_user)) -> dict:
    uid = c.user["id"]
    db.q("""INSERT INTO notifications (user_id, kind, title, body, url, dedupe_key)
            VALUES (%s, 'welcome', 'Welcome to Oversight',
                    'Follow a rule or an organization and updates land here: new proposed rules, comment deadlines, and final decisions.',
                    '/#yours', 'welcome') ON CONFLICT DO NOTHING""", uid)  # fmt: skip
    rows = db.q("""SELECT id, kind, title, body, url, created_at, read_at FROM notifications
                   WHERE user_id = %s ORDER BY created_at DESC LIMIT 30""", uid)  # fmt: skip
    return {"unread": sum(1 for r in rows if not r["read_at"]), "items": rows}


@router.post("/api/notifications/read")
def notifications_read(c: Caller = Depends(require_user)) -> dict:
    db.q("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL", c.user["id"])
    return {"ok": True}


# ------------------------------------------------------------------ usage events
class Event(BaseModel):
    name: str
    path: str | None = None
    props: dict | None = None
    anon: str | None = None


@router.post("/api/e")
def event(body: Event, c: Caller = Depends(caller)) -> Response:
    if db.enabled() and re.fullmatch(r"[a-z_:.]{1,40}", body.name):
        props = json.loads(json.dumps(body.props or {})[:2000]) if len(json.dumps(body.props or {})) <= 2000 else {}
        db.q("INSERT INTO events (anon, user_id, name, path, props) VALUES (%s, %s, %s, %s, %s)",
             (body.anon or "")[:64], c.user["id"] if c.user else None, body.name, (body.path or "")[:300], db.J(props))  # fmt: skip
    return Response(status_code=204)


@router.get("/api/metrics")
def metrics(days: int = 14, c: Caller = Depends(require_user)) -> dict:
    """For the team only (ADMIN_EMAILS): visitors, the main funnel, and open problem reports."""
    if (c.user.get("email") or "").lower() not in ADMINS:
        raise HTTPException(403, "Team only")
    days = max(1, min(days, 90))
    daily = db.q("""SELECT date_trunc('day', at)::date AS day, count(DISTINCT anon) AS visitors, count(*) AS events
                    FROM events WHERE at > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 1""", days)  # fmt: skip
    names = db.q("""SELECT name, count(*) n, count(DISTINCT anon) people FROM events
                    WHERE at > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC LIMIT 40""", days)  # fmt: skip
    funnel = [(k, (db.one(f"SELECT count(DISTINCT anon) n FROM events WHERE name = %s AND at > now() - make_interval(days => %s)", k, days) or {}).get("n", 0))
              for k in ("view:landing", "view:rule", "open:ask", "open:list", "ask:sent", "coach:run", "view:org", "signin")]  # fmt: skip
    reports = db.q("SELECT id, who, docket, node_id, problem, note, url, created_at FROM reports WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 50")
    users = (db.one("SELECT count(*) n FROM users") or {}).get("n", 0)
    return {"days": days, "daily": daily, "events": names, "funnel": funnel, "reports": reports, "users": users}


# ------------------------------------------------------------------ command palette search
@router.get("/api/find")
def find(q: str) -> dict:
    """Everything a query could mean, across rules: organizations, rules, topics and asks."""
    q = q.strip()
    if len(q) < 2:
        return {"orgs": find_orgs("", 5), "rules": [], "items": []}
    ql = q.lower()
    rules = [{"short": st.short, "title": st.meta.get("title"), "url": f"/rule/{st.short}"}
             for st in stores() if ql in (st.meta.get("title") or "").lower() or ql == st.short.lower()]  # fmt: skip
    items = []
    for st in stores():
        for h in st.search(q, None, 6):
            if h["kind"] in ("ask", "topic", "section"):
                items.append({"rule": st.short, "id": h["id"], "kind": h["kind"], "label": h["label"],
                              "verdict": h.get("verdict"), "code": h.get("code"),
                              "url": f"/rule/{st.short}?n={h['id']}"})  # fmt: skip
    return {"orgs": find_orgs(q, 5), "rules": rules, "items": items[:12]}
