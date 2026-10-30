# Evidence

Logs and small sample artifacts showing the pipeline runs end-to-end (Milestone 2 deliverable). The data itself is DVC-tracked, not committed here; these are excerpts.

## Pipeline

### On a Google Cloud VM (current code)
One `docker compose up --build -d` from a fresh clone on a GCP VM (`undersigned-ms2`) on 19 Oct 2026 (the log's timestamps are UTC, 20 Oct), following [`docs/setup.md`](../setup.md) with only a data.gov key set. Commit `f0a5f10`, so this run includes containment grouping and passage-stage. Same 40-record sample: 40 records, 11 attachments, 40 letters with 0 failed, 18 letters in 2 containment groups and 22 individual, 816 comment passages with 208 links to 15 sections of the rule, and 1,108 rule passages embedded and served by the API. The build took about four minutes and the containers about twelve more, about sixteen in all, most of the twelve embedding the rule on the VM's CPU.

| File | What it shows |
| --- | --- |
| `running-instances-gcp-console.png` | Compute Engine instance list with `undersigned-ms2` running |
| `running-instances-gcp-ps.png` | `docker compose ps -a` and `curl localhost:8000/health` inside the VM, hostname in the prompt |
| `pipeline-run-vm.log` | Container events and each stage's log from the VM run |
| `pipeline-ps-vm.txt` | `docker compose ps -a` on the VM: five batch containers `Exited (0)` (passage-stage is the fifth), chromadb / api-service / frontend `Up` |
| `api-retrieve-vm.png` | `POST /retrieve` executed from a laptop browser through an SSH tunnel to the VM, with the rule passages returned. From the earlier 14 Oct VM run (879 rule passages), not the 19 Oct rerun; the request and the shape of the response have not changed since |
| `ui-calling-backend.png` | The rule page at `localhost:3000` showing the sections of 88 FR 84878 with one section open, and the browser's Network tab with the page's call to `/api/rules/EPA-HQ-OW-2022-0801/sections` answered 200. Taken on a laptop run of the same sample; the request as nginx and the API logged it is in [`frontend/`](frontend/README.md) |
| `rule-page-section-open.png` | The same page on 18 Oct after passage-stage linking: § 141.84 open, 40 citing passages from 5 letters, with the first quotes. Taken on a laptop run with #74 and #83 merged in. [`docs/wireframe.png`](../wireframe.png) is drawn from this run. `ui-calling-backend.png` above predates linking, so its citing counts show "—" |

### Earlier run on a laptop (13 Oct)
One `docker compose up --build -d` from a fresh clone, captured on 13 Oct 2026 on a laptop, with `.env.example` copied to `.env` and an API key added. Nothing else was set. The run is the fixed 40-record sample of docket EPA-HQ-OW-2022-0801 (`data-collector/samples/ms2_ids.txt`) and takes about a minute.

Sample in, artifact out: 40 comment ids go in. Out come 40 raw records with 11 attachments, `letters.parquet` with 40 letters and 0 failed records, `assignments.parquet` with one exact-match group of 2 letters, and 879 chunks of the proposed rule (88 FR 84878) in ChromaDB, which the API serves.

| File | What it shows |
| --- | --- |
| `pipeline-run.log` | Container events in order, then each stage's own log: collector (40 records, index stage skipped), processor (40 letters, 0 failed), campaign-builder (2 letters in 1 group), rule-passages (879 chunks embedded), api-service (879 passages loaded) |
| `pipeline-ps.txt` | `docker compose ps -a`: four batch containers `Exited (0)`, chromadb / api-service / frontend `Up` |
| `pipeline-curl.txt` | `localhost:8000/health` returns `"status":"ok"` with 879 passages for the docket, `localhost:3000` returns 200 from nginx, the ChromaDB heartbeat answers, and the derived files are on disk |

Known limits of the 13 Oct laptop run: exact match groups 2 of the 20 campaign letters in the sample, because those campaigns are personalized (ticket #5). The rule-page screenshot's citing counts are "—": it predates the API reading passage-stage's links. The live API now fills those counts for this sample (see [`api-service/`](api-service/README.md)); preamble sections stay 0 because the linker only resolves regulatory citations. The grouper line in the laptop log (`2 in 1 exact-match groups`) predates containment grouping (U-05). The VM log above was rerun after it and shows `18 in 2 containment groups`, one group per campaign; see [`campaign-builder/containment.md`](campaign-builder/containment.md). The laptop log and `pipeline-curl.txt` also predate the rule-passages fixes in #67 and #83, so they show 879 rule passages where the current code gives 1,108.

## data-collector

Smoke run on EPA-HQ-OW-2018-0149 with `MAX_RECORDS=50` and one API key (indexes the first full page of 250).

| File | What it shows |
| --- | --- |
| `data-collector/collector-smoke.log` | Log of the run: index, detail calls, attachment downloads, final summary |
| `data-collector/collector-manifest.json` | Summary written by the collector: 50 comments indexed, 50 detail records, 18 attachments, 0 failed |
| `data-collector/sample/comments_index.head.jsonl` | First 5 lines of the index (output of stage 1, the list endpoint) |
| `data-collector/sample/details_index.head.jsonl` | First 5 lines of the per-comment summary (stage 2): `receive_date`, `posted_date`, whether a body is present, attachment count |
| `data-collector/sample/attachments_manifest.head.jsonl` | First 5 lines of the attachment manifest (stage 3): which files were downloaded and where |
| `data-collector/sample/EPA-HQ-OW-2018-0149-0084.json` | One complete detail record as returned by `GET /v4/comments/{id}?include=attachments`: the input to stage 3 and the source of the comment text the processor reads |

Input → output: the docket ID `EPA-HQ-OW-2018-0149` goes in; `data/raw/EPA-HQ-OW-2018-0149/` comes out with `comments_index.jsonl`, `details/<id>.json`, `details_index.jsonl`, `attachments/<id>/<file>`, `attachments_manifest.jsonl` and `manifest.json`. Re-running the collector skips everything already on disk (`api_calls_this_run: 0` in the manifest).

Sample generated by `scripts/make_evidence_sample.py`; names redacted per CONTRIBUTING.md.

## CREDO Action campaign, traced end to end

[`credo-trace.md`](credo-trace.md): the raw record, its cover email and 1,717-page signer file, the checks behind MS1's Figure A, and the rule sections it links to.

## rule-passages

Cold and warm runs, the section outline, and query-to-passage examples for real comments are in [`rule-passages/`](rule-passages/README.md).

## api-service

The container's startup log, a curl session (health, retrieval, a merged list, `k=50`, an unknown docket, a
rejected request) and the API's answers for comment 0390 are in [`api-service/`](api-service/README.md).
With both retrievers the answer matches the rule-passages command line passage for passage; the merged
answer shows where each passage ranked in each retriever. The 2019 rule's 61 sections, as the sections
endpoint first returned them, are there too, with citation counts still `null`. A later session on the
lead and copper sample fills those counts from `links.parquet` and lists the citing passages.

## frontend

The rule page calling the API on the MS2 sample: the screenshot above, and one page load as nginx and the
API logged it, in [`frontend/`](frontend/README.md).

## campaign-builder

Exact-match grouping and the B-cubed scorer (U-09): the tests by name (20 at capture on 12 Oct) and the grouper's first run on the
development docket's inline comment bodies are in [`campaign-builder/`](campaign-builder/README.md).

## data-processor

The processor's run on 50 development-docket records, with what it does and does not show, is in
[`data-processor/`](data-processor/README.md).

## passage-stage

The stage's run on the lead and copper sample, its counts and links per section are in
[`passage-stage/`](passage-stage/README.md). The hand check of the model-made labels is in
[`../hand-check/`](../hand-check/README.md).
