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

# Pré-checagem dos dados: produção lê zera.perfis_demo (k-means) e grava estado/telemetria em zera.*.
# Se o dataset ainda não foi publicado (python -m dados.publicar_bq), cai para a amostra real embarcada + estado em JSON,
# avisa e segue — o serviço nunca sobe apontando para tabelas inexistentes.
if [ "$FONTE" = "bigquery" ]; then
  if command -v bq >/dev/null 2>&1 && bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv \
       'SELECT COUNT(*) AS n FROM `'"$PROJECT"'.zera.perfis_demo`' 2>/dev/null | tail -1 | grep -Eq '^[1-9][0-9]*$'; then
    echo ">> dados ok: zera.perfis_demo publicado"
  else
    echo "!! zera.perfis_demo não encontrado — rode 'python -m dados.publicar_bq' (precisa de ADC). Subindo com ZERA_FONTE=amostra (40 clientes reais, 12 meses) e estado em JSON."
    FONTE="amostra"; ESTADO="json"; TELEMETRIA_BQ=0
  fi
fi
TELEMETRIA_BQ="${TELEMETRIA_BQ:-$([ "$ESTADO" = "bigquery" ] && echo 1 || echo 0)}"
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
# 1 instância (min=max): sessões do ADK e cache de contexto vivem em processo — sem split-brain entre réplicas na demo.
# Escala horizontal é P1 (VertexAiSessionService + estado só no BigQuery). Concurrency 40 cobre a banca com folga.
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --allow-unauthenticated --service-account "$SA" \
  --min-instances 1 --max-instances 1 --concurrency 40 --memory 1Gi --cpu 1 --timeout 300 --cpu-boost \
  --labels "app=zera,versao=$VERSAO" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=1,GOOGLE_GENAI_USE_ENTERPRISE=1,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$LOCATION,ZERA_MODEL=$MODEL,ZERA_FONTE=$FONTE,ZERA_ESTADO=$ESTADO,ZERA_STRICT_NUMEROS=1,ZERA_HOJE=2026-09-26,ZERA_VERSAO=$VERSAO,ZERA_OTEL_GCP=$OTEL,ZERA_TELEMETRIA_BQ=$TELEMETRIA_BQ,ZERA_LOG_JSON=1,ZERA_LOG_LEVEL=INFO,ZERA_MODEL_ARMOR=${ZERA_MODEL_ARMOR:-0},ZERA_DOCS=0"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "UI + API no ar: $URL   (fonte=$FONTE estado=$ESTADO otel=$OTEL versão=$VERSAO)"
echo "smoke completo (health, ready, perfis, chat com Gemini, botão Contratar + HITL): infra/smoke_prod.sh $URL"
echo "logs:  gcloud run services logs read $SERVICE --region $REGION --limit 50"
echo "rollback: gcloud run services update-traffic $SERVICE --region $REGION --to-revisions=<revisao-anterior>=100"
echo "observabilidade (métricas de log, alertas, orçamento): infra/observabilidade.sh"
