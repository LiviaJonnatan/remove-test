# Setup: running Undersigned from a fresh clone

Two ways to run it. **The demo** needs Docker and one free API key, nothing else. It takes about a minute on a laptop once the images are built, and about 16 minutes on a small VM including the build. **The full data** needs the team's cloud credentials and hours of API time. A course staff member or a new teammate should start with the demo.

## 1. The demo (about a minute on a laptop once images are built, about 16 minutes on a small VM including the build)

### What you need

| | |
| --- | --- |
| Docker Desktop (Mac/Windows) or Docker Engine + Compose plugin (Linux) | `docker compose version` should print 2.x |
| A `data.gov` API key | free and instant at https://api.data.gov/signup/; arrives by email |
| About 2 GB of disk | images plus the small demo data |
| Internet access to `api.regulations.gov`, `downloads.regulations.gov`, `huggingface.co`, `federalregister.gov` | the collector, the attachment downloads, the processor's image build, and the rule text |

No Google Cloud account, no service-account key, no DVC. The demo fetches its data live from the API.

### Steps

```bash
git clone https://github.com/aidaneichman/AC215_Undersigned.git
cd AC215_Undersigned
cp .env.example .env
```

Open `.env` and paste your key after `API_DATA_GOV_KEY=` (line 3; the lines above it are comments):

```
API_DATA_GOV_KEY=your_key_here
```

Leave everything else as it is. The defaults pull the 40-record demo sample from docket EPA-HQ-OW-2022-0801 (the 2023 Lead and Copper Rule Improvements) and the proposed rule those comments answer. Comments in `.env` must stay on their own lines; Docker treats anything after `=` as part of the value.

Then:

```bash
docker compose up --build
```

### What you should see

The first build takes a few minutes (the data-processor image downloads a small tokenizer from huggingface.co, the api-service image a small embedding model). After that, in order:

1. `chromadb` starts.
2. `data-collector` logs `fixed list of 40 records, index stage skipped`, then `details: 0 of 40 already on disk, 40 to fetch`, then a `done: {...}` summary and exits 0. About 40 API calls and 11 file downloads; under 10 seconds.
3. `data-processor` prints one JSON line (`"letters":40, "records_failed":0`, with the tokenize and raw-data checksums) and exits 0.
4. `campaign-builder` prints `40 letters: 18 in 2 containment groups, 22 individual` and exits 0: the sample's two campaigns, one group each, with two short campaign letters left out (see `docs/evidence/campaign-builder/containment.md`).
5. `rule-passages` (in parallel with 2 to 4) downloads the rule, logs `1108 chunks`, then `embedded 128/1108` ... `embedded 1108/1108`, and exits 0.
6. `passage-stage` waits for campaign-builder and rule-passages, prints `39 letters, 816 passages, 158 cite the rule's sections or other CFR text, 208 links to 15 sections of the rule, 1 to numbers outside it` and exits 0.
7. `api-service` logs `Read 209 passage links`, `Loaded 1108 rule passages` and `Application startup complete`, and stays up.
8. `frontend` (nginx) starts and stays up.

Whole run on a fresh VM: about 16 minutes, about 4 building the images and about 12 running the containers. Most of the 12 is rule-passages embedding the 1,108 passages on CPU. On a laptop with the images already built, the run takes about 70 seconds.

In a second terminal:

```bash
docker compose ps -a      # five Exited (0), three Up
curl localhost:8000/health
```

Then open:

- http://localhost:3000 — the page
- http://localhost:8000/docs — the API, with a form to try `POST /retrieve`
- http://localhost:9000/api/v2/heartbeat — ChromaDB

The first terminal stays attached to the servers; that's normal. Stop everything with Ctrl-C there, then `docker compose down`.

### Try the API

```bash
curl -s -X POST localhost:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"text": "Requiring all lead service lines to be replaced within ten years is not achievable for small water systems that cannot locate or afford to replace lines on private property.", "k": 3, "method": "both", "docket_id": "EPA-HQ-OW-2022-0801"}'
```

returns the rule passages that argument is about, from two retrievers (BM25, then embeddings). The same request can be made from the form at localhost:8000/docs; leave `docket_id` out or set it to the docket above.

### Where the data went

`data/raw/EPA-HQ-OW-2022-0801/` (the 40 records and their attachments, as the API returned them) and `data/derived/` (letters and groups). Both are git-ignored. `schema.md` describes every file.

## 2. The full data (team members)

This adds the team's versioned data from Google Cloud Storage.

### Extra things you need

| | |
| --- | --- |
| `uv` | https://docs.astral.sh/uv/ |
| The service-account key file | `undersigned-key.json`, shared directly by a team member |
| Access to the `ac215-undersigned` GCP project | the bucket is `gs://ac215-undersigned-data` |
| Disk | 3 GB for the development docket, ~7 GB for Clean Power Plan, 0.4 GB for lead and copper |

### Steps

```bash
# The key lives outside the repository, in a secrets/ folder next to it (as in the course template)
mkdir -p ../secrets && mv ~/Downloads/undersigned-key.json ../secrets/
export GOOGLE_APPLICATION_CREDENTIALS=../secrets/undersigned-key.json
export GRPC_ENABLE_FORK_SUPPORT=0 GRPC_VERBOSITY=ERROR    # silences a harmless gRPC crash message on Mac
uv sync
uv run dvc pull                      # everything; or one docket:
uv run dvc pull data/raw/EPA-HQ-OW-2018-0149.dvc
```

