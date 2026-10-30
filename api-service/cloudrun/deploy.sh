#!/usr/bin/env bash
# Build the API image in Cloud Build and deploy it to Cloud Run, with the rule index and the
# promoted linker inside the image.
#
#   api-service/cloudrun/deploy.sh                          # model and index from the bucket
#   MODEL=linker-train/out/in/onnx INDEX=data/derived/chroma-lcr api-service/cloudrun/deploy.sh
#                                                           # publish local copies first, then deploy
#
# The service is private: a caller needs an identity token from an account with run.invoker, e.g.
#   curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"
# PUBLIC=1 opens it to anyone, a decision for the team (anyone could then run up the bill).
#
# The bucket holds what is served: gs://BUCKET/serving/linker/ (the model, with linker.json naming
# its run, commit and test accuracy) and gs://BUCKET/serving/index/ (the ChromaDB folder).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-ac215-undersigned}"
REGION="${REGION:-us-central1}"
BUCKET="${BUCKET:-ac215-undersigned-data}"
SERVICE="${SERVICE:-undersigned-api}"
COMMIT="$(git rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/undersigned/api-service:${COMMIT}"

if [ -n "${MODEL:-}" ]; then
  gcloud storage rsync --recursive --delete-unmatched-destination-objects "$MODEL" "gs://${BUCKET}/serving/linker"
fi
if [ -n "${INDEX:-}" ]; then
  gcloud storage rsync --recursive --delete-unmatched-destination-objects "$INDEX" "gs://${BUCKET}/serving/index"
fi

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
cp api-service/cloudrun/Dockerfile api-service/pyproject.toml api-service/uv.lock "$BUILD/"
cp -r api-service/src "$BUILD/src"
mkdir -p "$BUILD/lib"
cp -r rule-passages/src/rule_passages "$BUILD/lib/rule_passages"
find "$BUILD" -name __pycache__ -prune -exec rm -rf {} +

cp api-service/cloudrun/cloudbuild.yaml "$BUILD/"
gcloud builds submit "$BUILD" --project "$PROJECT" --region "$REGION" --config "$BUILD/cloudbuild.yaml" \
  --substitutions "_BUCKET=${BUCKET},_IMAGE=${IMAGE}"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
  "$([ "${PUBLIC:-0}" = 1 ] && echo --allow-unauthenticated || echo --no-allow-unauthenticated)" --memory 4Gi --cpu 2 --min-instances 0 --max-instances 2 \
  --concurrency 8 --timeout 60 --set-env-vars "GIT_COMMIT=${COMMIT}" --quiet
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format "value(status.url)"
