#!/usr/bin/env bash
# Deploy de PRODUÇÃO do app completo (API + agente ADK + UI) em UM serviço do Cloud Run. Rode na raiz do repo.
#   gcloud auth login && gcloud config set project batalha-time-03-vhxk
#   python -m dados.publicar_bq          # 1x: tabelas zera.* + clusterização (precisa de ADC: gcloud auth application-default login)
#   infra/deploy_app.sh                  # build (Cloud Build, Dockerfile multi-stage) + deploy + IAM mínimo
# Variáveis opcionais: SERVICE, REGION, ZERA_MODEL, ZERA_FONTE (bigquery|amostra), ZERA_ESTADO (bigquery|json), ZERA_OTEL_GCP (1|0)
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${REGION:-us-central1}"          # região do Cloud Run (o modelo usa GOOGLE_CLOUD_LOCATION abaixo)
SERVICE="${SERVICE:-zera}"
MODEL="${ZERA_MODEL:-gemini-3.8-flash}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
FONTE="${ZERA_FONTE:-bigquery}"
ESTADO="${ZERA_ESTADO:-bigquery}"
OTEL="${ZERA_OTEL_GCP:-1}"
VERSAO="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"

gcloud config set project "$PROJECT" >/dev/null
echo ">> APIs necessárias (as já habilitadas são ignoradas)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com \
  bigquery.googleapis.com logging.googleapis.com monitoring.googleapis.com telemetry.googleapis.com modelarmor.googleapis.com >/dev/null

# Service account dedicada (princípio do menor privilégio): Vertex AI, BigQuery (dados/estado/telemetria), Logging, Monitoring, Trace, Model Armor
SA_NAME="${SA_NAME:-zera-run}"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || gcloud iam service-accounts create "$SA_NAME" --display-name "zera.ai Cloud Run" >/dev/null
for ROLE in roles/aiplatform.user roles/bigquery.dataEditor roles/bigquery.jobUser roles/logging.logWriter roles/monitoring.metricWriter \
            roles/cloudtrace.agent roles/telemetry.tracesWriter roles/telemetry.metricsWriter roles/modelarmor.user; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null 2>&1 \
    || echo "(sem permissão para dar $ROLE — peça ao admin se algo falhar em runtime)"
done

echo ">> Build + deploy ($SERVICE em $REGION, versão $VERSAO, fonte=$FONTE, estado=$ESTADO, otel=$OTEL)"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --allow-unauthenticated --service-account "$SA" \
  --min-instances 1 --max-instances 2 --concurrency 40 --memory 1Gi --cpu 1 --timeout 120 --cpu-boost \
  --labels "app=zera,versao=$VERSAO" \
  --set-env-vars "GOOGLE_GENAI_USE_ENTERPRISE=1,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$LOCATION,ZERA_MODEL=$MODEL,ZERA_FONTE=$FONTE,ZERA_ESTADO=$ESTADO,ZERA_STRICT_NUMEROS=1,ZERA_HOJE=2026-09-26,ZERA_VERSAO=$VERSAO,ZERA_OTEL_GCP=$OTEL,ZERA_TELEMETRIA_BQ=1,ZERA_LOG_JSON=1,ZERA_LOG_LEVEL=INFO,ZERA_MODEL_ARMOR=${ZERA_MODEL_ARMOR:-0},ZERA_DOCS=0"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "UI + API no ar: $URL"
echo "smoke: curl -s $URL/health; curl -s $URL/ready; curl -s $URL/v1/clientes | head -c 400; curl -s $URL/metrics | head -c 400"
echo "logs:  gcloud run services logs read $SERVICE --region $REGION --limit 50"
echo "observabilidade (métricas de log, alertas, orçamento): infra/observabilidade.sh"
