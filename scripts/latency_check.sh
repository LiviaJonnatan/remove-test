#!/usr/bin/env bash
# Times undersigned-api as a caller sees it, from this machine:
#   1. the first request, which is a cold start if the service has been idle long enough to scale
#      to zero (about 15 minutes),
#   2. N warm requests each to /health and /link, as p50 and p95,
#   3. the cold starts Cloud Run's own request log recorded in the last 30 days.
#
#   scripts/latency_check.sh        # N = 50
#   scripts/latency_check.sh 100
#
# Times include the network between this machine and Cloud Run. Needs gcloud logged in with an
# account that can call the service.
set -euo pipefail

N="${1:-50}"
PROJECT="${GCP_PROJECT:-ac215-undersigned}"
URL="$(gcloud run services describe undersigned-api --project "$PROJECT" --region us-central1 --format 'value(status.url)')"
TOKEN="$(gcloud auth print-identity-token)"
BODY='{"text": "Water systems should pay to replace the customer-owned portion of the service line.", "docket_id": "EPA-HQ-OW-2022-0801", "k": 3}'

# Each prints "status seconds".
health() {
  curl -s -o /dev/null -w '%{http_code} %{time_total}\n' --max-time 150 \
    -H "Authorization: Bearer $TOKEN" "$URL/health"
}
link() {
  curl -s -o /dev/null -w '%{http_code} %{time_total}\n' --max-time 150 -X POST "$URL/link" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$BODY"
}

# Reads a column of seconds, prints p50 and p95 in ms by nearest rank.
percentiles() {
  sort -n | awk '{ ms[NR] = $1 * 1000 } END {
    i50 = int(NR * 0.50); if (i50 < NR * 0.50) i50++
    i95 = int(NR * 0.95); if (i95 < NR * 0.95) i95++
    printf "%.0f ms | %.0f ms", ms[i50], ms[i95] }'
}

echo "First request, $(date -u +'%d %b %H:%M UTC'):"
read -r code secs < <(health)
if awk -v s="$secs" 'BEGIN { exit !(s > 10) }'; then kind="cold start"; else kind="already warm"; fi
echo "  GET /health $code in ${secs} s ($kind)"
echo

echo "Warm, $N requests each, from this machine:"
echo
echo "| Route | p50 | p95 | Requests | Not 200 |"
echo "|---|---|---|---|---|"
for route in health link; do
  results="$(for _ in $(seq "$N"); do "$route"; done)"
  not_ok="$(awk '$1 != 200' <<< "$results" | wc -l | tr -d ' ')"
  case "$route" in health) label="GET /health" ;; link) label="POST /link" ;; esac
  echo "| \`$label\` | $(awk '{ print $2 }' <<< "$results" | percentiles) | $N | $not_ok |"
done
echo

echo "Cold starts in Cloud Run's request log, last 30 days (requests that took 30 s or more):"
gcloud logging read --project "$PROJECT" \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"undersigned-api\" AND logName=\"projects/$PROJECT/logs/run.googleapis.com%2Frequests\" AND httpRequest.latency>=\"30s\"" \
  --freshness 30d --format 'value(timestamp,httpRequest.requestMethod,httpRequest.requestUrl,httpRequest.status,httpRequest.latency)' \
  | sed -E 's|https://[^/]+||; s|^([0-9-]+)T([0-9:]{5})[^[:space:]]*|  \1 \2 UTC|'
