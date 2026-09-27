#!/usr/bin/env bash
# Deploy de PRODUÇÃO do app completo (API + agente ADK + UI) em UM serviço do Cloud Run. Rode na raiz do repo.
#   gcloud auth login && gcloud config set project batalha-time-03-vhxk
#   python -m dados.publicar_bq          # 1x: tabelas zera.* + clusterização (precisa de ADC: gcloud auth application-default login)
#   infra/deploy_app.sh                  # build (Cloud Build, Dockerfile multi-stage) + deploy + IAM mínimo
# Variáveis opcionais: SERVICE, REGION, ZERA_MODEL, ZERA_FONTE (bigquery|amostra), ZERA_ESTADO (bigquery|json), ZERA_OTEL_GCP (1|0)
#   Gemini sem IAM na identidade de runtime (403 aiplatform.endpoints.predict — ver infra/producao.md §1c):
#   ZERA_GEMINI_API_KEY_SECRET=<secret no Secret Manager>  (recomendado)  |  ZERA_GEMINI_API_KEY=<chave> (vira variável do serviço)
#   ZERA_GEMINI_API_KEY_MODO=vertex (padrão: Vertex AI modo express, chave com alvo aiplatform.googleapis.com) | developer (AI Studio)
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
REGION="${REGION:-us-central1}"          # região do Cloud Run (o modelo usa GOOGLE_CLOUD_LOCATION abaixo)
SERVICE="${SERVICE:-zera}"
MODEL="${ZERA_MODEL:-gemini-3.8-flash}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
FONTE="${ZERA_FONTE:-bigquery}"
ESTADO="${ZERA_ESTADO:-bigquery}"
# OTel para telemetry.googleapis.com fica desligado por padrão: no projeto do evento a Org Policy bloqueia cloudtrace.googleapis.com
# e os exportadores só geram erro. Logs JSON (Cloud Logging), /metrics e zera.telemetria continuam. ZERA_OTEL_GCP=1 religa.
OTEL="${ZERA_OTEL_GCP:-0}"
VERSAO="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"

gcloud config set project "$PROJECT" >/dev/null

# Pré-checagem dos dados: produção lê zera.perfis_demo (k-means) e grava estado/telemetria em zera.*.
# Se o dataset ainda não foi publicado (python -m dados.publicar_bq), cai para a amostra real embarcada + estado em JSON,
# avisa e segue — o serviço nunca sobe apontando para tabelas inexistentes.
if [ "$FONTE" = "bigquery" ]; then
  if command -v bq >/dev/null 2>&1 && bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv \
       'SELECT COUNT(*) AS n FROM `'"$PROJECT"'.zera.perfis_demo`' 2>/dev/null | tail -1 | grep -Eq '^[1-9][0-9]*$'; then
    echo ">> dados ok: zera.perfis_demo publicado"
    # A identidade de runtime do Cloud Run pode não ter bigquery.jobs.create (IAM travado no projeto do evento). Exporta agora,
    # com a SUA credencial, o resultado do BigQuery ML (perfis_demo + perfil agregado + dívidas + clusters) para
    # dados/snapshot_bq/ — vai dentro da imagem e a API usa automaticamente se o BigQuery recusar a consulta em runtime.
    if ZERA_FONTE=bigquery GOOGLE_CLOUD_PROJECT="$PROJECT" ${PYTHON:-uv run python} -m dados.exportar_snapshot_bq; then
      echo ">> snapshot do BigQuery embarcado (fallback automático se o runtime não tiver permissão)"
    else
      echo "!! não consegui exportar o snapshot — se o runtime não tiver permissão no BigQuery, /ready vai falhar; use ZERA_FONTE=amostra"
    fi
  else
    echo "!! zera.perfis_demo não encontrado — rode 'python -m dados.publicar_bq' (precisa de ADC). Subindo com ZERA_FONTE=amostra (40 clientes reais, 12 meses) e estado em JSON."
    FONTE="amostra"; ESTADO="json"; TELEMETRIA_BQ=0
  fi
fi
TELEMETRIA_BQ="${TELEMETRIA_BQ:-$([ "$ESTADO" = "bigquery" ] && echo 1 || echo 0)}"
echo ">> APIs necessárias (as já habilitadas são ignoradas)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com \
  bigquery.googleapis.com logging.googleapis.com monitoring.googleapis.com telemetry.googleapis.com modelarmor.googleapis.com >/dev/null

