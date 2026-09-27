#!/usr/bin/env bash
# Observabilidade e FinOps no GCP (idempotente): métricas baseadas em logs, política de alerta e orçamento de billing.
# Requer: logging.googleapis.com, monitoring.googleapis.com, billingbudgets.googleapis.com (já habilitadas no projeto).
#   infra/observabilidade.sh              # cria/atualiza tudo
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
SERVICE="${SERVICE:-zera}"
gcloud config set project "$PROJECT" >/dev/null

metrica() {  # nome, filtro, descrição
  gcloud logging metrics describe "$1" >/dev/null 2>&1 && gcloud logging metrics update "$1" --log-filter="$2" --description="$3" >/dev/null \
    || gcloud logging metrics create "$1" --log-filter="$2" --description="$3" >/dev/null
  echo "  metrica de log: $1"
}
BASE="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$SERVICE\""
echo ">> Métricas baseadas em logs (logs JSON estruturados da API)"
metrica zera_http_erros        "$BASE AND jsonPayload.message=\"http\" AND jsonPayload.status>=500"                       "Respostas 5xx da API zera.ai"
metrica zera_chamadas_llm      "$BASE AND jsonPayload.message=\"chamada_llm\""                                             "Chamadas ao Gemini (tokens/custo no payload)"
metrica zera_transicoes        "$BASE AND jsonPayload.message=\"transicao\""                                               "Transições da máquina de estados (funil)"
metrica zera_acordos_fechados  "$BASE AND jsonPayload.message=\"transicao\" AND jsonPayload.para=\"COMPLETED\""            "Acordos contratados"
metrica zera_nenhuma_opcao     "$BASE AND jsonPayload.message=\"transicao\" AND jsonPayload.para=\"NO_SUITABLE_OPTION\""   "Jornadas sem opção adequada"
metrica zera_guardrail         "$BASE AND jsonPayload.message:\"guardrail\""                                                "Bloqueios de guardrail (entrada/saída)"

echo ">> Política de alerta: taxa de erro 5xx (precisa de um canal de notificação; crie em Monitoring > Alerting se quiser e-mail)"
cat > /tmp/zera-alerta.json <<JSON
{
  "displayName": "zera.ai — erros 5xx na API",
  "combiner": "OR",
  "conditions": [{
    "displayName": "mais de 5 erros 5xx em 5 minutos",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/zera_http_erros\" AND resource.type=\"cloud_run_revision\"",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM"}],
      "comparison": "COMPARISON_GT", "thresholdValue": 5, "duration": "0s"
    }
  }]
}
JSON
gcloud alpha monitoring policies list --filter='displayName="zera.ai — erros 5xx na API"' --format='value(name)' | grep -q . \
  || gcloud alpha monitoring policies create --policy-from-file=/tmp/zera-alerta.json >/dev/null && echo "  alerta ok"

echo ">> Orçamento (FinOps): alerta em 50/90/100% de R\$ ${ORCAMENTO_BRL:-200}/mês na conta de billing do projeto"
BILLING=$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null || true)
if [ -n "$BILLING" ]; then
  gcloud billing budgets list --billing-account="${BILLING#billingAccounts/}" --format='value(displayName)' 2>/dev/null | grep -q "zera.ai" \
    || gcloud billing budgets create --billing-account="${BILLING#billingAccounts/}" --display-name="zera.ai — hackathon" \
         --budget-amount="${ORCAMENTO_BRL:-200}BRL" --filter-projects="projects/$PROJECT" \
         --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 >/dev/null && echo "  orçamento ok"
else
  echo "  (sem acesso à conta de billing — crie o orçamento no console: Billing > Budgets & alerts)"
fi
echo ">> Painéis: Cloud Trace (spans invocation/agent/call_llm/execute_tool + motor.*), Monitoring (workload.googleapis.com/zera.*),"
echo "   Logs Explorer (jsonPayload.message in [http, chamada_llm, transicao]), BigQuery zera.telemetria (Looker Studio)."
