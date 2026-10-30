# passage-stage

Splits each distinct letter into passages of about 120 words and reads the rule sections a passage
cites (for example `§ 141.84(b)(2)` or `40 CFR 141.85`). A campaign's shared text is read once. The
letters' own citations are the answer key that retrieval is scored against.

- **Input:** letters and campaign assignments from data-processor and campaign-builder, and the rule text
  rule-passages collected (it uses rule-passages' own chunking, so section names match).
- **Output:** `data/derived/passages/<docket>/`: `passages.parquet` (with `text_masked`, the text with
  citations hidden), `links.parquet` (one row per passage and cited section) and `summary.json`.
- **Run alone:** `docker compose run --rm passage-stage` (after campaign-builder and rule-passages)
- **Tests:** `uv run pytest && uv run ruff check .` (offline)

On the demo sample: 816 passages and 208 links to 15 sections of the rule. Full description:
[README, passage-stage](../README.md#passage-stage).
