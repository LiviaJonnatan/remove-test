# data-collector

Pulls Regulations.gov dockets into `data/raw/<docket>/`. It is the only container that talks to the
Regulations.gov API; every later stage reads the files it writes.

- **Input** (`.env`): `API_DATA_GOV_KEY`, `DOCKET_IDS`, and `RECORD_IDS_FILE` or `MAX_RECORDS`. The
  `.env.example` default fetches the fixed 40-record demo list in `samples/ms2_ids.txt`.
- **Output:** `data/raw/<docket>/`: `details/<id>.json` (each record as the API returned it),
  `attachments/`, `attachments_manifest.jsonl`, `details_index.jsonl` and `manifest.json`. The schema is in
  [`schema.md`](../schema.md).
- **Run alone:** `docker compose run --rm data-collector`
- **Tests:** `uv run pytest && uv run ruff check .` (offline)

Full description, modes and known limits: [README, data-collector](../README.md#data-collector).
Run logs: [`docs/evidence/data-collector/`](../docs/evidence/data-collector/).
