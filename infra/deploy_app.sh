#!/usr/bin/env bash
# Deploy do app completo (API + agente + UI) em UM serviço do Cloud Run. Rode na raiz do repo.
#   gcloud auth login && infra/deploy_app.sh
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${REGION:-us-central1}"          # região do Cloud Run (o modelo usa GOOGLE_CLOUD_LOCATION abaixo)
SERVICE="${SERVICE:-zera}"
MODEL="${ZERA_MODEL:-gemini-3.8-flash}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com bigquery.googleapis.com >/dev/null

# a service account do Cloud Run precisa chamar o Vertex AI (e o BigQuery, se ZERA_FONTE/ZERA_ESTADO=bigquery)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for ROLE in roles/aiplatform.user roles/bigquery.dataEditor roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null 2>&1 || echo "(sem permissão para dar $ROLE — peça ao admin se a chamada ao Gemini falhar)"
done

gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 1Gi --cpu 1 --timeout 120 \
  --set-env-vars "GOOGLE_GENAI_USE_ENTERPRISE=1,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$LOCATION,ZERA_MODEL=$MODEL,ZERA_FONTE=${ZERA_FONTE:-csv},ZERA_ESTADO=${ZERA_ESTADO:-json},ZERA_STRICT_NUMEROS=1,ZERA_HOJE=2026-09-26"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "UI + API no ar: $URL   (health: $URL/health)"
