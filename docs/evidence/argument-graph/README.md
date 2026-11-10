# Evidence: argument-graph (LCRI pilot, 364 cited passages)

Date 2026-10-30, laptop, commit `2fb86d5`, backend `cli`, model
`['claude-fable-5-1']`. Inputs are the full LCRI docket after dvc pull and the data-processor, campaign-builder and passage-stage containers (1,553 letters, 5,409 passages, 364 cited passages from 42 letters); rule context from the proposal text on disk (rule_context: files). Eval numbers are in pilot.md.

| File | What it shows |
|---|---|
| `run.log` | The stage's own log lines for this run |
| `summary.json` | Counts, cost by step, token totals, prompt hash, input checksums |
| `ledger-excerpt.jsonl` | One row per model call: tag, tokens, seconds, USD as reported |
| `one-claim-end-to-end.md` | One passage through claims, pair verdicts and its issue, real ids |
| `results.md` | Eval tables from eval/score.py |

Run: 364 passages in, 364 extracted, 859 claims
(859/859 quotes verified first pass,
0 dropped), 605 issues (116 with more than one
claim), 214 flagged significant, 184 review rows.
Calls {'extract': 40, 'judge': 45},
USD 29.1882 (0 cache-read tokens, 530554
cache-write, 371509 output), wall clock 156.3 s.

## Reproduce

```bash
cd argument-graph
GRAPH_BACKEND=cli GRAPH_MODEL=fable DATA_DIR=../data DOCKET_IDS=EPA-HQ-OW-2022-0801 \
  PYTHONPATH=../rule-passages/src uv run python src/main.py all
python eval/make_evidence.py --graph-dir ../data/derived/graph/EPA-HQ-OW-2022-0801 --log run.log
```

## What this does not show

The prompts and raw answers (`prompts/`, `raw/`) hold letter text and stay in `data/derived/`,
which is not in git. Eval numbers appear only once `eval/match.py` and `eval/score.py` have run.
