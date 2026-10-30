# api-service

The FastAPI service the frontend calls, on port 8000. It reads the `rule_passages` collection in ChromaDB
and passage-stage's `passages.parquet` and `links.parquet`, and writes nothing. No model is called when a
request comes in.

- **Endpoints** (interactive docs at http://localhost:8000/docs):
  - `GET /health`
  - `POST /retrieve`: text in, the rule passages it argues about out
  - `GET /rules/{docket_id}/sections`: the rule's sections with citing counts, for the rule page
  - `GET /rules/{docket_id}/passages?section_ref=...`: the comment passages that cite a section
- **Run alone:** `docker compose up -d --build --no-deps api-service` (ChromaDB must already hold the rule)
- **Tests:** `uv run pytest && uv run ruff check .` (offline: an in-memory ChromaDB and a fake embedder)

Request and response examples: [README, api-service](../README.md#api-service) and
[`docs/evidence/api-service/`](../docs/evidence/api-service/README.md).