`dvc pull` fetches whatever version the checked-out `.dvc` pointer files name, so run `git pull` first.

To run the pipeline on a full docket instead of the demo, edit `.env`:

```
DOCKET_IDS=EPA-HQ-OW-2018-0149
RECORD_IDS_FILE=
MAX_RECORDS=
```

and `docker compose up`. The collector skips every record already on disk from `dvc pull`, so a docket that's fully pulled goes straight to the processor.

To pull a docket yourself from the API: same `.env`, no `dvc pull`, and expect about one hour per 1,000 records per key (11 hours for the development docket). The run is resumable. Afterwards `uv run dvc add data/raw/<docket>` and `uv run dvc push`, and commit the `.dvc` file. One person pulls a given docket at a time.

### On a Google Cloud VM

The demo on a VM needs exactly what it needs on a laptop: Docker and the data.gov key.

For the full-data path a VM is simpler than a laptop, because it can authenticate to the bucket as itself. Create it in the console: Compute Engine → VM instances → Create instance.

```bash
gcloud compute ssh undersigned-ms2 --zone us-central1-a -- -L 3000:localhost:3000 -L 8000:localhost:8000
```

On the VM, install Docker and uv, clone as above, then `uv run dvc pull` for the full data path. The `-L` flags make `localhost:3000` and `localhost:8000` on your laptop show the VM's stack without opening any firewall port. Stop the VM when done.

## 3. Every `.env` setting

| variable | demo needs it? | used by | meaning |
| --- | --- | --- | --- |
| `API_DATA_GOV_KEY` (or `API_DATA_GOV_KEYS`, comma-separated) | **yes** | data-collector | the data.gov key; several keys are rotated |
| `DOCKET_IDS` | default | all batch stages | which dockets to process, comma-separated |
| `RECORD_IDS_FILE` | default | data-collector, data-processor | fetch and process exactly these ids, skipping the index; the demo list |
| `MAX_RECORDS` | default | data-collector, data-processor | cap for smoke tests; ignored while `RECORD_IDS_FILE` is set |
| `SKIP_ATTACHMENTS` | default `0` | data-collector | `1` skips attachment downloads |
| `SHARD` | empty | data-collector | `k/n` to split a pull across containers |
| `SIGNER_HASH_KEY` | not yet | data-processor | secret for hashing signer names |
| `GCP_PROJECT`, `GCS_BUCKET` | no | nothing yet | reserved for cloud jobs |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | nothing yet | path inside containers; `dvc pull` on a laptop needs the variable exported in your shell instead, and on a GCP VM with the service account attached needs nothing |
| `WANDB_API_KEY` | no | none yet | for experiment tracking |

### What needs credentials, and when

| credential | needed by | when |
| --- | --- | --- |
| data.gov key | data-collector | every run that fetches records |
| service-account key | `dvc pull` / `dvc push` on a laptop | only when moving data to or from the bucket. A GCP VM with the service account attached needs no key file |
| none | huggingface.co, federalregister.gov | image build (processor, api-service) and rule-passages' fetch; public, no key |

## 4. Troubleshooting

| symptom | cause | fix |
| --- | --- | --- |
| `env file .env not found` | `cp .env.example .env` not done | do it |
| `ValueError: invalid literal for int()` with a comment in the message | a comment after a value in `.env` | move comments to their own lines |
| `no API keys: set API_DATA_GOV_KEYS` | key line empty | paste the key |
| `RECORD_IDS_FILE ...: id ... is not in DOCKET_IDS` | `DOCKET_IDS` changed but the demo list is still set | empty `RECORD_IDS_FILE`, or set `DOCKET_IDS` back |
| collector logs "all keys at their hourly limit; sleeping" | the key's 1,000 requests/hour are used, often by another job on the same key | wait, or give the pipeline its own key |
| a batch container `Exited (1)` and api-service never starts | compose enforces the stage order; a failed stage blocks the rest | `docker compose logs <that service>` |
| `403 Forbidden` on an attachment download | the agency's server refuses a few files | logged in `manifest.json`, run continues |
| `dvc pull` prints gRPC `fork_posix` errors at the end | Mac-only teardown noise after a successful pull | ignore, or export the two `GRPC_` variables above |
| `dvc status` says a raw folder is modified after a demo run | the demo rewrote `manifest.json` in the full docket's folder | `uv run dvc checkout`; never `dvc add` it |
| api-service exits with "collection is empty" | rule-passages hasn't run | `docker compose run --rm rule-passages` |
| processor image build fails reaching huggingface.co | network block or HF outage | retry; nothing in our code |
| `/retrieve` returns `{"hits": []}` | `docket_id` set to a docket the index doesn't hold (the Swagger example value `"string"`) | leave `docket_id` out or set it to the docket you ran |


## 5. Tests and lint

Each container has its own tests, offline:

```bash
cd data-collector && uv sync && uv run pytest && uv run ruff check . && cd ..
```

Same for `data-processor`, `campaign-builder`, `passage-stage`, `rule-passages`, `api-service`. The frontend:

```bash
cd frontend && npm ci && npm test
```

GitHub Actions runs all of them on every pull request (`.github/workflows/ci.yml`).