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

## 2b. The linker (Milestone 3)

The trained model behind `POST /link`. Four things you might want to do, each independent: run the training locally, run it on Vertex AI, run the pipeline that gates and promotes a model, and deploy or call the API on Cloud Run. The demo in section 1 does not need any of this: it serves `/retrieve` and the rule page, and `/link` answers 503 there until a model is mounted (see "Serving `/link` locally" below).

### What you need

| | |
| --- | --- |
| Everything in section 2 | `uv`, the service-account key, access to the GCP project |
| The frozen linking set | `uv run dvc pull data/linking.dvc data/linking-extra.dvc` (small; `train.json`, `test.json`, `uncited.json`, the rules, and the preamble windows) |
| A Weights & Biases account on the team's host | the project is at https://forge.coreweave.com/wandb/aidaneichman-harvard-university/undersigned-linker; ask Aidan to add you |
| `gcloud` logged in as yourself | `gcloud auth login` and `gcloud config set project ac215-undersigned`, for Vertex, Cloud Build and Cloud Run. The service-account key is for DVC only |
| Disk and time, local training | about 45 minutes on an M2 Pro per 4-epoch run; the base model (130 MB) downloads once |

### Train locally

```bash
uv run dvc pull data/linking.dvc data/linking-extra.dvc
cd linker-train
uv sync
uv run wandb login --host https://api.forge.coreweave.com        # once; paste your key from the team host
uv run python src/main.py baseline                               # untuned encoder: 44.7% top-1 on the test set, no training
uv run python src/main.py train --mode in --out out/in           # the served configuration
uv run python src/main.py report --runs out/in --out out/report  # the tables in the README
```

`--mode in` trains on every docket's citing passages; `--mode lodo` trains one model per held-out docket (`--holdout ED-2021-OCR-0166` for just one). Settings are in `configs/bge-small.yaml`; override any with `--set key=value` (`--set epochs=1` for a smoke run). Data is found at `../data/linking` by default, or wherever `DATA_ROOT` or `--data` points, including a `gs://` path.

To add the preamble and letter-citation scores to a trained run (the `in-pre` + scores row in the README): `uv run python src/main.py combine --run out/in --extras ../data/linking-extra`.

A run writes `config.json`, `history.json`, `metrics.json` and `predictions.jsonl` into its `--out` folder, and the same into W&B (project `undersigned-linker`, run name from `--name`, default the folder name). `out/` and `wandb/` are git-ignored; the evidence copies in `docs/evidence/linker-train/` were copied in by hand.

### Train on Vertex AI

```bash
cd linker-train
GPU=none vertex/submit.sh in                  # CPU machine, no GPU quota needed
vertex/submit.sh in                           # one T4; needs the project's T4 quota
vertex/submit.sh lodo --holdout ED-2021-OCR-0166 --set preamble_queries=true --combine
DRY_RUN=1 vertex/submit.sh in                 # print the job spec instead of starting it
```

`submit.sh` builds the image for the current commit in Cloud Build (`vertex/build.sh`, tagged with the short commit hash, skipped if it already exists), then starts one custom job that reads `gs://ac215-undersigned-data/linking` and writes `gs://ac215-undersigned-data/linker-runs/<run>/`. The frozen set must already be in the bucket: `dvc push` puts it there. The W&B key is taken from `WANDB_API_KEY` in your shell or from `../.env`. Jobs time out after 10 hours (`TIMEOUT_HOURS`). A CPU run on `e2-standard-16` takes about an hour an epoch; follow it at https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=ac215-undersigned and in W&B.

### Run the pipeline (train, evaluate, gate, promote)

```bash
cd linker-train
vertex/run_pipeline.sh                        # 4 epochs on CPU
vertex/run_pipeline.sh --epochs 1             # smoke run
vertex/run_pipeline.sh --gpu                  # once there is T4 quota
```

Three steps, all on the same image: **train** (as above), **evaluate** (the report against every saved method) and **gate and promote**, which copies the ONNX export to `gs://ac215-undersigned-data/serving/linker/` only if the run beats hybrid search (lower end of the paired difference above zero) and is no worse than the model now served, compared at three decimals. Either way the step writes `promotion.json` in the run folder saying what it decided and why. Runs are at https://console.cloud.google.com/vertex-ai/pipelines/runs?project=ac215-undersigned; the compiled spec lands in vertex/pipeline.json and should not be committed.

Promote a local run by hand with the same gate: `promote --run out/in --serve <serving folder>`; the pipeline passes `/gcs/ac215-undersigned-data/serving/linker`.

### Deploy to Cloud Run

```bash
api-service/cloudrun/deploy.sh                                              # what the bucket holds
MODEL=linker-train/out/in/onnx INDEX=data/derived/chroma-lcr api-service/cloudrun/deploy.sh   # push local copies first
```

`deploy.sh` builds the API image in Cloud Build with the rule index and the promoted linker copied in from `gs://ac215-undersigned-data/serving/`, so the service needs no ChromaDB server, then deploys it as `undersigned-api` in `us-central1` (2 CPU, 4 GiB, scales to zero, at most 2 instances, 60 s timeout). The image is tagged with the commit hash and `GIT_COMMIT` is set in the service so `/health` and `/link` report it. The service is **private**: `PUBLIC=1` would open it to anyone and is a team decision.

