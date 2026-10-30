#!/usr/bin/env bash
# Build the training image in Cloud Build, push it to Artifact Registry and start one Vertex AI
# custom job on a T4. Nothing is built on the laptop.
#
#   vertex/submit.sh in                 # train on every docket's training comments
#   vertex/submit.sh lodo               # one model per held-out docket
#   GPU=none vertex/submit.sh in        # CPU machine (MACHINE, default e2-standard-16), no GPU quota needed
#   vertex/submit.sh in --set preamble_queries=true --combine   # anything after the mode goes to train
#   TIMEOUT_HOURS=10 stops a job that runs longer (default 10)
#   DRY_RUN=1 prints the job spec instead of starting it
#
# Needs: gcloud logged in (gcloud auth login) on the ac215-undersigned project, and the frozen set in the bucket
# (dvc push, or gsutil -m cp -r data/linking gs://ac215-undersigned-data/linking).
# The W&B key is read from your environment or ../.env and passed to the job as an env var.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-in}"
shift || true
EXTRA=""
for a in "$@"; do EXTRA="${EXTRA}, \"${a}\""; done
TIMEOUT_S=$(( ${TIMEOUT_HOURS:-10} * 3600 ))
PROJECT="${GCP_PROJECT:-ac215-undersigned}"
REGION="${REGION:-us-central1}"
BUCKET="${BUCKET:-ac215-undersigned-data}"
GPU="${GPU:-NVIDIA_TESLA_T4}"
COMMIT="$(git rev-parse --short HEAD)"
RUN="${NAME:-${MODE}}-$(date +%m%d-%H%M)"

if [ -z "${WANDB_API_KEY:-}" ] && [ -f ../.env ]; then
  WANDB_API_KEY="$(grep -E '^WANDB_API_KEY=' ../.env | cut -d= -f2- | tr -d '"')"
fi

IMAGE="${IMAGE:-$(vertex/build.sh)}"

JOB="$(mktemp)"
sed -e "s|__IMAGE__|${IMAGE}|" -e "s|__MODE__|${MODE}|" -e "s|__RUN__|${RUN}|g" -e "s|__BUCKET__|${BUCKET}|g" \
    -e "s|__COMMIT__|${COMMIT}|" -e "s|__EXTRA_ARGS__|${EXTRA}|" -e "s|__TIMEOUT__|${TIMEOUT_S}s|" \
    -e "s|__WANDB_KEY__|${WANDB_API_KEY:-}|" vertex/job.yaml > "$JOB"
if [ "$GPU" = none ]; then
  sed -i.bak -e '/accelerator/d' -e "s|machineType: .*|machineType: ${MACHINE:-e2-standard-16}|" "$JOB" && rm -f "$JOB.bak"
else
  sed -i.bak "s|acceleratorType: .*|acceleratorType: ${GPU}|" "$JOB" && rm -f "$JOB.bak"
fi
if [ -n "${DRY_RUN:-}" ]; then
  # The key is never printed: the line is replaced with whether one is set.
  awk -v set="${WANDB_API_KEY:+yes}" 'prev ~ /WANDB_API_KEY/ {print "          value: <wandb key set: " (set ? set : "no") ">"; prev=""; next} {print; prev=$0}' "$JOB"
  rm -f "$JOB"; exit 0
fi
gcloud ai custom-jobs create --project "$PROJECT" --region "$REGION" \
  --display-name "linker-${RUN}" --config "$JOB"
rm -f "$JOB"
echo "Output: gs://${BUCKET}/linker-runs/${RUN}/"
