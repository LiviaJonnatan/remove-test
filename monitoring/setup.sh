#!/usr/bin/env bash
# Sets up monitoring for undersigned-api in Cloud Monitoring from the files in this folder:
#   metrics/*.yaml   log-based metrics, read from the JSON line the API logs for every request
#   alerts/*.yaml    alert policies, emailed to every address in ALERT_EMAILS
#   dashboard.json   the dashboard
#
#   ALERT_EMAILS="a@example.com,b@example.com" monitoring/setup.sh
#
# Safe to run again after editing a file: metrics and alert policies are updated in place and the
# dashboard is replaced. Without ALERT_EMAILS it sets up the metrics and the dashboard only.
# Needs gcloud logged in, with the alpha and beta components (gcloud components install alpha beta).
set -euo pipefail

PROJECT="${GCP_PROJECT:-ac215-undersigned}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Log-based metrics"
for file in "$HERE"/metrics/*.yaml; do
  name="$(basename "$file" .yaml)"
  if gcloud logging metrics describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud logging metrics update "$name" --project "$PROJECT" --config-from-file "$file" >/dev/null
    echo "  updated $name"
  else
    gcloud logging metrics create "$name" --project "$PROJECT" --config-from-file "$file" >/dev/null
    echo "  created $name"
  fi
done

if [ -z "${ALERT_EMAILS:-}" ]; then
  echo "Alerts: skipped, ALERT_EMAILS is not set"
else
  echo "Email channels"
  channels=()
  IFS=',' read -ra emails <<< "$ALERT_EMAILS"
  for email in "${emails[@]}"; do
    email="${email// /}"
    channel="$(gcloud beta monitoring channels list --project "$PROJECT" \
      --filter "type=\"email\" AND labels.email_address=\"$email\"" --format 'value(name)' | head -n 1)"
    if [ -z "$channel" ]; then
      channel="$(gcloud beta monitoring channels create --project "$PROJECT" --type email \
        --display-name "undersigned-api alerts: $email" --channel-labels "email_address=$email" \
        --format 'value(name)')"
      echo "  created a channel for $email"
    else
      echo "  $email already has a channel"
    fi
    channels+=("$channel")
  done

  echo "Alert policies"
  for file in "$HERE"/alerts/*.yaml; do
    title="$(sed -n 's/^displayName: *//p' "$file")"
    # The policy as committed, plus the channels it emails.
    policy="$(mktemp)"
    cp "$file" "$policy"
    echo "notificationChannels:" >> "$policy"
    printf -- '- %s\n' "${channels[@]}" >> "$policy"
    existing="$(gcloud alpha monitoring policies list --project "$PROJECT" \
      --filter "displayName=\"$title\"" --format 'value(name)' | head -n 1)"
    if [ -n "$existing" ]; then
      gcloud alpha monitoring policies update "$existing" --project "$PROJECT" --policy-from-file "$policy" >/dev/null
      echo "  updated $title"
    else
      gcloud alpha monitoring policies create --project "$PROJECT" --policy-from-file "$policy" >/dev/null
      echo "  created $title"
    fi
    rm "$policy"
  done
fi

echo "Dashboard"
title="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["displayName"])' "$HERE/dashboard.json")"
# Create the new one first, then remove older ones with the same name, so a failed create leaves the
# old dashboard in place.
new="$(gcloud monitoring dashboards create --project "$PROJECT" --config-from-file "$HERE/dashboard.json" --format 'value(name)')"
echo "  created $title"
for old in $(gcloud monitoring dashboards list --project "$PROJECT" --filter "displayName=\"$title\"" --format 'value(name)'); do
  if [ "$old" != "$new" ]; then
    gcloud monitoring dashboards delete "$old" --project "$PROJECT" --quiet >/dev/null
    echo "  removed the previous $title"
  fi
done

echo
echo "Dashboard: https://console.cloud.google.com/monitoring/dashboards?project=$PROJECT"
echo "Alerts:    https://console.cloud.google.com/monitoring/alerting?project=$PROJECT"
