# rule-passages

The RAG pipeline for the rule's own text. It collects the rule from the Federal Register API (no key),
cuts it into chunks of about 200 words that never cross a section, embeds them with
`BAAI/bge-small-en-v1.5` (ONNX, CPU) and loads them into the ChromaDB collection `rule_passages`.
Retrieval (BM25, embeddings, or both merged by rank) lives in `src/rule_passages/` and is shared with
api-service.

- **Input:** `DOCKET_IDS` / `RULE_DOCKETS` from `.env`; ChromaDB at `CHROMA_HOST:CHROMA_PORT`.
- **Output:** `data/raw/federal_register/` (the rule documents) and the `rule_passages` collection,
  persisted in `docker-volumes/chromadb`.
- **Run alone:** `docker compose up -d chromadb && docker compose run --rm rule-passages`
- **Query it:** `docker compose run --rm rule-passages python src/main.py query --text "<a sentence from a letter>"`
- **Tests:** `uv run pytest && uv run ruff check .` (offline, no model download)

On the demo rule (88 FR 84878): 1,108 chunks. Full description: [README, rule-passages](../README.md#rule-passages)
and [`docs/evidence/rule-passages/`](../docs/evidence/rule-passages/README.md).
