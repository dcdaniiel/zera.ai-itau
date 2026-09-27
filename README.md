# zera.ai — renegociação que cabe no mês da cliente

Agente do Itaú (ADK + Gemini no Vertex AI) para a **Batalha de Agentes Itaú × Google**. A cliente entra no rotativo (gatilho),
recebe um convite discreto (se autorizou), confirma o orçamento, compara alternativas calculadas por um **motor determinístico**
e contrata só com confirmação explícita. Princípio **"ambos ganham"**: o banco não abre mão do saldo devedor — muda a taxa
(rotativo/cheque a 8–14% a.m. → taxa de renegociação) e o prazo (12x…60x); a parcela cai, a dívida ganha data para acabar e o
banco recebe o saldo integral + juros do acordo.

Docs: [`docs/PRD-MVP.md`](docs/PRD-MVP.md) · [`docs/arquitetura-c4.md`](docs/arquitetura-c4.md) (C4 + ADK graph + observabilidade/FinOps + uso dos serviços GCP) · [`docs/estrategia-dados.md`](docs/estrategia-dados.md)

```
motor/        núcleo determinístico: capacidade, priorização, cenários por prazo (entrada + consolidação), hoje×nova opção, benefícios/claims, Price, respiro, amortização, gatilhos
dados/        loader (BigQuery | amostra real | fixture), segmentação por regras, SQL (tabelas zera.*, clusterização k-means BigQuery ML), publicar_bq.py, amostra real exportada do BQ
zera_agent/   experiencia.py (máquina de estados + contrato estruturado + roteamento de intenção), agente ADK, tools, guardrails, contexto, observabilidade (OTel/logs/métricas/FinOps)
api/          FastAPI: /v1/clientes (perfis do BQ), experiência (spec v1), /chat/inicio + /chat/stream + /chat/confirmar (agente ADK com HITL nativo, NDJSON), /health /ready /metrics — serve a UI buildada
ui/           app mobile (React + Vite + Tailwind, paleta Itaú): perfis → onboarding → preferências → home (trigger) → experiência de 10 telas | conversa com o agente (cards, HITL, guardrails)
tests/        62 testes sem rede (motor, fluxo ponta a ponta, agente com HITL, API de chat, guardrails, dados); tests/fixtures = perfil sintético SÓ para testes
infra/        setup GCP (dados + Model Armor), deploy Cloud Run (produção), observabilidade/FinOps, Agent Engine
```

**Nenhum dado é mockado.** Os perfis vêm da base do evento (`hackathon_dados.extrato_sintetico`): no GCP, pelo cluster-alvo do
k-means (BigQuery ML → `zera.perfis_demo`); local, pela amostra real exportada do BigQuery (`dados/amostra_bq_extrato_sintetico.csv`)
com segmentação por regras. O cliente mais típico do segmento recebe o nome da persona do produto ("Cleide"); os demais, pseudônimos
determinísticos (identidade fictícia). Dívidas inferidas do extrato ficam rotuladas "estimado do extrato". **Renda = média mensal das
entradas (tipo `E`) do histórico** do cliente (12 meses), com a fonte sempre exibida; quando o histórico não traz nenhuma entrada, o motor
**não calcula** sobra/parcela/cenários (dados insuficientes): a zera.ai pergunta, a cliente informa (`informar_renda`, no chat ou na
experiência guiada) e tudo é recalculado com o valor dito por ela — nunca inventa.

> **Amostra local:** `dados/amostra_bq_extrato_sintetico.csv` atual veio de um `LIMIT 10000` ordenado por descrição — só saídas de
> jan/2025, sem entradas —, então todo perfil aparece com "renda não identificada" e a proatividade fica em silêncio até a renda ser
> informada. Gere uma amostra completa (12 meses, entradas e saídas, 40 clientes do segmento) com
> `bq query --project_id=batalha-time-03-vhxk --use_legacy_sql=false --format=csv --max_rows=2000000 "$(cat dados/sql/exportar_amostra.sql)" > dados/amostra_bq_extrato_sintetico.csv`
> e reinicie a API. Em `ZERA_FONTE=bigquery` a renda já vem do histórico completo (`zera.perfil_cliente.renda_media`).

## Rodar local

```bash
pip install -r requirements.txt            # ou: uv sync
cp zera_agent/env.demo zera_agent/.env     # lido automaticamente (adk web, uvicorn, pytest); ZERA_FONTE=amostra roda sem credenciais | bigquery (após publicar_bq)
unset GOOGLE_CLOUD_LOCATION                # variável exportada no shell tem precedência sobre o .env (e o app avisa); gemini-3.x é servido em "global"
gcloud auth application-default login      # para o Gemini responder "por que essa opção?" e as perguntas livres
uv run pytest -q                           # 62 testes, sem rede (ou: pytest -q com o venv ativo)
uv run uvicorn api.main:app --reload --port 8080   # API (+ serve ui/dist se existir)
cd ui && npm install && npm run dev        # http://localhost:5173 — /api vai para :8080
```

