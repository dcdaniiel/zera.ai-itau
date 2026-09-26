#!/usr/bin/env bash
# Deploy no Vertex AI Agent Engine (Sessions + Memory Bank gerenciados). Rode na raiz do repo.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
# requirements do pacote do agente (o Agent Engine instala isso)
cat > zera_agent/requirements.txt <<REQ
google-adk
google-cloud-aiplatform[agent_engines]
google-cloud-firestore
google-cloud-bigquery
db-dtypes
pandas
REQ
# o Agent Engine empacota só a pasta do agente: copia motor/ e dados/ para dentro dela
rsync -a --delete motor/ zera_agent/motor/
rsync -a --delete --exclude '__pycache__' dados/ zera_agent/dados/
adk deploy agent_engine \
  --project="$PROJECT" --region="$REGION" \
  --display_name="Zera" --description="Renegociação que cabe no mês do cliente" \
  --otel_to_cloud \
  ${AGENT_ENGINE_ID:+--agent_engine_id="$AGENT_ENGINE_ID"} \
  zera_agent
