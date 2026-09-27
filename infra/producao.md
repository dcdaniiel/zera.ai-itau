# zera.ai em produção (GCP, projeto `batalha-time-03-vhxk`)

Um serviço no **Cloud Run** (`zera`, `us-central1`) com API FastAPI + agente ADK (Gemini 3.8 Flash via Vertex AI, endpoint `global`) + UI
(Vite build servido pela própria API). Dados no **BigQuery** (`zera.*`, k-means BigQuery ML). Observabilidade no backend: Cloud Trace,
Cloud Monitoring, Cloud Logging (logs JSON), `zera.telemetria`. Tudo com serviços já habilitados no projeto.

## 0. Pré-requisitos (na sua máquina, uma vez)

```bash
gcloud auth login && gcloud auth application-default login
gcloud config set project batalha-time-03-vhxk
cd ~/Desktop/DEV/zera.ai-itau && git pull && uv sync
```

## 1. Dados (BigQuery) — 1 comando, idempotente

```bash
uv run python -m dados.publicar_bq       # zera.extrato (partição/cluster) → features → perfil_cliente → dividas_derivadas
                                         # → k-means (zera.kmeans_perfis) → clusters_clientes → perfil_clusters → perfis_demo
                                         # → estado_cliente / eventos / telemetria; imprime os perfis do cluster-alvo
```
Verificação: `bq query --use_legacy_sql=false 'SELECT nome, renda_media, meses_com_renda, qtd_dividas FROM `batalha-time-03-vhxk.zera.perfis_demo` ORDER BY ordem'`
— os perfis precisam ter `renda_media > 0` (renda = média mensal das entradas do histórico).

Se algum SQL falhar: me mande a mensagem (o SQL foi validado por parser, nunca executado antes). **O deploy não depende disso**:
sem `zera.perfis_demo` o script sobe com `ZERA_FONTE=amostra` (40 clientes reais, 12 meses, embarcados na imagem) e estado em JSON.

## 1b. Permissões no projeto do evento (o que descobrimos)

A conta pessoal tem BigQuery, Cloud Build, Cloud Run e Artifact Registry (leitura) — mas **não** pode criar service account,
repositório no Artifact Registry nem alterar IAM. A identidade de runtime do Cloud Run (`27813124245-compute@…`) **não tem**
`bigquery.jobs.create`. O deploy contorna tudo isso sem intervenção de admin:

- service account: usa a identidade padrão do Cloud Run;
- repositório de imagens: reaproveita o que já existe no Artifact Registry (`--image`);
- dados: exporta, com a sua credencial, o resultado do BigQuery ML para `dados/snapshot_bq/` (embarcado na imagem); em runtime a API
  tenta o BigQuery e, ao receber 403, usa o snapshot automaticamente — a fonte aparece como `bigquery_snapshot (<hora da exportação>)`;
- estado: `ZERA_ESTADO=bigquery` cai para JSON local se a gravação for recusada (1 instância, então consistente).

**Ao vivo sem Owner:** o dono do dataset `zera` (você) pode dar acesso de dataset à conta de runtime — isso basta para a API ler
`zera.*` direto das tabelas (`tabledata.list`, sem job) e gravar estado/eventos/telemetria por streaming insert:

```bash
uv run python infra/conceder_dataset.py 27813124245-compute@developer.gserviceaccount.com
```
Ordem de tentativa em runtime: query (jobs) → leitura direta das tabelas (dataset) → snapshot embarcado. `/health` mostra qual está ativa.
Se um admin conceder `roles/bigquery.jobUser` + `roles/bigquery.dataEditor` à conta compute, a query volta a ser usada sem redeploy.

## 1c. Gemini em produção: `403 aiplatform.endpoints.predict` (a identidade de runtime não tem `roles/aiplatform.user`)

Sintoma: `/chat/stream` devolve `{"tipo":"erro", "erro":"403 PERMISSION_DENIED … Permission 'aiplatform.endpoints.predict' denied …",
"dica":"…"}`, a cliente vê "Não consegui responder agora. Nenhum valor foi inventado…" e o log traz `Root node zera failed` /
`chat_stream falhou`. Tudo o que não usa o modelo (experiência guiada, perfis, proatividade, botão Contratar + HITL) segue funcionando.
Causa: a conta padrão do Cloud Run (`27813124245-compute@developer.gserviceaccount.com`) não tem papéis no projeto do evento e a
sua conta não pode conceder (`setIamPolicy` negado). Duas saídas:

**A) Correção definitiva — 1 comando por um admin/organizador do projeto (vale em 1–2 min, sem redeploy):**
```bash
gcloud projects add-iam-policy-binding batalha-time-03-vhxk \
  --member=serviceAccount:27813124245-compute@developer.gserviceaccount.com --role=roles/aiplatform.user
# no mesmo pedido, se possível (BigQuery ao vivo sem os fallbacks): --role=roles/bigquery.jobUser e --role=roles/bigquery.dataEditor
```

**B) Sem admin — chave de API do Vertex AI (modo express).** A chave autentica o *projeto*, não uma identidade, então não passa pelo
IAM da conta de runtime. Na sua máquina (precisa de `serviceusage.apiKeys.create`; se for negado, resta o caminho A ou uma chave do
AI Studio com `ZERA_GEMINI_API_KEY_MODO=developer`):
```bash
gcloud services api-keys create --project batalha-time-03-vhxk --display-name zera-vertex \
  --api-target=service=aiplatform.googleapis.com --format='value(response.keyString)'   # imprime a chave UMA vez
# recomendado: Secret Manager (a chave não fica visível no serviço)
printf '%s' 'AIza…' | gcloud secrets create zera-gemini-key --data-file=- --project batalha-time-03-vhxk
gcloud secrets add-iam-policy-binding zera-gemini-key --member=serviceAccount:27813124245-compute@developer.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor --project batalha-time-03-vhxk
ZERA_GEMINI_API_KEY_SECRET=zera-gemini-key ./infra/deploy_app.sh
# se o Secret Manager também for negado (só para a demo; a chave restrita ao alvo aiplatform fica visível a quem tem run.viewer):
ZERA_GEMINI_API_KEY='AIza…' ./infra/deploy_app.sh
```
O agente passa a chave explicitamente ao cliente do SDK (`zera_agent/agent.py::modelo`) — vinda só do ambiente, `GOOGLE_CLOUD_PROJECT`/
`LOCATION` teriam precedência sobre ela. `/health` mostra `llm_auth: adc | api_key:vertex | api_key:developer`. O deploy termina com uma
sonda no `/chat/stream` e imprime a dica exata se o Gemini ainda não responder. Para voltar ao padrão (depois do caminho A), rode o
deploy sem as variáveis.

**Cloud Trace:** a Org Policy do projeto bloqueia `cloudtrace.googleapis.com` (`Request is disallowed by organization's Org Policy`), e os
exportadores OTel devolviam `Failed to export … 400` a cada 6 s. Por isso `ZERA_OTEL_GCP` fica **0** por padrão neste projeto (logs JSON,
`/metrics` e `zera.telemetria` continuam); com `=1`, cada mensagem de erro do exportador é registrada uma vez e as repetições são suprimidas.

## 2. Deploy

```bash
infra/setup_gcp.sh        # opcional: template Model Armor (ZERA_MODEL_ARMOR=1 no deploy liga a sanitização)
infra/deploy_app.sh       # APIs, service account zera-run com IAM mínimo, Cloud Build (Dockerfile multi-stage), Cloud Run
```
Leva ~6–8 min (build do Node + Python). No fim imprime a URL. Variáveis opcionais: `ZERA_FONTE=amostra`, `ZERA_ESTADO=json`,
`ZERA_OTEL_GCP=0`, `ZERA_MODEL=gemini-2.5-flash` (fallback estável), `ZERA_MODEL_ARMOR=1`.

O que o deploy configura:

