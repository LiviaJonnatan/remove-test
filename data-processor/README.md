# data-processor

Turns raw comment records and their attachments into one letter per record: inline text, DOCX and PDF
text, and OCR only when a page has no text. Signer names are hashed with `SIGNER_HASH_KEY`, and tokens
are counted with the bge-small tokenizer that is baked into the image.

- **Input:** `data/raw/<docket>/` from data-collector.
- **Output:** `data/derived/letters/<docket>/`: `letters.parquet`, `records.parquet`, `signers.parquet`
  and `processing_report.json`.
- **Run alone:** `docker compose run --rm --no-deps data-processor` (after data-collector has run)
- **Tests:** `uv run pytest && uv run ruff check .` (offline)

Full description and the 50-record validation run: [README, data-processor](../README.md#data-processor)
and [`docs/evidence/data-processor/`](../docs/evidence/data-processor/README.md).
