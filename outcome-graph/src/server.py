"""Oversight's API and page.

    uv run uvicorn server:app --app-dir src --port 8077

Pages: `/` is the landing page (rule gallery, sign-in, your drafts and chats); `/rule/<SHORT>` is
the graph for one rule with Iris, the comment coach, Inspect and the Scoreboard.

Accounts are optional. Signed out, everything is browsable and Iris and the coach work a few times
a day; nothing is stored, and a chat lives only in the browser tab. Signed in (Firebase Auth), chats,
drafts and coach runs are saved in Postgres, Iris knows who you are and what you asked before, and
you can follow rules. See auth.py, db.py and agent.py.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import config
import db
from auth import Caller, caller, require_user
from coach import Coach, agent_system, parse_reply
from mcp_server import build as build_tools
from store import Store, _outcome, available
import hub
import mcp_remote

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web" / "dist"

MCP = mcp_remote.build()


@asynccontextmanager
async def _lifespan(_app):
    _startup()
    async with MCP.session_manager.run():  # the mounted MCP app's own lifespan never runs
        yield


app = FastAPI(title="Oversight", lifespan=_lifespan)
# graph.json is about 1 MB of JSON and the JS bundle about 850 KB; both shrink 5-7x. Starlette's
# gzip leaves text/event-stream alone, so Iris and the coach still stream.
app.add_middleware(GZipMiddleware, minimum_size=1024)
_stores: dict[str, Store] = {}
_coaches: dict[str, Coach] = {}
_tools: dict[str, object] = {}


# ------------------------------------------------------------------ rules in memory
def store(docket: str | None = None) -> Store:
    docket = docket or config.DEFAULT_DOCKET
    built = available(config.DATA_ROOT)
    if docket not in built:
        hit = next((d for d, m in built.items() if (m.get("short") or "").lower() == docket.lower()), None)
        if not hit:
            raise HTTPException(404, f"No outcome record for {docket}")
        docket = hit
    if docket not in _stores:
        _stores[docket] = Store(docket, data_root=config.DATA_ROOT)
    return _stores[docket]


def coach(docket: str | None = None) -> Coach:
    st = store(docket)
    if st.docket not in _coaches:
        _coaches[st.docket] = Coach(st, [store(d) for d in available(config.DATA_ROOT) if d != st.docket])
    return _coaches[st.docket]


def tools(docket: str):
    st = store(docket)
    if st.docket not in _tools:
        _tools[st.docket] = build_tools(st, lambda: coach(st.docket))
    return _tools[st.docket]


# ------------------------------------------------------------------ public endpoints
@app.get("/api/config")
def client_config() -> dict:
    """What the page needs to start: whether accounts and the agent are on, and how to sign in."""
    return {
        "accounts": db.enabled(),
        "agent": config.AGENT,
        "backend": config.LLM_BACKEND if config.AGENT else None,
        "model": (config.MODEL if config.LLM_BACKEND == "vertex" else config.CLI_MODEL) if config.AGENT else None,
        "firebase": {"apiKey": config.FIREBASE_API_KEY, "authDomain": config.FIREBASE_AUTH_DOMAIN,
                     "projectId": config.FIREBASE_PROJECT},
        "authEmulator": config.AUTH_EMULATOR_PUBLIC if config.AUTH_EMULATOR else None,
        "limits": {f"{k}_{w}": v for (k, w), v in config.LIMITS.items()},
    }  # fmt: skip


@app.get("/api/left")
def left(request: Request) -> dict:
    """What this visitor has left today, so the page can say so before they press the button."""
    c = caller(request)
    used = db.used(c.who) if db.enabled() else {}
    return {"signed_in": c.signed_in, "offline": _offline(),
            "left": {k: max(0, config.LIMITS[(c.kind, k)] - used.get(k, 0)) for k in ("ask", "coach")},
            "limit": {k: config.LIMITS[(c.kind, k)] for k in ("ask", "coach")}}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "agent": config.AGENT, "accounts": db.enabled(), "rules": len(available(config.DATA_ROOT))}


@app.get("/api/dockets")
def dockets() -> dict:
    return {"default": config.DEFAULT_DOCKET, "dockets": available(config.DATA_ROOT)}


@app.get("/api/rules")
def rules() -> list[dict]:
    """The landing page's gallery: built rules first, then what the watcher found since 2019."""
    built = available(config.DATA_ROOT)
    if not db.enabled():
        return [{**m, "status": "ready"} for m in built.values()]
    out = []
    for r in db.rules():
        when = r["final_on"] or r["comments_close"] or r["proposed_on"]
        if r["status"] != "ready" and (not when or when.year < 2019):
            continue
        m = built.get(r["docket"], {})
        out.append({**{k: (str(v) if v is not None and k.endswith(("_on", "close")) else v) for k, v in r.items()
                       if k in ("docket", "short", "title", "status", "proposed_on", "final_on", "comments_close",
                                "fr_url", "asks", "changed")},
                    "proposed": m.get("proposed"), "final": m.get("final"), "comments": m.get("comments"),
                    "verdicts": m.get("verdicts")})  # fmt: skip
    return out


