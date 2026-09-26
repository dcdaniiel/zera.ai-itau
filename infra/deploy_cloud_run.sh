#!/usr/bin/env bash
# Fallback: API do ADK no Cloud Run (com UI de dev). Rode na raiz do repo.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
rsync -a --delete motor/ zera_agent/motor/
rsync -a --delete --exclude '__pycache__' dados/ zera_agent/dados/
adk deploy cloud_run \
  --project="$PROJECT" --region="$REGION" \
  --otel_to_cloud \
  zera_agent -- --allow-unauthenticated --service-account="" --set-env-vars="GOOGLE_GENAI_USE_ENTERPRISE=1,ZERA_FONTE=csv"
