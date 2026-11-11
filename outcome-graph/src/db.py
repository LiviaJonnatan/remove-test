"""Postgres access: one connection pool, the schema applied at startup, and the queries the API
needs. Plain SQL, no ORM; there are a handful of tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config

_pool: ConnectionPool | None = None


def enabled() -> bool:
    return bool(config.DATABASE_URL)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8,
                               kwargs={"row_factory": dict_row}, open=True)  # fmt: skip
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def migrate() -> None:
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with pool().connection() as c:
        c.execute(sql)


def q(sql: str, *args: Any) -> list[dict]:
    params = args[0] if len(args) == 1 and isinstance(args[0], dict) else args
    with pool().connection() as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(sql: str, *args: Any) -> dict | None:
    rows = q(sql, *args)
    return rows[0] if rows else None


def J(x: Any) -> Jsonb:
    return Jsonb(x)


# ---------------------------------------------------------------- users
def upsert_user(uid: str, email: str | None, name: str | None) -> dict:
    return one(
        """INSERT INTO users (auth_uid, email, name) VALUES (%s, %s, %s)
           ON CONFLICT (auth_uid) DO UPDATE SET email = EXCLUDED.email,
             name = COALESCE(users.name, EXCLUDED.name), last_seen = now()
           RETURNING *""", uid, email, name)  # fmt: skip


def update_profile(user_id: str, org_type: str | None, org_name: str | None, name: str | None) -> dict:
    return one("""UPDATE users SET org_type = %s, org_name = %s, name = COALESCE(%s, name)
                  WHERE id = %s RETURNING *""", org_type, org_name, name, user_id)  # fmt: skip


# ---------------------------------------------------------------- rules
def upsert_rule(r: dict) -> None:
    q("""INSERT INTO rules (docket, short, title, status, proposed_on, final_on, comments_close,
                            fr_url, bundle_version, asks, changed)
         VALUES (%(docket)s, %(short)s, %(title)s, %(status)s, %(proposed_on)s, %(final_on)s,
                 %(comments_close)s, %(fr_url)s, %(bundle_version)s, %(asks)s, %(changed)s)
         ON CONFLICT (docket) DO UPDATE SET
           short = COALESCE(EXCLUDED.short, rules.short), title = EXCLUDED.title,
           status = CASE WHEN rules.status = 'ready' AND EXCLUDED.status <> 'ready'
                         THEN rules.status ELSE EXCLUDED.status END,
           proposed_on = COALESCE(EXCLUDED.proposed_on, rules.proposed_on),
           final_on = COALESCE(EXCLUDED.final_on, rules.final_on),
           comments_close = COALESCE(EXCLUDED.comments_close, rules.comments_close),
           fr_url = COALESCE(EXCLUDED.fr_url, rules.fr_url),
           bundle_version = COALESCE(EXCLUDED.bundle_version, rules.bundle_version),
           asks = COALESCE(EXCLUDED.asks, rules.asks), changed = COALESCE(EXCLUDED.changed, rules.changed),
           updated_at = now()""",
      {k: r.get(k) for k in ("docket", "short", "title", "status", "proposed_on", "final_on",
                             "comments_close", "fr_url", "bundle_version", "asks", "changed")})  # fmt: skip


def rules() -> list[dict]:
    return q("SELECT * FROM rules ORDER BY (status = 'ready') DESC, COALESCE(final_on, proposed_on) DESC NULLS LAST")


# ---------------------------------------------------------------- usage limits
def take(who: str, kind: str, limit: int) -> bool:
    """Count one model call for `who` today; False if that would pass the limit."""
    row = one("""INSERT INTO usage (who, kind, n) VALUES (%s, %s, 1)
                 ON CONFLICT (who, day, kind) DO UPDATE SET n = usage.n + 1
                 RETURNING n""", who, kind)  # fmt: skip
    return row["n"] <= limit


def give_back(who: str, kind: str) -> None:
    """Undo one take(): the call failed, so it shouldn't count."""
    q("UPDATE usage SET n = greatest(n - 1, 0) WHERE who = %s AND kind = %s AND day = current_date", who, kind)


def used(who: str) -> dict:
    return {r["kind"]: r["n"] for r in q("SELECT kind, n FROM usage WHERE who = %s AND day = current_date", who)}


# ---------------------------------------------------------------- conversations
def new_conversation(user_id: str, docket: str, title: str) -> dict:
    return one("INSERT INTO conversations (user_id, docket, title) VALUES (%s, %s, %s) RETURNING *",
               user_id, docket, title[:120])  # fmt: skip


def conversation(cid: str, user_id: str) -> dict | None:
    return one("SELECT * FROM conversations WHERE id = %s AND user_id = %s", cid, user_id)