Demo local: `http://localhost:5173` → escolha um perfil (amostra real) → onboarding → preferências (`avisar` = permissão de
proatividade) → home com o balão "Diminua suas parcelas" no botão flutuante (só se todas as pré-condições passarem) → experiência.
Botão azul (frasco) = controles da demo (trocar perfil, avançar o relógio para dez/26 — 13º entra — ou jan/27 — mês fraco —, reiniciar)
e o painel FinOps (chamadas, tokens e custo estimado do LLM).

**Conversa com o agente (ADK + HITL):** sem balão na home (cliente sem gatilho, ou balão dispensado), o botão flutuante abre a conversa;
na experiência guiada, o link "Conversar" faz o mesmo. A abertura é determinística (contexto + 3 proteções + sugestões de próximo passo);
cada mensagem vai para o agente ADK via `/chat/stream` e a tela mostra, conforme acontecem, os chips de tool (`informar_renda` /
`informar_gasto_fixo` quando você diz um valor), os cards do motor
(raio-X, capacidade, prioridades, cenários com "Quero esta", planos, acordo), o texto, o selo de guardrail e o custo do turno.
Contratar/respiro/amortizar disparam o **card HITL** (`adk_request_confirmation`): a tool só executa depois de "Confirmar" no app
(`/chat/confirmar`), com o consentimento registrado (`canal=hitl_app` + frase). A conversa exige `gcloud auth application-default login`
(Gemini via Vertex AI); a experiência guiada roda sem LLM.

Sem `gcloud auth application-default login` tudo funciona menos o LLM: "por que" cai nos critérios determinísticos e as perguntas
livres recebem orientação com ações — nunca um beco sem saída.

## Dados no BigQuery (produção da demo)

```bash
gcloud auth application-default login && gcloud config set project batalha-time-03-vhxk
python -m dados.publicar_bq                # cria zera.extrato (partição/cluster), features, perfil_cliente, dividas_derivadas,
                                           # k-means (zera.kmeans_perfis), clusters_clientes, perfil_clusters, perfis_demo,
                                           # estado_cliente, eventos, telemetria — e imprime os perfis do cluster-alvo
ZERA_FONTE=bigquery ZERA_ESTADO=bigquery uvicorn api.main:app --port 8080
```
Sem Python na máquina: `python -m dados.publicar_bq --imprimir` mostra o SQL renderizado para colar no console do BigQuery (Cloud Shell).

## Deploy em produção (um serviço no Cloud Run: API + agente + UI)

```bash
gcloud auth login && gcloud config set project batalha-time-03-vhxk
python -m dados.publicar_bq                # 1x (dados + clusterização)
infra/setup_gcp.sh                         # opcional: Model Armor template
infra/deploy_app.sh                        # Cloud Build (Dockerfile multi-stage) + Cloud Run + service account com IAM mínimo; imprime a URL
infra/observabilidade.sh                   # métricas de log, alerta 5xx, orçamento de billing
curl -s $URL/health; curl -s $URL/ready; curl -s $URL/metrics
```
O deploy sobe com `ZERA_FONTE=bigquery ZERA_ESTADO=bigquery ZERA_OTEL_GCP=1 ZERA_TELEMETRIA_BQ=1 ZERA_LOG_JSON=1`:
traces/métricas OTel do ADK (invocation, agent, call_llm, execute_tool) e do motor vão para `telemetry.googleapis.com`
(Cloud Trace / Monitoring), logs JSON estruturados para o Cloud Logging, custo por chamada/jornada para `zera.telemetria`.

## Números da persona (perfil mais típico do segmento, com renda informada de ~R$ 2.325)

Hoje: R$ 900/mês em 3 pagamentos, saldo devedor R$ 6.800, R$ 641/mês só de juros, sem prazo. Recomendada: 48x R$ 212,77
(total R$ 10.213 = R$ 6.800 + R$ 3.413 de juros a 1,8% a.m.); alternativas 36x R$ 258 (menor custo) e 60x R$ 186 (menor parcela).
Com o 13º (R$ 2.800): quita o cheque especial, abate R$ 1.784 do cartão e renegocia o resto em 24x R$ 212,73 (total R$ 7.789).
Gasto extra informado de R$ 80/mês muda a recomendação para 60x; R$ 300/mês → "nenhuma opção cabe" com diagnóstico e caminhos.
