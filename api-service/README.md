# api-service

The FastAPI service the frontend calls, on port 8000. It reads the `rule_passages` collection in ChromaDB
and passage-stage's `passages.parquet` and `links.parquet`, and writes nothing. The trained ONNX linker
runs inside the service on each `/link` request, and the bge-small encoder embeds each `/retrieve` query.
No hosted LLM is called.

- **Endpoints** (interactive docs at http://localhost:8000/docs):
  - `GET /health`: status, passages loaded, dockets, and which linker is served (`null` without one)
  - `POST /retrieve`: text in, the rule passages it argues about out
  - `POST /link`: one comment passage in, the rule's sections ranked, with `margin` and `needs_reader`
  - `GET /stats`: request count, server errors and p50, p90 and p99 latency per route, for this instance
  - `GET /rules/{docket_id}/sections`: the rule's sections with citing counts, for the rule page
  - `GET /rules/{docket_id}/passages?section_ref=...`: the comment passages that cite a section
- **Linker:** `LINKER_MODEL_DIR` points at an exported model folder (`linker-train`'s `export` or
  `promote`). Unset, `/link` answers 503.
- **Run alone:** `docker compose up -d --build --no-deps api-service` (ChromaDB must already hold the rule)
- **Cloud Run:** `cloudrun/deploy.sh` builds the image with the rule index, the promoted linker and the
  passage files inside it, and deploys `undersigned-api`. See [docs/setup.md](../docs/setup.md#deploy-to-cloud-run).
- **Tests:** `uv run pytest && uv run ruff check .` (offline: an in-memory ChromaDB and a fake embedder)

Request and response examples: [README, api-service](../README.md#api-service),
[README, `POST /link`](../README.md#the-api-post-link) and
[`docs/evidence/api-service/`](../docs/evidence/api-service/README.md).