# Service account dedicada (princípio do menor privilégio): Vertex AI, BigQuery (dados/estado/telemetria), Logging, Monitoring, Trace, Model Armor.
# No projeto do evento a conta pode não ter iam.serviceAccounts.create: nesse caso o Cloud Run usa a identidade padrão do projeto
# (<número>-compute@developer.gserviceaccount.com), que já tem os papéis necessários — o deploy segue sem parar.
SA_NAME="${SA_NAME:-zera-run}"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SA_FLAG=""   # bash 3.2 do macOS + set -u: string simples em vez de array vazio
if gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || gcloud iam service-accounts create "$SA_NAME" --display-name "zera.ai Cloud Run" >/dev/null 2>&1; then
  for ROLE in roles/aiplatform.user roles/bigquery.dataEditor roles/bigquery.jobUser roles/logging.logWriter roles/monitoring.metricWriter \
              roles/cloudtrace.agent roles/telemetry.tracesWriter roles/telemetry.metricsWriter roles/modelarmor.user; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null 2>&1 \
      || echo "(sem permissão para dar $ROLE — peça ao admin se algo falhar em runtime)"
  done
  SA_FLAG="--service-account=$SA"
  echo ">> service account: $SA"
else
  echo "!! sem permissão para criar a service account $SA_NAME — usando a identidade padrão do Cloud Run (conta compute do projeto)"
fi

echo ">> Build + deploy ($SERVICE em $REGION, versão $VERSAO, fonte=$FONTE, estado=$ESTADO, otel=$OTEL)"
# 1 instância (min=max): sessões do ADK e cache de contexto vivem em processo — sem split-brain entre réplicas na demo.
# Escala horizontal é P1 (VertexAiSessionService + estado só no BigQuery). Concurrency 40 cobre a banca com folga.
# Repositório de imagens: `--source` cria "cloud-run-source-deploy" no Artifact Registry, o que exige
# artifactregistry.repositories.create — negado no projeto do evento. Reaproveita qualquer repositório Docker já existente
# (em qualquer região) via --image; se não houver nenhum, imprime o comando de 1 linha para quem tem permissão (owner/organização).
IMAGE_FLAG=""
if [ -n "${AR_REPO:-}" ]; then
  IMAGE_FLAG="--image=${AR_REPO}/${SERVICE}"           # ex.: AR_REPO=us-central1-docker.pkg.dev/proj/repo
