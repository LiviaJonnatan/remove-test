# campaign-builder

Groups copies of the same form letter into campaigns, so later stages read a campaign's shared text once.
The default grouper is containment of five-word phrases (`GROUPING_METHOD=containment`); exact match and
MinHash are the alternatives, and B-cubed F1 scores a grouping against EPA's.

- **Input:** `data/derived/letters/<docket>/letters.parquet` from data-processor.
- **Output:** `data/derived/campaigns/<docket>/`: `assignments.parquet`, `campaigns.parquet`,
  `representatives.parquet` and `summary.json`.
- **Run alone:** `docker compose run --rm --no-deps campaign-builder` (after data-processor has run)
- **Tests:** `uv run pytest && uv run ruff check .` (offline)

On the 40-record demo sample, containment groups 18 of the 20 campaign letters, one group per campaign
(B-cubed F1 0.91). Full description: [README, campaign-builder](../README.md#campaign-builder) and
[`docs/evidence/campaign-builder/containment.md`](../docs/evidence/campaign-builder/containment.md).