@app.get("/api/watcher")
def watcher() -> dict:
    """When the rule watcher last ran, for the landing page."""
    if not db.enabled():
        return {"last": None}
    r = db.one("SELECT started_at, finished_at, seen, new FROM ingest_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    return {"last": r}


@app.get("/api/graph")
def graph(docket: str | None = None) -> Response:
    return Response(store(docket).graph_json, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=300"})  # fmt: skip


@app.get("/api/node/{nid:path}")
def node(nid: str, offset: int = 0, docket: str | None = None) -> dict:
    out = store(docket).node(nid, offset, max_chars=20000)
    if "error" in out:
        raise HTTPException(404, out["error"])
    return out


@app.get("/api/search")
def search(q: str, kind: str | None = None, limit: int = 12, docket: str | None = None) -> list[dict]:
    return store(docket).search(q, kind, limit)


@app.get("/api/stakeholders")
def stakeholders(scope: str | None = None, docket: str | None = None) -> dict:
    return store(docket).compare_stakeholders(scope)


# ------------------------------------------------------------------ lists without the model
@app.get("/api/asks")
def asks(docket: str | None = None, verdict: str | None = None, changed: bool = False, group: str | None = None,
         ids: str | None = None, limit: int = 600) -> dict:
    """The asks behind a filter, with EPA's answer and who asked: the list view under the map."""
    st = store(docket)
    want = set(ids.split(",")) if ids else None
    out = []
    for n in st.nodes.values():
        if n["kind"] != "ask" or (want is not None and n["id"] not in want):
            continue
        if verdict and n.get("verdict") != verdict:
            continue
        if changed and not n.get("changed"):
            continue
        orgs = [(o, e) for o, e in st.adj[n["id"]] if st.nodes[o]["kind"] == "org"]
        if group and not any(st.nodes[o].get("stakeholder") == group for o, _ in orgs):
            continue
        d = st.details.get(n["id"], {})
        sup = sorted((o for o, e in orgs if e["kind"] == "supports"), key=lambda o: -st.nodes[o].get("comments", 0))
        mine = [o for o in sup if group and st.nodes[o].get("stakeholder") == group]
        side = outcome = None
        if group:  # which side the group took (majority of its commenters) and whether it won
            g_for = sum(1 for o, e in orgs if st.nodes[o].get("stakeholder") == group and e["kind"] == "supports")
            g_against = sum(1 for o, e in orgs if st.nodes[o].get("stakeholder") == group and e["kind"] == "opposes")
            side = "for" if g_for >= g_against else "against"
            outcome = _outcome(n.get("verdict"), side)
            if side == "against":
                mine = [o for o, e in orgs if st.nodes[o].get("stakeholder") == group and e["kind"] == "opposes"]
        out.append({
            "id": n["id"], "label": n["label"], "verdict": n.get("verdict"), "changed": bool(n.get("changed")),
            "code": n.get("code"), "quote": d.get("quote"), "final_rule_change": d.get("final_rule_change"),
            "asked_by": [st.nodes[o]["label"] for o in (mine or sup)[:3]], "asked_by_n": len(sup),
            "group_n": len(mine), "side": side, "outcome": outcome, "page": st.cites.get(n["id"], {}).get("page"),
        })  # fmt: skip
    out.sort(key=lambda a: (-a["group_n"], -a["asked_by_n"], a["code"] or ""))
    return {"total": len(out), "asks": out[:limit]}


class Similar(BaseModel):
    draft: str
    docket: str | None = None


@app.post("/api/similar")
def similar(body: Similar) -> dict:
    """The coach's first pass, with no model: each point in the draft, and the past asks closest to it.
    Embeddings only, so it works while the AI is offline and costs nothing."""
    text = body.draft.strip()[:6000]
    if len(text) < 40:
        raise HTTPException(400, "Paste a longer draft.")
    co = coach(body.docket)
    chunks = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", text) if len(p.strip()) >= 40][:8]
    points, seen = [], set()
    for c in chunks:
        hits = [h for h in co.similar_asks(c, limit=3, rule=co.s.short) if h["match"] >= 0.62 and h["id"] not in seen][:2]
        seen.update(h["id"] for h in hits)
        points.append({"point": c, "asks": hits})
    return {"points": points}


# ------------------------------------------------------------------ account
class Profile(BaseModel):
    name: str | None = None
    org_type: str | None = None
    org_name: str | None = None


def _me(c: Caller) -> dict:
    u = c.user
    used = db.used(c.who)
    return {
        "user": {k: u[k] for k in ("id", "email", "name", "org_type", "org_name")} | {"id": str(u["id"])},
        "follows": db.follows(u["id"]),
        "org_follows": hub.org_follows(u["id"]),
        "drafts": len(db.drafts(u["id"])),
        "conversations": len(db.conversations(u["id"])),
        "left": {k: max(0, config.LIMITS[("user", k)] - used.get(k, 0)) for k in ("ask", "coach")},
    }


@app.get("/api/me")
def me(c: Caller = Depends(require_user)) -> dict:
    return _me(c)


@app.put("/api/me")
def update_me(body: Profile, c: Caller = Depends(require_user)) -> dict:
    db.update_profile(c.user["id"], body.org_type, body.org_name, body.name)
    c.user = db.one("SELECT * FROM users WHERE id = %s", c.user["id"])
    return _me(c)


class Follow(BaseModel):
    docket: str
    on: bool = True


@app.post("/api/follow")
def follow(body: Follow, c: Caller = Depends(require_user)) -> dict:
    db.follow(c.user["id"], body.docket, body.on)
    return {"follows": db.follows(c.user["id"])}


@app.get("/api/conversations")
def conversations(docket: str | None = None, c: Caller = Depends(require_user)) -> list[dict]:
    return [{**r, "id": str(r["id"]), "user_id": None} for r in db.conversations(c.user["id"], docket)]


@app.get("/api/conversations/{cid}")
def conversation(cid: str, c: Caller = Depends(require_user)) -> dict:
    conv = db.conversation(cid, c.user["id"])
    if not conv:
        raise HTTPException(404, "No such conversation")
    return {"id": cid, "docket": conv["docket"], "title": conv["title"], "messages": db.messages(cid)}


@app.get("/api/drafts")
def drafts(docket: str | None = None, c: Caller = Depends(require_user)) -> list[dict]:
    return [{**r, "id": str(r["id"])} for r in db.drafts(c.user["id"], docket)]


@app.get("/api/drafts/{did}")
def draft(did: str, c: Caller = Depends(require_user)) -> dict:
    d = db.draft(did, c.user["id"])
    if not d:
        raise HTTPException(404, "No such draft")
    return {**d, "id": str(d["id"]), "user_id": None}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, c: Caller = Depends(require_user)) -> dict:
    if not db.delete_owned("conversations", cid, c.user["id"]):
        raise HTTPException(404, "No such conversation")
    return {"deleted": cid}


@app.delete("/api/drafts/{did}")
def delete_draft(did: str, c: Caller = Depends(require_user)) -> dict:
    if not db.delete_owned("drafts", did, c.user["id"]):
        raise HTTPException(404, "No such draft")
    return {"deleted": did}


# ------------------------------------------------------------------ Iris
IRIS = """You are Iris, the guide inside Oversight. Oversight is the record of what happened to \
public comments on US drinking water rules: every ask commenters made, the agency's answer in its own \
words, who argued each side, and what changed in the final rule.

The user is looking at {title} ({short}, docket {docket}, final rule {final}) as a graph: EPA's \
{topics} response topics around a ring, one dot per ask colored by EPA's verdict, commenters \
inside. Your tools read that graph; ids look like topic:9.7, ask:9.7:2, org:14, sec:141.84.

How to answer:
- Use the tools; never answer from memory. Usually 2 to 4 calls.
{show}- Your answer appears in a small card and may be read aloud. Two to five short sentences, or at \
most five tight bullets. Lead with the answer. Numbers when you have them.
- Name commenters and asks with [[id]] (e.g. [[org:14]]); the page turns each into a chip with \
its name. Write the id instead of the name, never both.
- When you state a verdict, quote EPA's words briefly in quotation marks.
- Plain sentences. No em dashes, no preamble, no closing summary.
- If the record cannot answer, say what it can answer instead.{about}"""


def iris_system(st: Store, c: Caller) -> str:
    about = ""
    if c.user:
        u = c.user
        recent = db.conversations(u["id"], limit=5)
        ds = db.drafts(u["id"])[:5]
        follows = db.follows(u["id"])
        lines = [f"Name: {u.get('name') or 'not given'}"]
        if u.get("org_type") or u.get("org_name"):
            lines.append(f"Organization: {u.get('org_name') or ''} ({u.get('org_type') or 'type not given'})")
        if follows:
            lines.append("Follows: " + ", ".join(follows))
        if recent:
            lines.append("Recent conversations: " + "; ".join(f"\"{r['title']}\" ({r['docket']})" for r in recent))
        if ds:
            lines.append("Saved draft comments: " + "; ".join(f"\"{d['title']}\"" for d in ds))
        about = ("\n\nAbout this signed-in user (use it to make answers relevant to them, e.g. point a "
                 "utility to what utilities won; use my_history when they refer to earlier work):\n- " + "\n- ".join(lines))  # fmt: skip
    show = ("- Then call show_on_graph once with the nodes your answer is about, focusing the most relevant "
            "one. The user sees them light up while you answer.\n") if config.LLM_BACKEND == "vertex" else ""
    return IRIS.format(title=st.meta.get("title"), short=st.short, docket=st.docket, final=st.meta.get("final"),
                       topics=st.stats.get("topics"), about=about, show=show)  # fmt: skip


class Ask(BaseModel):
    question: str
    docket: str | None = None
    conversation_id: str | None = None
    history: list[dict] | None = None  # signed-out only: the tab's own copy of the chat


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n".encode()


def _hours_left() -> int:
    """Hours until the usage day rolls over (Postgres current_date, UTC)."""
    now = datetime.now(timezone.utc)
    return max(1, 24 - now.hour)


def _limit(c: Caller, kind: str):
    """Take one unit of today's quota and return a function that gives it back. Callers give it back
    when the model call fails, so an error never costs anyone a question."""
    if not db.enabled():
        return lambda: None
    cap = config.LIMITS[(c.kind, kind)]
    if not db.take(c.who, kind, cap):
        db.give_back(c.who, kind)
        raise _limit_error(c, kind, cap)
    if c.net and not db.take(c.net, kind, cap * config.NET_FACTOR):
        db.give_back(c.net, kind)
        db.give_back(c.who, kind)
        raise _limit_error(c, kind, cap)

    def release():
        db.give_back(c.who, kind)
        if c.net:
            db.give_back(c.net, kind)
    return release


def _limit_error(c: Caller, kind: str, cap: int) -> HTTPException:
    what = {"ask": "questions", "coach": "comment checks", "speak": "spoken answers"}[kind]
    h = _hours_left()
    msg = f"You've used today's {cap} free {what}. More in about {h} hour{'s' if h != 1 else ''}."
    if not c.signed_in:
        user_cap = config.LIMITS[("user", kind)]
        msg = f"You've used today's {cap} free {what}. Sign in for {user_cap} a day, or come back in about {h} hours."
    return HTTPException(429, {"code": "limit", "message": msg, "signed_in": c.signed_in})


# When Vertex says the Claude quota is exhausted, stop calling it for a while: every visitor gets the
# offline message at once, and nobody's daily quota is touched.
_offline_until = 0.0
OFFLINE_MSG = ("Iris can't answer typed questions yet: the AI model behind her is waiting on cloud quota. "
               "Everything on the map works, and the suggested questions below open the answer from the record.")


def _offline() -> bool:
    return time.time() < _offline_until


def _mark_offline(e: Exception) -> None:
    global _offline_until
    if "429" in str(e) or "Quota exceeded" in str(e):
        _offline_until = time.time() + 600


def _stream(gen) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip


@app.post("/api/ask")
async def ask(body: Ask, request: Request) -> StreamingResponse:
    if not config.AGENT:
        raise HTTPException(503, "Iris is off on this copy.")
    c = caller(request)
    q = body.question.strip()[:2000]
    if not q:
        raise HTTPException(400, "Ask something.")
    if _offline():
        raise HTTPException(503, {"code": "offline", "message": OFFLINE_MSG})
    release = _limit(c, "ask")
    st = store(body.docket)
    conv, history = None, []
    if c.signed_in:
        if body.conversation_id:
            conv = db.conversation(body.conversation_id, c.user["id"])
        if conv:
            history = [{"role": m["role"], "content": m["content"]} for m in db.messages(str(conv["id"]))][-12:]
        else:
            conv = db.new_conversation(c.user["id"], st.docket, q)
    else:
        history = [m for m in (body.history or [])[-12:] if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]

    if conv:  # the question is saved even if the answer fails, so the chat never comes back empty
        db.add_message(str(conv["id"]), "user", q)

    async def run():
        if conv:
            yield _sse({"type": "conversation", "id": str(conv["id"]), "title": conv["title"]})
        done = None
        try:
            async for ev in agent.run(
                system=iris_system(st, c), history=history, prompt=q, srv=tools(st.docket), docket=st.docket,
                history_search=(lambda s: db.search_history(c.user["id"], s)) if c.signed_in else None,
            ):  # fmt: skip
                if ev["type"] == "done":
                    done = ev
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001
            release()
            _mark_offline(e)
            yield _sse({"type": "error", **_friendly(e)})
            return
        if not (done and done.get("text")):
            release()
        elif conv:
            db.add_message(str(conv["id"]), "assistant", done["text"], done.get("trace"), done.get("usd"))

    return _stream(run())


def _friendly(e: Exception) -> dict:
    s = str(e)
    if "429" in s or "Quota exceeded" in s:
        return {"code": "offline", "message": OFFLINE_MSG}
    if "PermissionDenied" in type(e).__name__ or "403" in s:
        return {"code": "offline", "message": OFFLINE_MSG}
    return {"code": "error", "message": "Iris hit a snag answering that. Try again in a moment."}


# ------------------------------------------------------------------ Iris's voice
class Speak(BaseModel):
    text: str


_tts = None
_voice_cache: dict[str, bytes] = {}


@app.post("/api/speak")
def speak(body: Speak, request: Request) -> Response:
    """Text to speech with Google Cloud TTS (Chirp 3 HD). Same credentials as Vertex: no key."""
    global _tts
    text = " ".join(body.text.split())[:1200]
    if not text:
        raise HTTPException(400, "Nothing to say.")
    if text in _voice_cache:
        return Response(_voice_cache[text], media_type="audio/mpeg")
    release = _limit(caller(request), "speak")
    from google.cloud import texttospeech as tts

    if _tts is None:
        _tts = tts.TextToSpeechClient(client_options={"quota_project_id": config.GCP_PROJECT})
    try:
        r = _tts.synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code="en-US", name=config.TTS_VOICE),
            audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3),
        )
    except Exception as e:  # noqa: BLE001
        release()
        raise HTTPException(503, f"Voice unavailable: {type(e).__name__}") from e
    if len(_voice_cache) > 200:
        _voice_cache.clear()
    _voice_cache[text] = r.audio_content
    return Response(r.audio_content, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ comment coach
class Draft(BaseModel):
    draft: str
    docket: str | None = None
    draft_id: str | None = None


COACH_TOOLS = ["find_similar_asks", "search_rule_text", "get_node", "search_comments", "neighbors"]
ASK_RE = re.compile(r"\b(?:[A-Z]{2,6}/)?ask:[\d.]+:\d+\b")


@app.post("/api/coach")
async def coach_draft(body: Draft, request: Request) -> StreamingResponse:
    """The coach as an agent: it decides which past asks, rule paragraphs and comments to read,
    streams each lookup, then returns advice that code has checked. Signed-in drafts are saved."""
    if not config.AGENT:
        raise HTTPException(503, "The comment coach is off on this copy.")
    c = caller(request)
    text = body.draft.strip()[:8000]
    if len(text) < 40:
        raise HTTPException(400, "Paste a longer draft.")
    if _offline():
        raise HTTPException(503, {"code": "offline", "message": OFFLINE_MSG.replace("Iris can't answer typed questions", "The coach can't read drafts").replace(" and the suggested questions below open the answer from the record", "")})
    release = _limit(c, "coach")
    co = coach(body.docket)
    saved = db.save_draft(c.user["id"], co.s.docket, text, body.draft_id) if c.signed_in else None

    async def run():
        if saved:
            yield _sse({"type": "draft", "id": str(saved["id"]), "title": saved["title"]})
        yield _sse({"type": "phase", "step": "read", "text": "Reading your draft"})
        seen: set[str] = set()
        done = None
        try:
            async for ev in agent.run(
                system=agent_system(co.s, available(config.DATA_ROOT)), history=[], prompt="DRAFT COMMENT:\n" + text,
                srv=tools(co.s.docket), docket=co.s.docket, allowed=COACH_TOOLS, ui=False, max_turns=16,
            ):  # fmt: skip
                if ev["type"] == "visit":
                    ids = [i for i in ev["ids"] if ASK_RE.fullmatch(i)]
                    seen.update(ids)
                    yield _sse({"type": "visit", "tool": ev["tool"], "ids": ids[:40]})
                elif ev["type"] == "tool":
                    yield _sse({"type": "tool", "name": ev["name"], "input": ev["input"]})
                elif ev["type"] == "done":
                    done = ev
                elif ev["type"] == "error":
                    yield _sse(ev)
        except Exception as e:  # noqa: BLE001
            release()
            _mark_offline(e)
            yield _sse({"type": "error", **_friendly(e)})
            return
        raw = parse_reply((done or {}).get("text") or "")
        if not raw:
            release()
            yield _sse({"type": "error", "code": "error", "message": "The coach's reply came back garbled. Try again."})
            return
        result = co.clean(raw, {i for i in seen if co.resolve(i)})
        n_tools = len((done or {}).get("trace") or [])
        if saved:
            db.add_coach_run(str(saved["id"]), result, n_tools, done.get("usd"), done.get("ms"))
        yield _sse({"type": "result", **result, "tools": n_tools, "usd": done.get("usd"), "ms": done.get("ms")})

    return _stream(run())


# ------------------------------------------------------------------ startup and pages
def _startup() -> None:
    if db.enabled():
        db.migrate()
        from jobs.watch_rules import ready_rows

        for r in ready_rows(available(config.DATA_ROOT)):
            db.upsert_rule(r)
    # build the cross-rule organization index in the background, so the first search or scorecard
    # on a new instance doesn't pay for it
    threading.Thread(target=hub.org_index, daemon=True).start()
    if config.AGENT:  # embed asks and rule paragraphs in the background so the first coach run is quick
        def warm():
            for d in available(config.DATA_ROOT):
                for ix in coach(d).idx.values():
                    ix.ask_vecs, ix.rule_paras  # noqa: B018

        threading.Thread(target=warm, daemon=True).start()


hub.setup(store, coach)
app.include_router(hub.router)
app.mount("/mcp", MCP.streamable_http_app())


# Pages are revalidated on every load so a deploy is seen at once; the hashed assets they point
# to are cached normally.
NO_CACHE = {"Cache-Control": "no-cache"}

if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/")
    def landing(d: str | None = None):
        if d:  # old links: /?d=PFAS
            return RedirectResponse(f"/rule/{d}")
        return FileResponse(WEB / "index.html", headers=NO_CACHE)

    @app.get("/rule/{short}")
    def rule_page(short: str):
        if short.upper() not in _shorts():
            return _not_found(f"We don't have a map for {short} yet.")
        return FileResponse(WEB / "rule.html", headers=NO_CACHE)

    def _page(name: str, title: str | None = None, desc: str | None = None, image: str | None = None, url: str = ""):
        html = (WEB / f"{name}.html").read_text()
        if title:  # share previews (Slack, LinkedIn, iMessage) read these; the page fills the rest in itself
            esc = lambda x: str(x).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")  # noqa: E731
            meta = (f'<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc or "")}">'
                    f'<meta property="og:type" content="website"><meta name="twitter:card" content="summary_large_image">'
                    + (f'<meta property="og:image" content="{esc(image)}">' if image else "")
                    + f'<meta name="description" content="{esc(desc or "")}">')
            html = html.replace("<title>Oversight</title>", f"<title>{esc(title)}</title>{meta}", 1)
        return HTMLResponse(html, headers=NO_CACHE)

    @app.get("/org/{slug}")
    def org_page(slug: str, request: Request):
        try:
            o = hub.org(slug)
        except HTTPException:
            return _not_found("We don't have that organization in the mapped rules.")
        pct = f"{round(100 * o['share'])}%" if o["share"] is not None else "no decided asks"
        base = str(request.base_url).rstrip("/").replace("http://", "https://") if "run.app" in str(request.base_url) else str(request.base_url).rstrip("/")
        return _page("org", f"{o['name']} · Oversight", f"{pct} of {o['decided']} decided asks went their way on {', '.join(o['rules'])}. "
                     "What EPA did with their comments, from EPA's own response documents.", f"{base}/og/org/{o['slug']}.png")

    @app.get("/methods")
    def methods_page():
        return _page("methods", "Methods · Oversight", "How Oversight reads EPA's response documents, and how accurate it is.")

    @app.get("/connect")
    def connect_page():
        return _page("connect", "Use Oversight in Claude", "Ask your own Claude what happened to public comments on EPA rules.")

    @app.get("/prepare/{docket}")
    def prepare_page(docket: str):
        return _page("prepare", "Prepare a comment · Oversight", "What EPA adopted and declined when commenters made similar points before.")

    @app.get("/admin")
    def admin_page():
        return _page("admin")

    @app.get("/rtc/{short}.pdf")
    def rtc_pdf(short: str):
        """EPA's response-to-comments document, so citations can open it at the quoted page."""
        for d, m in available(config.DATA_ROOT).items():
            if str(m.get("short", "")).upper() == short.upper() and (store(d).dir / "rtc.pdf").exists():
                return FileResponse(store(d).dir / "rtc.pdf", media_type="application/pdf",
                                    headers={"Cache-Control": "public, max-age=86400"})  # fmt: skip
        return _not_found(f"No response document for {short}.")

    @app.get("/favicon.ico")
    def favicon() -> Response:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" '
               'stroke="#57d39a" stroke-width="2.5"/></svg>')
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


