#!/usr/bin/env bash
# Build the image for this commit if needed, then compile and start the Vertex AI pipeline
# (train, evaluate, gate and promote). Extra arguments go to pipeline.py, e.g. --epochs 2 or --gpu.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="$(vertex/build.sh)"
if [ -z "${WANDB_API_KEY:-}" ] && [ -f ../.env ]; then
  WANDB_API_KEY="$(grep -E '^WANDB_API_KEY=' ../.env | cut -d= -f2- | tr -d '"')"
  export WANDB_API_KEY
fi
uv run --group pipeline python vertex/pipeline.py --image "$IMAGE" "$@"
