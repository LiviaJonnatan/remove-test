# data-processor evidence

Ticket U-04 (#4): convert the 50-record sample into canonical letters inside the data-processor container.

| File | What it shows |
| --- | --- |
| `run.log` | The container run on 50 real development-docket records: 50 letters produced, zero failed records |

## What the run does and does not show

The processor reads raw detail records and downloaded attachments from Livia’s collector and writes the letters-layer tables defined in `schema.md`.

The real sample exercises inline comment text, attachment extraction, and OCR fallback. Attachment pointers such as “See attached file(s)” are routed to attachment extraction. Formats are deduplicated by attachment ID, preferring DOCX over PDF. Where several attachments exist, a unique attachment titled `Comment` is preferred over supporting correspondence.

Record `0080` required OCR because its letter was scanned. Records `0092` and `0093` required primary-attachment selection. Their extracted text was manually checked against the source letters.

The run verifies that all 50 sample records produce letter rows inside Docker. It does not validate extraction across the full docket or real full-letter campaign attachments. This sample contains no campaign records, so it provides no EPA-labeled letters for B-cubed evaluation.

No letter text, signer names, or contact details are reproduced in these logs.

## Reproduce

From the repository root, restore the raw sample through the team’s DVC workflow and configure `SIGNER_HASH_KEY` in `.env`.

```bash
mkdir -p docs/evidence/data-processor

cd data-processor
uv sync --frozen
uv run pytest -v 2>&1 | tee ../docs/evidence/data-processor/pytest.txt
uv run ruff check . 2>&1 | tee ../docs/evidence/data-processor/ruff.txt
uv run python fetch_tokenizer.py --out ../data/models/bge/tokenizer.json
cd ..

docker compose build data-processor
docker compose run --rm --no-deps data-processor python src/main.py \
  --docket EPA-HQ-OW-2018-0149 \
  --data-root /app/data \
  --tokenizer /app/data/models/bge/tokenizer.json \
  --max-records 50 --record-ids-file "" --strict \
  2>&1 | tee docs/evidence/data-processor/run.log
```

`--no-deps` runs the processor against existing raw data without restarting the collector. `--record-ids-file ""` turns off the demo id list set in `.env`, so `--max-records` applies. `--strict` returns a nonzero exit code if any record fails.

Outputs are saved under `data/derived/letters/EPA-HQ-OW-2018-0149/`: `letters.parquet`, `records.parquet`, `signers.parquet`, and `processing_report.json`. Generated data is kept out of Git.