def _shorts() -> set[str]:
    return {str(m.get("short") or "").upper() for m in available(config.DATA_ROOT).values()} - {""}


def _not_found(headline: str = "That page doesn't exist.") -> HTMLResponse:
    rules = "".join(
        f'<a href="/rule/{s}">{s}</a>' for s in sorted(_shorts()))
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Not found · Oversight</title>
<link rel="icon" href="/favicon.ico"><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#07090f;color:#e7ebf3;font:15px/1.6 Inter,system-ui,sans-serif}}
main{{max-width:460px;padding:24px;text-align:center}} h1{{font-size:22px;margin:0 0 6px}} p{{color:#8a96ad;margin:0 0 18px}}
nav{{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}} a{{color:#e7ebf3;text-decoration:none;border:1px solid #263048;
border-radius:9px;padding:8px 14px}} a:hover{{border-color:#8fb6ff}} a.home{{background:#3d7bff;border-color:#3d7bff}}</style></head>
<body><main><h1>{headline}</h1><p>Rules with a full record:</p><nav>{rules}<a class="home" href="/">All rules</a></nav></main></body></html>""",
        status_code=404, headers=NO_CACHE)


@app.exception_handler(404)
async def _404(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": getattr(exc, "detail", "Not Found")}, status_code=404)
    return _not_found()