def conversations(user_id: str, docket: str | None = None, limit: int = 30) -> list[dict]:
    return q("""SELECT c.*, (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS n
                FROM conversations c WHERE user_id = %s AND (%s::text IS NULL OR docket = %s)
                ORDER BY updated_at DESC LIMIT %s""", user_id, docket, docket, limit)  # fmt: skip


def messages(cid: str) -> list[dict]:
    return q("SELECT id, role, content, trace, usd, created_at FROM messages WHERE conversation_id = %s ORDER BY id", cid)


def add_message(cid: str, role: str, content: str, trace: list | None = None, usd: float | None = None) -> None:
    q("INSERT INTO messages (conversation_id, role, content, trace, usd) VALUES (%s, %s, %s, %s, %s)",
      cid, role, content, J(trace or []), usd)  # fmt: skip
    q("UPDATE conversations SET updated_at = now() WHERE id = %s", cid)


def search_history(user_id: str, query: str, limit: int = 8) -> list[dict]:
    """Full-text search over this user's own past messages and drafts."""
    return q("""
        (SELECT 'message' AS kind, c.id::text AS ref, c.title, c.docket, m.role, left(m.content, 400) AS text,
                m.created_at, ts_rank(m.search, websearch_to_tsquery('english', %s)) AS rank
           FROM messages m JOIN conversations c ON c.id = m.conversation_id
          WHERE c.user_id = %s AND m.search @@ websearch_to_tsquery('english', %s))
        UNION ALL
        (SELECT 'draft', d.id::text, d.title, d.docket, NULL, left(d.body, 400), d.updated_at,
                ts_rank(d.search, websearch_to_tsquery('english', %s))
           FROM drafts d WHERE d.user_id = %s AND d.search @@ websearch_to_tsquery('english', %s))
        ORDER BY rank DESC, created_at DESC LIMIT %s""",
             query, user_id, query, query, user_id, query, limit)  # fmt: skip


# ---------------------------------------------------------------- drafts
def save_draft(user_id: str, docket: str, body: str, draft_id: str | None = None) -> dict:
    title = " ".join(body.split())[:70]
    if draft_id:
        row = one("""UPDATE drafts SET body = %s, title = %s, updated_at = now()
                     WHERE id = %s AND user_id = %s RETURNING *""", body, title, draft_id, user_id)  # fmt: skip
        if row:
            return row
    return one("INSERT INTO drafts (user_id, docket, title, body) VALUES (%s, %s, %s, %s) RETURNING *",
               user_id, docket, title, body)  # fmt: skip


def drafts(user_id: str, docket: str | None = None) -> list[dict]:
    return q("""SELECT d.id, d.docket, d.title, d.updated_at,
                       (SELECT count(*) FROM coach_runs r WHERE r.draft_id = d.id) AS runs
                FROM drafts d WHERE user_id = %s AND (%s::text IS NULL OR docket = %s)
                ORDER BY updated_at DESC LIMIT 50""", user_id, docket, docket)  # fmt: skip


def draft(draft_id: str, user_id: str) -> dict | None:
    d = one("SELECT * FROM drafts WHERE id = %s AND user_id = %s", draft_id, user_id)
    if d:
        d["runs"] = q("SELECT id, result, tools, usd, ms, created_at FROM coach_runs WHERE draft_id = %s ORDER BY id DESC LIMIT 5", draft_id)
    return d


def add_coach_run(draft_id: str, result: dict, tools: int, usd: float | None, ms: int | None) -> None:
    q("INSERT INTO coach_runs (draft_id, result, tools, usd, ms) VALUES (%s, %s, %s, %s, %s)",
      draft_id, J(json.loads(json.dumps(result, default=str))), tools, usd, ms)  # fmt: skip


def delete_owned(table: str, row_id: str, user_id: str) -> bool:
    """Delete one of the user's own conversations or drafts. Messages and coach runs go with it (ON DELETE CASCADE)."""
    assert table in ("conversations", "drafts")
    return bool(q(f"DELETE FROM {table} WHERE id = %s AND user_id = %s RETURNING id", row_id, user_id))


# ---------------------------------------------------------------- follows
def follow(user_id: str, docket: str, on: bool) -> None:
    if on:
        q("INSERT INTO rule_follows (user_id, docket) VALUES (%s, %s) ON CONFLICT DO NOTHING", user_id, docket)
    else:
        q("DELETE FROM rule_follows WHERE user_id = %s AND docket = %s", user_id, docket)


def follows(user_id: str) -> list[str]:
    return [r["docket"] for r in q("SELECT docket FROM rule_follows WHERE user_id = %s", user_id)]
