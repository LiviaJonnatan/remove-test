# argument-graph

Turns the comment passages that cite a section of the rule into the table an agency response
writer needs: every claim with a verbatim quote, what the commenter asks for, the kind of evidence
offered, the claims of a section grouped into issues, each issue counted by distinct letters and
campaigns, and an `evidence_type` flag on the issues whose claims carry data, a legal argument or a
concrete alternative. Two model steps (extract, judge); every other step is script, and everything
the script could not settle goes to a review queue. The LCRI pilot
([pilot.md](../docs/evidence/argument-graph/pilot.md)) found that the judge does not beat cosine
clustering on point recall and that the flag recalls fewer answered points than flagging every
issue, so the flag is a column, not a significance signal.

- **Input:** `letters.parquet` (data-processor), `assignments.parquet` and `campaigns.parquet`
  (campaign-builder), `passages.parquet` and `links.parquet` (passage-stage), and the rule text
  rule-passages collected (for the section heading and the first 150 words as prompt context).
- **Output:** `data/derived/graph/<docket>/`: `claims.parquet`, `pairs.parquet`, `issues.parquet`,
  `claim_issues.parquet`, `review.parquet`, `graph.json`, `summary.json`, plus `ledger.jsonl`,
  `prompts/<tag>.txt` and `raw/<tag>.json` per model call. Columns in
  [schema.md §3c](../schema.md#3c-graph-layer-datagraphdocket-argument-graph).
- **Run alone:** `docker compose run --rm argument-graph` (after passage-stage). On a laptop with
  Claude Code: `GRAPH_BACKEND=cli DATA_DIR=../data PYTHONPATH=../rule-passages/src uv run python
  src/main.py all`. With no key and no `claude` on PATH it prints a skip message and exits 0.
- **Tests:** `uv run pytest && uv run ruff check .` (46 tests, offline; recorded answers in
  `tests/fixtures/`, a lookup-table embedder, no network).

Full description: [README, Argument graph](../README.md#argument-graph).

## Backends

| `GRAPH_BACKEND` | Uses | When |
|---|---|---|
| `cli` | `claude -p --model fable --output-format json`, the laptop's Claude Code login | pilots; cost comes from the CLI's own `total_cost_usd` |
| `sdk` | the Anthropic SDK, `claude-fable-5-1`, JSON-schema output, section context cached before the passages | the container; needs `ANTHROPIC_API_KEY`; cost from `prices.json` |
| `fake` | `tests/fixtures/<tag>.json` | tests |

Default: `sdk` if the key is set, else `cli` if `claude` is on PATH, else skip. Every call is
cached under `raw/<tag>.json` together with the prompt's sha1: a rerun (or `python src/main.py
pairs`) serves the same prompt from the file and makes no call, and a different prompt under the
same tag is a miss. A cached answer that no longer validates against the schema is a miss too.

## Harness rules

| Check | On failure |
|---|---|
| Output validates against `schemas/*.json` | one re-ask with the validator's message, then `llm_failed` review rows for the batch and a non-zero exit |
| Every passage or pair id returned exactly once | one re-ask listing the missing and duplicated ids; a pair still missing defaults to `different` (`missing_from_output`) |
| Quote is a substring of the passage after normalising quotes, dashes, spaces and ligatures (`quotes.py`) | fall back to the whole letter; one re-ask for the failing claims of the batch; still failing, the claim is dropped (`quote_failed`). Quotes are never shortened by script |
| Quote is not a fragment (under 8 words, a heading, a citation list) | claim kept with `needs_review` (`quote_fragment`) |
| Model's `section_ref` is one of the passage's cited sections | the citation wins; `section_disagrees` or `no_section` logged |
| Linker top-5 contains the cited section (`GRAPH_LINKER_DIR` or `GRAPH_LINK_URL`) | `linker_disagrees`; otherwise `linker_rank` is filled |
| Union-find component also holds a pair judged `different` | `contested_merge` on the issue |
| Component over 40% of a section's claims (sections with 5 or more) | `giant_issue`, kept |
| Spend above `GRAPH_MAX_USD` (default 40) | the call that crosses the cap is kept on disk, every later live call is refused before anything is paid, cached calls still serve; main.py writes partial outputs and exits 2 |

## Counting and significance

`n_letters` counts distinct letters among an issue's claims; `n_campaigns` distinct campaigns;
`n_letters_incl_copies` adds each campaign's members that are not already among the issue's
letters, so a form letter sent 5,000 times counts once in the first and 5,000 times in the third,
and a campaign reaching an issue through two of its letters is not counted twice. `significant`
is a rule, not a model: any member claim with `data`, `legal` or `alternative` in `evidence_type`,
listed in `significance_from`. On the LCRI pilot the rule recalled 9.0% of the points the agency
answered explicitly against 22.9% for flagging every issue, so it is kept as a column for the
reader pack's audit and not used as a signal.

## Eval (`eval/`)

| Script | Does |
|---|---|
| `parse_preamble.py` | cuts the final rule's 35 "Summary of Public Comments and the EPA's Response" blocks into the points the agency summarised, deterministically; `block_sections.csv` maps the 9 blocks that cite no section |
| `match.py` | bge-small top-3 candidate issues per point (every section's issues for a catch-all point), 10 points per model call, each judged on its own; `--reuse` keeps the previous verdicts for points whose candidates are unchanged; writes `matches.parquet`, `points_scored.parquet` and `graph_eval.json` |
| `baselines.py` | B0 one issue per cited (passage, section) with no model, B1 cosine clustering at matched issue count, B2 the 12 Oct positions |
| `score.py` | block and point recall (top-3 and top-2 candidates, catch-all apart), 95% percentile bootstrap over blocks with paired differences against the pipeline, compression, significance recall against flag-all and two top-k baselines, linker agreement (frozen test number read from `docs/evidence/linker-train/in-pre/metrics.json`), review load as rows over claims and as distinct claims over claims, cost |
| `pack/` | seeded reader sheets for two readers (`make_pack.py`), codebook, agreement and rates (`score_readers.py`) |
| `make_evidence.py` | copies a run's log, summary and ledger to `docs/evidence/argument-graph/` with one claim followed end to end |

## Where it fails

- Issues are per section; the same ask about § 141.84 and § 141.86 appears twice.
- The preamble omits comments the EPA judged insignificant, so point recall is a recall label only.
- Significance rests on an extractor field: a data argument with no number is missed, a cost table
  can be tagged `data`. The reader pack's 30-item audit measures this. On the pilot the flag was
  cut as a signal.
- Uncited passages are out by default; `GRAPH_INCLUDE_UNCITED=1` brings in the linker's 65.5% top-1.
- No organisation field exists in the three EPA dockets; "who is behind it" is campaign and state.
- Fable's list price is 5x Sonnet per token; the ledger shows the spend and the pilot decides the
  effort level.
- Point boundaries inside paragraphs that carry both summary and response are heuristic: the cut
  is at the first sentence that opens as the agency speaking, and an agency sentence without such
  an opener survives as a point. The reader pack's 40-item boundary check measures the rate.
