#!/usr/bin/env bash
# Gemini em produção SEM admin de IAM (infra/producao.md §1c): chave de API do Vertex AI (modo express), guardada no
# Secret Manager e injetada no Cloud Run como ZERA_GEMINI_API_KEY. Idempotente. A chave nunca é impressa no terminal.
#   ./infra/gemini_api_key.sh                         # cria/reaproveita a chave, grava no segredo, libera a conta de runtime, faz o deploy
#   MODO=developer CHAVE='AIza…' ./infra/gemini_api_key.sh   # alternativa: chave do AI Studio (Gemini Developer API) já em mãos
# Variáveis: SECRET (zera-gemini-key), KEY_DISPLAY (zera-vertex), RUNTIME_SA (conta compute do projeto), MODO (vertex|developer)
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${GOOGLE_CLOUD_PROJECT:-batalha-time-03-vhxk}"
SECRET="${SECRET:-zera-gemini-key}"
KEY_DISPLAY="${KEY_DISPLAY:-zera-vertex}"
MODO="${MODO:-vertex}"
gcloud config set project "$PROJECT" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
RUNTIME_SA="${RUNTIME_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
gcloud services enable apikeys.googleapis.com secretmanager.googleapis.com >/dev/null 2>&1 || true

# 1) chave de API (fica só em memória deste shell)
if [ -n "${CHAVE:-}" ]; then
  echo ">> usando a chave informada em CHAVE (modo $MODO)"
else
  NOME=$(gcloud services api-keys list --filter="displayName=$KEY_DISPLAY" --format='value(name)' 2>/dev/null | head -1 || true)
  if [ -z "$NOME" ]; then
    echo ">> criando a chave de API '$KEY_DISPLAY' restrita ao Vertex AI (aiplatform.googleapis.com)"
    NOME=$(gcloud services api-keys create --display-name "$KEY_DISPLAY" --api-target=service=aiplatform.googleapis.com \
             --format='value(response.name)' 2>/dev/null || true)
    [ -n "$NOME" ] || NOME=$(gcloud services api-keys list --filter="displayName=$KEY_DISPLAY" --format='value(name)' 2>/dev/null | head -1 || true)
  else
    echo ">> reaproveitando a chave de API '$KEY_DISPLAY'"
  fi
  if [ -z "$NOME" ]; then
    echo "!! não consegui criar nem achar a chave de API (serviceusage.apiKeys.create negado?)."
    echo "   Alternativa imediata: chave do Google AI Studio (aistudio.google.com/apikey) ->  MODO=developer CHAVE='AIza…' $0"
    exit 1
  fi
  CHAVE=$(gcloud services api-keys get-key-string "$NOME" --format='value(keyString)' | tr -d '\n')
  [ -n "$CHAVE" ] || { echo "!! get-key-string devolveu vazio para $NOME"; exit 1; }
fi

# 2) Secret Manager (cria ou adiciona versão) — a chave entra por pipe, sem passar por argumento nem histórico
if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  printf '%s' "$CHAVE" | gcloud secrets versions add "$SECRET" --data-file=- >/dev/null && echo ">> nova versão do segredo $SECRET"
else
  printf '%s' "$CHAVE" | gcloud secrets create "$SECRET" --data-file=- --replication-policy=automatic >/dev/null && echo ">> segredo $SECRET criado"
fi

# 3) a conta de runtime do Cloud Run precisa ler o segredo; sem permissão para isso, sobe com a chave como variável do serviço (só demo)
if gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null 2>&1; then
  echo ">> $RUNTIME_SA pode ler o segredo — deploy com --set-secrets"
  ZERA_GEMINI_API_KEY_SECRET="$SECRET" ZERA_GEMINI_API_KEY_MODO="$MODO" ./infra/deploy_app.sh
else
  echo "!! sem permissão para liberar o segredo à conta de runtime (secretmanager.secrets.setIamPolicy) — deploy com a chave como variável do serviço"
  ZERA_GEMINI_API_KEY="$CHAVE" ZERA_GEMINI_API_KEY_MODO="$MODO" ./infra/deploy_app.sh
fi