### Call the deployed API

A caller needs the `run.invoker` role on the service (ask Aidan or whoever owns the project to grant it to your Google account) and sends an identity token:

```bash
URL=$(gcloud run services describe undersigned-api --region us-central1 --format 'value(status.url)')
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" "$URL/health"            # "linker": {run, commit, test_acc@1, ...}
curl -s -X POST "$URL/link" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "text": "Requiring systems to replace every lead service line within ten years is not feasible for small utilities with limited staff.",
  "docket_id": "EPA-HQ-OW-2022-0801", "k": 3}'
curl -s -H "Authorization: Bearer $TOKEN" "$URL/stats"             # per-route counts, errors, p50/p90/p99 since the instance started
```

`403` with no body means no token or no `run.invoker`; `503` from `/link` means the image was built without a model in `serving/linker/`. To score the served model on the frozen lead-and-copper test passages, the check the README's evidence comes from:

```bash
ID_TOKEN="$TOKEN" uv run python scripts/link_check.py --api "$URL" --out docs/evidence/cloud-run/link-check.json
```

Request logs: `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="undersigned-api" AND jsonPayload.route="/link"' --limit 20`. One JSON line per request (`route`, `status`, `latency_ms`, `severity`), never the body.

### Serving `/link` locally

`docker-compose.yml` does not mount a model, so the compose stack's `/link` answers 503 and `/health` reports `"linker": null`. To serve one locally, export a run and point the API at it:

```bash
cd linker-train && uv run python src/main.py export --run out/in --out out/in/onnx && cd ..
# or fetch the promoted model:  gcloud storage cp -r gs://ac215-undersigned-data/serving/linker data/models/linker
LINKER_MODEL_DIR=/app/linker docker compose run --rm --service-ports \
  -v "$PWD/linker-train/out/in/onnx:/app/linker:ro" api-service
```

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
| `GCP_PROJECT`, `GCS_BUCKET` | no | `vertex/submit.sh`, `vertex/pipeline.py`, `cloudrun/deploy.sh` | which project and bucket the cloud jobs use; the scripts default to `ac215-undersigned` and `ac215-undersigned-data` |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | `dvc pull` / `dvc push` | path to the service-account key, exported in your shell on a laptop; a GCP VM with the service account attached needs nothing. Vertex and Cloud Run use their own identities, not this file |
| `WANDB_API_KEY` | no | linker-train, read by `submit.sh` and `run_pipeline.sh` from `../.env` when not in the shell | experiment tracking in the `undersigned-linker` project |

### What needs credentials, and when

| credential | needed by | when |
| --- | --- | --- |
| data.gov key | data-collector | every run that fetches records |
| service-account key | `dvc pull` / `dvc push` on a laptop | only when moving data to or from the bucket. A GCP VM with the service account attached needs no key file |
| none | huggingface.co, federalregister.gov | image build (processor, api-service) and rule-passages' fetch; public, no key |
| Google account (`gcloud auth login`) | Vertex jobs, the pipeline, Cloud Build, `deploy.sh`, calling the private API | anything in section 2b except local training |
| W&B key | linker-train | every training run; passed to Vertex jobs as an environment variable in the job spec |
| `run.invoker` on `undersigned-api` | calling the deployed API | granted per Google account by a project owner |

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
| `FileNotFoundError: .../data/linking/train.json` | the frozen set is not pulled | `uv run dvc pull data/linking.dvc data/linking-extra.dvc` from the repo root |
| Vertex job fails at start reading `gs://.../linking` | the set is in DVC but not pushed to the bucket path the job reads | `uv run dvc push`, or `gsutil -m cp -r data/linking gs://ac215-undersigned-data/linking` |
| `submit.sh` fails with a quota error on `NVIDIA_TESLA_T4` | the project's T4 quota is 0 | `GPU=none vertex/submit.sh in`, or wait for the quota request |
| `n1-highcpu-16` has no capacity | regional stock-out | `MACHINE=e2-standard-16` (the default) |
| the pipeline's promote step writes `promote: false` | the run did not beat hybrid search, or scored below the served model at three decimals | read `promotion.json` in the run folder; the served score is in `serving/linker/linker.json` |
| Cloud Run returns `403` with an empty body | no token, or your account lacks `run.invoker` | `-H "Authorization: Bearer $(gcloud auth print-identity-token)"`; ask for the role |
| Cloud Run `/link` returns `503 No linker model` | the image was built with nothing in `serving/linker/` | promote a run, then `deploy.sh` again |
| Cloud Run revision fails to start, memory | the image loads two models; 2 GiB was not enough | `deploy.sh` sets 4 GiB; do not lower it |
| compose `/link` returns 503 | no model mounted in the compose stack | see "Serving `/link` locally" |

## 5. Tests and lint

Each container has its own tests, offline:

```bash
cd data-collector && uv sync && uv run pytest && uv run ruff check . && cd ..
```

Same for `data-processor`, `campaign-builder`, `passage-stage`, `rule-passages`, `api-service` and `linker-train` (the last pulls the CUDA build of torch on Linux, so its first `uv sync` is a few GB). The frontend:

```bash
cd frontend && npm ci && npm test
```

GitHub Actions runs all of them on every pull request (`.github/workflows/ci.yml`).