| Item | Valor |
|---|---|
| Instâncias | min 1 / **max 1** (sessões do ADK e cache em processo; sem split-brain), concurrency 40, 1 vCPU / 1 GiB, cpu-boost, timeout 300 s |
| Modelo | `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_LOCATION=global`, `ZERA_MODEL=gemini-3.8-flash` (credencial = service account, sem chave) |
| Dados/estado | `ZERA_FONTE=bigquery` (+ snapshot embarcado como fallback automático), `ZERA_ESTADO=bigquery` (cai para JSON se recusado), `ZERA_TELEMETRIA_BQ=1` |
| Guardrails | `ZERA_STRICT_NUMEROS=1` (número fora das tools nunca chega à cliente), `ZERA_MODEL_ARMOR` opcional |
| Observabilidade | `ZERA_LOG_JSON=1` (Cloud Logging com request/trace id), `/metrics`, `zera.telemetria`; `ZERA_OTEL_GCP=0` por padrão neste projeto (Org Policy bloqueia o Cloud Trace — §1c); `=1` religa traces + métricas via telemetry.googleapis.com |
| Segurança | container sem privilégio (uid 10001), `ZERA_DOCS=0`, sem segredos em env, SA `zera-run` com papéis mínimos: `aiplatform.user`, `bigquery.dataEditor`, `bigquery.jobUser`, `logging.logWriter`, `monitoring.metricWriter`, `cloudtrace.agent`, `telemetry.tracesWriter`, `telemetry.metricsWriter`, `modelarmor.user` |
| Acesso | `--allow-unauthenticated` (demo pública para a banca); a UI é servida na mesma origem (sem CORS aberto necessário) |

## 3. Validar (obrigatório antes de apresentar)

```bash
infra/smoke_prod.sh https://zera-XXXX-uc.a.run.app
```
Checa: `/health`, `/ready` (fonte responde), perfis reais, proatividade, experiência guiada (0 tokens), **chat com Gemini** (tools + card),
**botão Contratar → card HITL → recusa** (nada contratado) e reset. Se o passo 4 falhar, a linha `erro` traz a dica
(credencial da SA, modelo/location, cota).

## 4. Observabilidade / FinOps

```bash
infra/observabilidade.sh   # métricas de log (5xx, chamadas LLM, transições, acordos, nenhuma opção, guardrails), alerta 5xx, orçamento
```
Onde olhar: **Cloud Trace** (spans `invocation`, `agent_run`, `call_llm`, `execute_tool`, `motor.*`, `agente.turno`), **Monitoring**
(`workload.googleapis.com/zera.*`: `zera.hitl_pedido`, `zera.hitl_resposta`, `zera.chat_roteado`, `zera.evento`, `zera.llm.*`),
**Logs Explorer** (`jsonPayload.message in (http, chamada_llm, transicao, guardrail)`), **BigQuery** `zera.telemetria` / `zera.eventos`.
`GET /metrics` (p50/p95 por etapa, custo por jornada) fica no backend — nada disso aparece na interface.

## 5. Operação

- Logs: `gcloud run services logs read zera --region us-central1 --limit 100`
- Rollback: `gcloud run revisions list --service zera --region us-central1` → `gcloud run services update-traffic zera --region us-central1 --to-revisions=<anterior>=100`
- Redeploy: `infra/deploy_app.sh` (mesma URL; versão = hash do commit em `ZERA_VERSAO`/label)
- Reset de um perfil na demo: `curl -X POST $URL/reset/<cliente_id>` (apaga estado: acordos, consentimentos, gastos informados)

## Falhas conhecidas e o que fazer

| Sintoma | Causa | Ação |
|---|---|---|
| `/ready` 503 | tabelas `zera.*` ausentes ou SA sem `bigquery.jobUser` | rode `publicar_bq`; ou redeploy com `ZERA_FONTE=amostra ZERA_ESTADO=json` |
| chat devolve `erro` com "404 … model" | modelo não servido na location | `GOOGLE_CLOUD_LOCATION=global` (padrão) ou `ZERA_MODEL=gemini-2.5-flash` |
| chat devolve `erro` 403 | identidade de runtime sem `roles/aiplatform.user` | §1c: admin concede (1 comando) ou chave de API do Vertex (`ZERA_GEMINI_API_KEY_SECRET`) |
| traces não aparecem | Org Policy bloqueia `cloudtrace.googleapis.com` neste projeto (ou SA sem `telemetry.tracesWriter`) | esperado no evento; `ZERA_OTEL_GCP=0` (padrão) |
| conversa "esquece" ao recarregar | instância reiniciou (estado em JSON) | usar `ZERA_ESTADO=bigquery` (padrão com dados publicados) |
