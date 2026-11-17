# linker-train

Trains the section linker behind the API's `POST /link`: a contrastive fine-tune of
`BAAI/bge-small-en-v1.5` that ranks a rule's regulatory sections for one comment passage. It also
scores a run against every saved method, gates it against hybrid search and the served model, and
exports it to ONNX for the API. Results and the reasons behind each choice:
[README, Milestone 3](../README.md#milestone-3-the-linker).

- **Data:** the frozen linking set, in DVC. From the repo root:
  `uv run dvc pull data/linking.dvc data/linking-extra.dvc` (needs bucket access, see
  [setup, section 2](../docs/setup.md#2-the-full-data-team-members)). Read from `../data/linking` by
  default, or from `DATA_ROOT` / `--data`, including a `gs://` path.
- **Settings:** `configs/bge-small.yaml`; override any with `--set key=value`.
- **W&B:** project `undersigned-linker` on the team's CoreWeave Forge host, invite only.
  `uv run wandb login --host https://api.forge.coreweave.com` once.

## Commands

```bash
uv sync
uv run python src/main.py baseline                                    # untuned encoder
uv run python src/main.py train --mode in --out out/in                # the plain recipe
uv run python src/main.py train --mode in --set preamble_queries=true --combine --out out/in-pre   # the served recipe
uv run python src/main.py train --mode lodo --out out/lodo            # one model per held-out docket
uv run python src/main.py report --runs out/in out/in-pre out/in-pre+ctx --out out/report
uv run python src/main.py export --run out/in-pre --out out/in-pre/onnx
uv run python src/main.py promote --run out/in-pre --serve ../data/models/linker
```

`promote` writes `promotion.json` in the run either way, and exports to `--serve` only if the run
beats hybrid search and is no worse than the model already in `--serve`.

## Vertex AI (`vertex/`)

| File | What it does |
|---|---|
| `build.sh` | Builds this image in Cloud Build for the current commit (skipped if it exists) and prints its URI |
| `submit.sh` | Starts one custom job from `job.yaml`; `GPU=none` for a CPU machine. Anything after the mode goes to `train` |
| `job.yaml` | The job spec: n1-standard-8 with one T4, 10 hour timeout by default |
| `pipeline.py` | The Vertex AI pipeline: train, evaluate, gate and promote to `gs://ac215-undersigned-data/serving/linker/` |
| `run_pipeline.sh` | Builds the image if needed, then compiles and starts the pipeline |

Commands and the bucket layout: [setup, section 2b](../docs/setup.md#2b-the-linker-milestone-3).

`hill/` sets the trainer up as an Autolab task, with the held-out letters kept out of the agent's
workspace. Its run records live in the Autolab project, not here.

## Tests

`uv run pytest` (5 tests, offline) and `uv run ruff check .`.
