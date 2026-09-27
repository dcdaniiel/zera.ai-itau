#!/usr/bin/env bash
# Prepara o projeto do evento para o zera.ai (idempotente). Rode uma vez, autenticado:
#   gcloud auth login && gcloud auth application-default login
# Usa SOMENTE serviços já habilitados no projeto (gcloud services list --enabled): BigQuery (+ML), Vertex AI, Cloud Run,
# Cloud Build, Artifact Registry, Logging, Monitoring, Telemetry (OTLP), Model Armor, Secret Manager, Pub/Sub, Billing Budgets.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${REGION:-us-central1}"
gcloud config set project "$PROJECT" >/dev/null

echo ">> 1) Camada de dados no BigQuery (tabelas zera.* + clusterização k-means + perfis da demo)"
python -m dados.publicar_bq

echo ">> 2) Model Armor: template de guardrails (injeção/jailbreak + dados sensíveis + conteúdo) — ZERA_MODEL_ARMOR=1 liga na API"
gcloud model-armor templates describe zera-guardrails --location="$REGION" >/dev/null 2>&1 || \
gcloud model-armor templates create zera-guardrails --location="$REGION" \
  --pi-and-jailbreak-filter-settings-enforcement=enabled --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
  --basic-config-filter-enforcement=enabled \
  --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"}]' \
  2>/dev/null && echo "  template criado" || echo "  (não foi possível criar o template — os guardrails locais dos callbacks continuam ativos)"

echo ">> 3) Segredos (opcional): chaves de terceiros nunca em env — ex.: gcloud secrets create zera-openfinance-key --data-file=-"
echo ">> 4) Scheduled query diária (BigQuery Data Transfer) para refazer features/perfis/clusters — exemplo:"
echo "   bq mk --transfer_config --project_id=$PROJECT --data_source=scheduled_query --display_name='zera dados' --schedule='every 24 hours' \\"
echo "      --params='{\"query\":\"CALL ... ou o conteúdo de dados/sql/zera_tabelas.sql renderizado\"}'"
echo ">> 5) Deploy: infra/deploy_app.sh   |   Observabilidade/FinOps: infra/observabilidade.sh"
