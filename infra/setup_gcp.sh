#!/usr/bin/env bash
# Prepara o projeto do evento para o Zera (idempotente). Rode uma vez, autenticado:
#   gcloud auth login && gcloud auth application-default login
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"

gcloud config set project "$PROJECT"

echo ">> APIs"
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com \
  logging.googleapis.com cloudtrace.googleapis.com secretmanager.googleapis.com \
  dlp.googleapis.com || true
# Model Armor pode não estar liberado no projeto do evento; tenta sem falhar
gcloud services enable modelarmor.googleapis.com 2>/dev/null || echo "(Model Armor não habilitado — guardrails seguem nos callbacks)"

echo ">> BigQuery dataset 'zera' (extrato clusterizado, features, perfil, dívidas, estado, eventos) — Firestore não está liberado"
bq --location="$REGION" ls -d "$PROJECT:zera" >/dev/null 2>&1 || bq --location="$REGION" mk -d "$PROJECT:zera"
bq query --use_legacy_sql=false --project_id="$PROJECT" < "$(dirname "$0")/../dados/sql/zera_tabelas.sql"
bq query --use_legacy_sql=false --project_id="$PROJECT" < "$(dirname "$0")/../dados/sql/eventos.sql"
echo ">> (opcional) agendar a atualização diária de features/perfil:"
echo "   bq mk --transfer_config --data_source=scheduled_query --display_name='zera features' --schedule='every 24 hours' --params='{\"query\":\"...\"}'"

echo ">> Bucket de staging"
gsutil ls -b "gs://$PROJECT-zera" >/dev/null 2>&1 || gsutil mb -l "$REGION" "gs://$PROJECT-zera"

echo ">> Pronto. Copie zera_agent/.env.example para zera_agent/.env e rode: adk web"