else
  # lista em JSON e escolhe um repositório DOCKER (de preferência na mesma região); o campo name pode vir curto ou completo
  REPO_JSON=$(gcloud artifacts repositories list --project "$PROJECT" --format=json 2>/dev/null || echo "[]")
  REPO_PICK=$(REGION="$REGION" python3 -c '
import json, os, sys
repos = json.loads(sys.stdin.read() or "[]")
cands = []
for r in repos:
    if str(r.get("format", "DOCKER")).upper() != "DOCKER":
        continue
    parts = str(r.get("name", "")).split("/")
    loc = parts[3] if len(parts) >= 6 else str(r.get("location", ""))
    repo = parts[5] if len(parts) >= 6 else parts[-1]
    if loc and repo:
        cands.append((0 if loc == os.environ["REGION"] else 1, loc, repo))
if cands:
    _, loc, repo = sorted(cands)[0]
    print(loc, repo)
' <<< "$REPO_JSON" 2>/dev/null || true)
  if [ -n "$REPO_PICK" ]; then
    REPO_LOC=${REPO_PICK%% *}; REPO_NAME=${REPO_PICK##* }
    IMAGE_FLAG="--image=${REPO_LOC}-docker.pkg.dev/${PROJECT}/${REPO_NAME}/${SERVICE}"
    echo ">> repositório de imagens existente: ${REPO_LOC}-docker.pkg.dev/${PROJECT}/${REPO_NAME}"
  else
    echo "!! nenhum repositório Docker no Artifact Registry e sua conta não pode criar um. Peça a quem tem permissão (owner do projeto /"
    echo "   organização do evento) para rodar UMA vez:"
    echo "   gcloud artifacts repositories create cloud-run-source-deploy --repository-format=docker --location=$REGION --project=$PROJECT"
    echo "   Depois rode ./infra/deploy_app.sh de novo (ou AR_REPO=<loc>-docker.pkg.dev/$PROJECT/<repo> ./infra/deploy_app.sh)."
    exit 1
  fi
fi

# Identidade de runtime (para a dica de operador no /chat/stream apontar o comando exato de IAM)
if [ -n "$SA_FLAG" ]; then RUNTIME_SA="$SA"; else
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || echo "")
  RUNTIME_SA="${PROJECT_NUMBER:-PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

ENV_VARS="GOOGLE_GENAI_USE_VERTEXAI=1,GOOGLE_GENAI_USE_ENTERPRISE=1,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$LOCATION,ZERA_MODEL=$MODEL,ZERA_FONTE=$FONTE,ZERA_ESTADO=$ESTADO,ZERA_STRICT_NUMEROS=1,ZERA_HOJE=2026-09-26,ZERA_VERSAO=$VERSAO,ZERA_OTEL_GCP=$OTEL,ZERA_TELEMETRIA_BQ=$TELEMETRIA_BQ,ZERA_LOG_JSON=1,ZERA_LOG_LEVEL=INFO,ZERA_MODEL_ARMOR=${ZERA_MODEL_ARMOR:-0},ZERA_DOCS=0,ZERA_RUNTIME_SA=$RUNTIME_SA"

# Plano B para o Gemini quando a identidade de runtime não tem roles/aiplatform.user e ninguém do time pode conceder:
# chave de API do Vertex AI (modo express) — autentica o projeto, não uma identidade. Preferir Secret Manager; a variável
# de ambiente fica visível para quem tem run.viewer no projeto (aceitável só para a demo, com a chave restrita ao alvo aiplatform).
SECRET_FLAG=""
if [ -n "${ZERA_GEMINI_API_KEY_SECRET:-}" ]; then
  SECRET_FLAG="--set-secrets=ZERA_GEMINI_API_KEY=${ZERA_GEMINI_API_KEY_SECRET}:latest"
  ENV_VARS="$ENV_VARS,ZERA_GEMINI_API_KEY_MODO=${ZERA_GEMINI_API_KEY_MODO:-vertex}"
  echo ">> Gemini via chave de API (Secret Manager: $ZERA_GEMINI_API_KEY_SECRET, modo ${ZERA_GEMINI_API_KEY_MODO:-vertex})"
elif [ -n "${ZERA_GEMINI_API_KEY:-}" ]; then
  ENV_VARS="$ENV_VARS,ZERA_GEMINI_API_KEY=${ZERA_GEMINI_API_KEY},ZERA_GEMINI_API_KEY_MODO=${ZERA_GEMINI_API_KEY_MODO:-vertex}"
  echo "!! Gemini via chave de API em VARIÁVEL DE AMBIENTE do serviço (modo ${ZERA_GEMINI_API_KEY_MODO:-vertex}) — só para a demo; prefira ZERA_GEMINI_API_KEY_SECRET"
fi

gcloud run deploy "$SERVICE" \
  --source . $IMAGE_FLAG --region "$REGION" --allow-unauthenticated $SA_FLAG $SECRET_FLAG \
  --min-instances 1 --max-instances 1 --concurrency 40 --memory 1Gi --cpu 1 --timeout 300 --cpu-boost \
  --labels "app=zera,versao=$VERSAO" \
  --set-env-vars "$ENV_VARS"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "UI + API no ar: $URL   (fonte=$FONTE estado=$ESTADO otel=$OTEL versão=$VERSAO)"
# Acesso público pode ser barrado por política da organização (allUsers). Se /health responder 403, o serviço está no ar mas
# privado: use o proxy autenticado para a demo ou dê run.invoker para as contas do time.
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' "$URL/health" || echo 000)
if [ "$CODIGO" = "403" ]; then
  echo "!! serviço no ar, mas o acesso público (allUsers) foi negado pela política do projeto. Alternativas:"
  echo "   1) demo pela sua máquina: gcloud run services proxy $SERVICE --region $REGION --port 8080   -> http://localhost:8080"
  echo "   2) liberar contas do time: gcloud run services add-iam-policy-binding $SERVICE --region $REGION --member='user:EMAIL' --role='roles/run.invoker'"
  echo "      e abrir com token: curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/health"
else
  echo "health HTTP $CODIGO"
  # Sonda do Gemini: 1 turno que exige o modelo. Se a identidade de runtime não tiver roles/aiplatform.user, a linha "erro" traz
  # a dica com o comando exato para o admin (ou o plano B com chave de API).
  CID=$(curl -s "$URL/v1/clientes" | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d.get("perfis", d) if isinstance(d, dict) else d; print(d[0]["cliente_id"])' 2>/dev/null || echo "")
  if [ -n "$CID" ]; then
    SONDA=$(curl -s -m 60 -X POST "$URL/chat/stream" -H 'Content-Type: application/json' -d "{\"cliente_id\":\"$CID\",\"sessao_id\":\"deploy-$VERSAO\",\"mensagem\":\"Quais opções cabem no meu bolso?\"}" || echo "")
    if echo "$SONDA" | grep -q '"tipo": "erro"'; then
      echo "!! Gemini NÃO respondeu em produção:"
      echo "$SONDA" | grep '"tipo": "erro"' | python3 -c 'import json,sys; d=json.loads(sys.stdin.readline()); print("   erro:", d.get("erro","")[:160]); print("   dica:", d.get("dica",""))' 2>/dev/null || echo "$SONDA" | head -c 400
      echo "   ver infra/producao.md §1c (admin: roles/aiplatform.user para $RUNTIME_SA | sem admin: ZERA_GEMINI_API_KEY_SECRET)"
    else
      echo "Gemini respondeu em produção (sonda /chat/stream ok)"
    fi
  fi
fi
echo "smoke completo (health, ready, perfis, chat com Gemini, botão Contratar + HITL): infra/smoke_prod.sh $URL"
echo "logs:  gcloud run services logs read $SERVICE --region $REGION --limit 50"
echo "rollback: gcloud run services update-traffic $SERVICE --region $REGION --to-revisions=<revisao-anterior>=100"
echo "observabilidade (métricas de log, alertas, orçamento): infra/observabilidade.sh"
