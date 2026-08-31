#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${FIREBASE_API_KEY:?Set FIREBASE_API_KEY}"

REGION="${REGION:-northamerica-northeast1}"
SERVICE="${SERVICE:-fincompass}"
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-$GOOGLE_CLOUD_PROJECT}"
FIREBASE_AUTH_DOMAIN="${FIREBASE_AUTH_DOMAIN:-${FIREBASE_PROJECT_ID}.firebaseapp.com}"

gcloud config set project "$GOOGLE_CLOUD_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --min 0 \
  --max 2 \
  --concurrency 20 \
  --timeout 300 \
  --set-env-vars "FINCOMPASS_HOSTED_MODE=1,FINCOMPASS_AUTH_MODE=required,FINCOMPASS_DATA_DIR=/tmp/fincompass,RATE_LIMIT_BACKEND=memory,AUDIT_IP_MODE=none,AUDIT_LOG_ENABLED=0,FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID},FIREBASE_API_KEY=${FIREBASE_API_KEY},FIREBASE_AUTH_DOMAIN=${FIREBASE_AUTH_DOMAIN}"

echo
echo "Deployment complete. Enable Email/Password in Firebase Authentication before testing sign-up."
