# Oversight

Oversight (code in `outcome-graph/`) is the outcome record for EPA drinking water rules, as a graph you can explore, question, and check a draft comment against. For each rule: what commenters asked for, EPA's verdict in its own words, who argued each side, and what changed between the proposed and final rule.

| Rule | Docket | Final | Asks | Changed the rule | Comment excerpts |
|---|---|---|---|---|---|
| Lead and Copper Rule Revisions (LCRR) | EPA-HQ-OW-2017-0300 | Jan 2021 | 1,362 | 290 | none: EPA summarized comments without naming commenters |
| PFAS Drinking Water Standard | EPA-HQ-OW-2022-0114 | Apr 2024 | 526 | 107 | 5,433, 3,531 tied to an ask |
| Lead and Copper Rule Improvements (LCRI) | EPA-HQ-OW-2022-0801 | Oct 2024 | 832 | 139 | 7,889, 5,113 tied to an ask |

Every one of the 2,720 EPA quotes was checked word for word against EPA's response document.

## Run it

The whole application, locally. Each piece stands in for its production counterpart; see
[docs/oversight-system-design.md](../docs/oversight-system-design.md) for the design.

| Local | Production |
|---|---|
| Postgres 16 in compose (`db`) | Cloud SQL for PostgreSQL |
| Firebase Auth emulator (`auth`) | Firebase Auth / Identity Platform, Google sign-in |
| FastAPI + the page (`api`) | Cloud Run service |
| Rule watcher (`watcher`, daily loop) | Cloud Run Job on a Cloud Scheduler trigger |
| Claude on Vertex AI with your gcloud login | Claude on Vertex AI with the service account. No API key anywhere |

```bash
cd outcome-graph
uv sync
(cd web && npm ci && npx vite build)
gcloud auth application-default login     # once; the model is reached with Google credentials
docker compose --profile app up -d --build
# open http://127.0.0.1:8080 ; auth emulator UI at http://127.0.0.1:4000
```

Or run the API on the host while developing, with only the database and auth emulator in compose:

```bash
docker compose up -d db auth
set -a; . ./.env.local; set +a
uv run uvicorn server:app --app-dir src --port 8077
uv run python src/jobs/watch_rules.py      # one watcher pass
```

`.env.local` holds no secrets: the local database password and a `demo-` Firebase project that only
the emulator serves. `LLM_BACKEND=vertex` is the real model path. Until the project's Vertex quota
for Claude is raised, `LLM_BACKEND=cli` uses the laptop's Claude Code login instead, with the same
tools and the same events on the page. `AGENT=0` turns Iris and the coach off, as on the current
hosted copy. Without `DATABASE_URL` the page runs signed-out only.

For front-end work, run `npx vite` in `web/` (port 5177, proxies `/api` to 8077).

## What it shows

| On the page | What it is |
|---|---|
| Ring | EPA's response topics in document order, grouped by chapter. Each dot is one ask, colored by EPA's verdict; a ringed dot changed the final rule |
| Legend | Filter by verdict, "changed the final rule", or stakeholder group |
| Iris | The agent with a face: an orb on the graph you can type or talk to. Each tool call lights up what it read, `show_on_graph` points at the nodes the answer is about, cited nodes become clickable chips, and answers can be read aloud. Signed in, conversations are saved and Iris knows your organization and earlier questions |
| Check a comment | The comment coach, below |
| Inspect | Topic: EPA's summary and every ask. Ask: EPA's sentence, effect on the final rule, who argued for and against. Commenter: their record. Section: proposal to final as word diffs |
| Scoreboard | Who got their way by stakeholder group, top and bottom commenters |

## Comment coach

Paste a draft comment on one of the rules. The coach is an agent: it picks its own lookups and the page shows each one as it happens.

| Tool | What it gives the agent |
|---|---|
| `find_similar_asks` | Past asks closest to a point, from every rule, with EPA's verdict, sentence and rule change |
| `search_rule_text` | Paragraphs of the final regulatory text of the rule being commented on |
| `get_node` | Full detail on one ask or topic, to compare an adopted and a declined version |
| `search_comments` | Comments EPA quoted, to see what a successful commenter argued |

It returns one card per point in the draft: how EPA answered similar asks, what the final rule already says, EPA's own sentence, two or three edits, and suggested wording.

What code checks, not the model:

| Check | What happens on failure |
|---|---|
| Every cited ask must have come back from a tool call in this run | Dropped |
| A "what the final rule says" quote must appear word for word in the final rule | Dropped, and an "already in the rule" outlook falls back to mixed |
| Verdict counts on each card | Computed from the graph |
| EPA's sentence on each card | Taken from the record, not written by the model |
| Reply is not valid JSON | Error shown, raw reply saved |

Typical run on the example drafts: 7 to 11 lookups, about 20 seconds, about $0.10. On the PFAS example it found that the final rule already gives every system until April 26, 2029 (five years), which is what the draft asked for.

## Backtest: does the record predict EPA's answer?

`eval/backtest.py` hides EPA's verdict on every ask and predicts it as moved (adopted or partly), declined, or no change. Four predictors: always "declined"; a vote of the 10 most similar asks; Sonnet given only the ask, its topic and who argued it; and Sonnet plus the 10 most similar asks with EPA's verdict and sentence. Asks from the same topic are never used as evidence.

