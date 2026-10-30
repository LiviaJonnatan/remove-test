#!/usr/bin/env bash
# Build the linker-train image for the current commit in Cloud Build (skipped if it already exists)
# and print its URI. Used by submit.sh and run_pipeline.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-ac215-undersigned}"
REGION="${REGION:-us-central1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/undersigned/linker-train:$(git rev-parse --short HEAD)"
gcloud artifacts repositories describe undersigned --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud artifacts repositories create undersigned --repository-format docker --location "$REGION" --project "$PROJECT" >&2
if ! gcloud artifacts docker images describe "$IMAGE" >/dev/null 2>&1; then
  gcloud builds submit --project "$PROJECT" --region "$REGION" --tag "$IMAGE" --timeout 40m \
    --machine-type e2-highcpu-8 . >&2
fi
echo "$IMAGE"
