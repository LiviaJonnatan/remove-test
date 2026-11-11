-- Oversight's relational state. Postgres locally (docker compose) and Cloud SQL in production.
-- The knowledge graph itself is not here: each built rule is an immutable bundle (graph, details,
-- excerpts, vectors) loaded into memory. This database holds what changes: users, their history,
-- and which rules exist and how far along they are. Every statement is idempotent; the API runs
-- this file at startup.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- One row per signed-in person. auth_uid is the Firebase / Identity Platform uid.
CREATE TABLE IF NOT EXISTS users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_uid    text UNIQUE NOT NULL,
    email       text,
    name        text,
    org_type    text,            -- utility, advocacy, trade, state, law_firm, press, academic, other
    org_name    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);

-- Every rulemaking the watcher knows about, built or not.
--   ready             bundle built and served
--   awaiting_rtc      final rule published; the agency's response-to-comments document is not in yet
--   processing        pipeline running
--   open_for_comment  proposed rule with an open comment period
--   proposed          proposed rule, comment period closed, no final rule yet
--   failed            pipeline error, see error
CREATE TABLE IF NOT EXISTS rules (
    docket          text PRIMARY KEY,
    short           text,
    title           text NOT NULL,
    status          text NOT NULL,
    proposed_on     date,
    final_on        date,
    comments_close  date,
    fr_url          text,
    bundle_version  text,
    asks            int,
    changed         int,
    discovered_at   timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    error           text
);

CREATE TABLE IF NOT EXISTS rule_follows (
    user_id     uuid REFERENCES users(id) ON DELETE CASCADE,
    docket      text REFERENCES rules(docket) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, docket)
);

-- Conversations with Iris. Signed-in only; anonymous chats live in the browser tab and are gone
-- when it closes.
CREATE TABLE IF NOT EXISTS conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    docket      text NOT NULL,
    title       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_user ON conversations (user_id, updated_at DESC);

-- content: the text shown; trace: tool calls and the node ids they touched, so a reopened chat can
-- light the graph up again.
CREATE TABLE IF NOT EXISTS messages (
    id               bigserial PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant')),
    content          text NOT NULL,
    trace            jsonb NOT NULL DEFAULT '[]',
    usd              numeric(8, 4),
    created_at       timestamptz NOT NULL DEFAULT now(),
    search           tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages (conversation_id, id);
CREATE INDEX IF NOT EXISTS messages_search ON messages USING gin (search);

-- Draft comments and every coach run on them.
CREATE TABLE IF NOT EXISTS drafts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    docket      text NOT NULL,
    title       text NOT NULL,
    body        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    search      tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || body)) STORED
);
CREATE INDEX IF NOT EXISTS drafts_user ON drafts (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS drafts_search ON drafts USING gin (search);

CREATE TABLE IF NOT EXISTS coach_runs (
    id          bigserial PRIMARY KEY,
    draft_id    uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    result      jsonb NOT NULL,
    tools       int,
    usd         numeric(8, 4),
    ms          int,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Daily limits on model calls, for signed-in users and for anonymous visitors (hashed address).
CREATE TABLE IF NOT EXISTS usage (
    who     text NOT NULL,
    day     date NOT NULL DEFAULT current_date,
    kind    text NOT NULL,
    n       int NOT NULL DEFAULT 0,
    PRIMARY KEY (who, day, kind)
);

-- One row per watcher run.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id           bigserial PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    seen         int,
    new          int,
    log          text
);

-- Following an organization (by its cross-rule key, store.org_key), alongside rule_follows.
CREATE TABLE IF NOT EXISTS org_follows (
    user_id     uuid REFERENCES users(id) ON DELETE CASCADE,
    org_key     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, org_key)
);

-- The in-app inbox. The watcher writes these; dedupe_key keeps one per event per person.
CREATE TABLE IF NOT EXISTS notifications (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        text NOT NULL,
    title       text NOT NULL,
    body        text,
    url         text,
    dedupe_key  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    read_at     timestamptz,
    emailed_at  timestamptz,
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications (user_id, created_at DESC);

-- People checking the extraction by hand: is this verdict right, is the ask stated faithfully.
CREATE TABLE IF NOT EXISTS reviews (
    id              bigserial PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    docket          text NOT NULL,
    ask_id          text NOT NULL,
    verdict_ok      boolean NOT NULL,
    ask_ok          boolean NOT NULL,
    right_verdict   text,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, docket, ask_id)
);

-- "This looks wrong" from any page.
CREATE TABLE IF NOT EXISTS reports (
    id          bigserial PRIMARY KEY,
    who         text NOT NULL,
    docket      text,
    node_id     text,
    problem     text NOT NULL,
    note        text,
    url         text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

-- First-party usage events: page views and key actions, no third-party tracker. `anon` is the
-- browser's random id, never an address.
CREATE TABLE IF NOT EXISTS events (
    id       bigserial PRIMARY KEY,
    at       timestamptz NOT NULL DEFAULT now(),
    anon     text,
    user_id  uuid,
    name     text NOT NULL,
    path     text,
    props    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_at ON events (at DESC);