| Test | Asks | Always declined | Similar-ask vote | Sonnet alone | Sonnet + record | Record minus Sonnet alone (95% interval, by topic) |
|---|---|---|---|---|---|---|
| LCRI, record = LCRI's other topics | 832 | 0.531 | 0.582 | 0.689 | **0.804** | **+11.5 pts** (+8.9 to +14.4) |
| LCRI, record = LCRR only (earlier rule) | 832 | 0.531 | 0.558 | 0.689 | 0.666 | −2.2 pts (−4.9 to +0.6) |
| PFAS, record = LCRR + LCRI | 526 | 0.487 | 0.544 | 0.656 | 0.653 | −0.2 pts (−4.0 to +4.1) |

Accuracy over three classes. Moved-vs-rest AUC for the first row: 0.753 alone, 0.904 with the record. Removing asks with a near-duplicate in another topic (similarity ≥ 0.85, leaving 763) leaves the first row at 0.794 vs 0.684.

What this says:

- Within one rule the record helps a lot. EPA's answers on other topics of the same rule tell you how it treated this one.
- Across rules it adds nothing measurable on top of Sonnet's own judgment. The similar-ask vote beats always-declined every time, so the record carries signal, but Sonnet already gets there.
- Caveat: both 2024 rules are before Sonnet's training cutoff, so "Sonnet alone" may partly remember the outcomes. A clean test needs a rule finalized after the cutoff.
- So the coach's value is grounding (EPA's actual reasoning, the actual rule text, real comments), not better odds than the model's guess.

Cost: $5.76 for the first row, $5.91 and $3.72 for the others.

```bash
uv run python eval/backtest.py --docket EPA-HQ-OW-2022-0801
uv run python eval/backtest.py --docket EPA-HQ-OW-2022-0801 --train EPA-HQ-OW-2017-0300
uv run python eval/backtest.py --docket EPA-HQ-OW-2022-0114 --train EPA-HQ-OW-2017-0300,EPA-HQ-OW-2022-0801
```

## Adding a rule

| Step | Command | Output |
|---|---|---|
| 0. Response document | Save EPA's response-to-comments PDF from regulations.gov as `data/raw/<docket>/rtc/rtc.pdf` (the site blocks scripted downloads; save it from a browser) | |
| 1. Rule text | `collect()` in `rule-passages` writes the Federal Register documents to `data/raw/federal_register/<docket>/` | proposed and final rule text |
| 2. Parse | `DOCKET_IDS=<docket> DATA_DIR=$PWD/data uv run --project response-index python response-index/src/main.py` | `responses/<docket>/` codes, entries, rule diff |
| 3. Asks and verdicts | `uv run python src/extract.py --docket <docket> --budget 25` | `outcomes/<docket>/raw/` |
| 4. Excerpt to ask | `uv run python src/assign.py --docket <docket> --budget 22` (skip if no excerpts) | `outcomes/<docket>/assign/` |
| 5. Graph | add the rule's name and chapters to `DOCKETS` in `src/build.py`, then `uv run python src/build.py --docket <docket>` | `graph.json`, `details.json` |

The page and the coach pick up any rule with a `graph.json`. Steps 3 and 4 cache every model call, so a rerun only pays for what is missing.

The parser reads three layouts: LCRI ("EPA Response to Comment Code 5.9.2" per topic), PFAS (numbered headings, then "Individual Public Comments"), and LCRR (numbered sections of summarized comments, each followed by "Agency Response", no named commenters). For LCRR, quotes are checked against the agency's parts only, so a commenter's words never pass as EPA's verdict. The rule diff takes the longest final rule that prints regulatory text, so later delay notices and corrections are skipped.

## Cost

| Rule | Extraction | Excerpt matching |
|---|---|---|
| LCRI | $8.77 | $18.00 |
| PFAS | $5.55 | $15.65 |
| LCRR | $12.58 | none |

All Opus via `claude -p`.

## How sure each part is

| Part | How it was made | Check |
|---|---|---|
| Topics, excerpts, EPA's replies, who said it | Parsed from EPA's response document by response-index | LCRI: same data the matcher is scored on. PFAS: 5,433 entries of about 5,580 "(Doc. #" markers |
| Rule changes | Paragraph diff of proposed vs final text (response-index) | Deterministic |
| Asks and verdicts | Model reads each topic's text; every quote verified by code | LCRI: 15 of 16 random asks right (the miss was EPA agreeing with a point that needed no rule change, labeled adopted). LCRR and PFAS: 16 of 16 (8 each) matched EPA's sentence |
| Excerpt to ask, for or against | Model reads 40 excerpts next to the topic's asks | Hand check of 8 in the pilot: 8 right. Text similarity was tried first and dropped |
| Stakeholder group | Regex on the commenter name | Rough. Most names read as individuals |

"Got their way" means EPA adopted what the commenter asked for or declined what they argued against. Partly counts as half in the percentages. Explained and already-in-the-rule count as no change.

## Use the graph from your own Claude

```bash
DOCKET=EPA-HQ-OW-2022-0114 claude mcp add outcome -- uv run --project outcome-graph python outcome-graph/src/mcp_server.py
```

Tools: `overview`, `search`, `search_comments`, `get_node`, `neighbors`, `org_record`, `compare_stakeholders`, `find_similar_asks`, `search_rule_text`.

## Hosted copy

`./deploy.sh` builds the page and packs every built rule into a Cloud Run service in the team's GCP project, with the Ask tab and coach off (no API key there). Rerun it to update the same link.

## Tests

```bash
uv run pytest -q
```
