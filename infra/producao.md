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
| Dados/estado | `ZERA_FONTE=bigquery`, `ZERA_ESTADO=bigquery`, `ZERA_TELEMETRIA_BQ=1` (ou amostra/json/0 no fallback) |
| Guardrails | `ZERA_STRICT_NUMEROS=1` (número fora das tools nunca chega à cliente), `ZERA_MODEL_ARMOR` opcional |
| Observabilidade | `ZERA_OTEL_GCP=1` (traces + métricas do ADK e do motor → telemetry.googleapis.com), `ZERA_LOG_JSON=1` (Cloud Logging com trace id) |
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
| chat devolve `erro` 403 | SA sem `roles/aiplatform.user` | peça ao admin do projeto (o script tenta conceder) |
| traces não aparecem | SA sem `telemetry.tracesWriter` | conceder o papel ou `ZERA_OTEL_GCP=0` |
| conversa "esquece" ao recarregar | instância reiniciou (estado em JSON) | usar `ZERA_ESTADO=bigquery` (padrão com dados publicados) |
