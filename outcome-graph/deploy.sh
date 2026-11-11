#!/usr/bin/env bash
# Deploy Oversight to Cloud Run as a public link. Iris and the coach run on Claude via Vertex AI
# with the service account. Accounts: Google sign-in through Identity Platform, state in Cloud SQL
# (instance oversight-db). The database URL is read from .cloudsql-url (gitignored) and passed as an
# env var: the service account can't read Secret Manager until an Owner grants it
# roles/secretmanager.secretAccessor on oversight-database-url (kept in sync); then swap the env var
# for: --set-secrets "DATABASE_URL=oversight-database-url:latest"
# .firebase-web-key holds the browser sign-in key: public by design, restricted to our domains.
#   ./deploy.sh            (uses the gcloud project already configured)
set -euo pipefail
cd "$(dirname "$0")"
REGION=${REGION:-us-central1}
PROJECT=ac215-undersigned
WEB_KEY=$(cat .firebase-web-key)
# DB_SECRET=1 (default): the service reads the URL from Secret Manager. Needs the one-time grant
# of roles/secretmanager.secretAccessor on oversight-database-url to the service account.
# DB_SECRET=0: pass it as a plain env var from .cloudsql-url instead (visible in the console).
if [ "${DB_SECRET:-1}" = 1 ]; then DB_FLAG=(--set-secrets "DATABASE_URL=oversight-database-url:latest"); DB_ENV=""
else DB_FLAG=(); DB_ENV=",DATABASE_URL=$(cat .cloudsql-url)"; fi

(cd web && npm ci --silent && npx vite build)

CTX=$(mktemp -d)
trap 'rm -rf "$CTX"' EXIT
cp -R Dockerfile pyproject.toml uv.lock src "$CTX"/
mkdir -p "$CTX/web"
cp -R web/dist "$CTX/web/"
# every built rule: its graph, details, excerpt vectors, and the excerpts table the store reads
for G in ../data/derived/outcomes/*/graph.json; do
  D=$(basename "$(dirname "$G")")
  mkdir -p "$CTX/data/outcomes/$D" "$CTX/data/responses/$D"
  cp ../data/derived/outcomes/$D/{graph.json,details.json} "$CTX/data/outcomes/$D/"
  cp ../data/derived/outcomes/$D/cites.json "$CTX/data/outcomes/$D/" 2>/dev/null || true
  cp ../data/raw/$D/rtc/rtc.pdf "$CTX/data/outcomes/$D/" 2>/dev/null || true  # EPA's document, for citations
  cp ../data/derived/outcomes/$D/excerpt_vec*.{npy,parquet} "$CTX/data/outcomes/$D/" 2>/dev/null || true
  cp ../data/derived/outcomes/$D/{ask,rule}_vec_*.npy "$CTX/data/outcomes/$D/" 2>/dev/null || true
  cp ../data/derived/responses/$D/{entries,rule_diff}.parquet "$CTX/data/responses/$D/"
  echo "packed $D"
done

gcloud run deploy outcome-graph --source "$CTX" --region "$REGION" \
  --allow-unauthenticated --memory 2Gi --cpu 1 --min-instances 0 --max-instances 2 --timeout 300 \
  --add-cloudsql-instances "$PROJECT:$REGION:oversight-db" \
  --set-env-vars "AGENT=${AGENT:-1},LLM_BACKEND=vertex,GOOGLE_CLOUD_PROJECT=$PROJECT,VERTEX_REGION=global,CLAUDE_MODEL=claude-sonnet-5-5,TTS_VOICE=en-US-Chirp3-HD-Aoede,FIREBASE_PROJECT=$PROJECT,FIREBASE_AUTH_DOMAIN=$PROJECT.firebaseapp.com,FIREBASE_API_KEY=$WEB_KEY,ADMIN_EMAILS=${ADMIN_EMAILS:-},PUBLIC_URL=https://outcome-graph-658318685216.us-central1.run.app$DB_ENV" ${DB_FLAG[@]+"${DB_FLAG[@]}"}
