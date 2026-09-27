# zera.ai — Desenho de solução (C4 Model, ADK graph, dados & ciência de dados, observabilidade/FinOps, GCP)

Projeto `batalha-time-03-vhxk` · Cloud Run em `us-central1` · Gemini via endpoint `global` · BigQuery na location do dataset do evento.
Versão de trabalho para a submissão — Batalha de Agentes Itaú × Google (26–27/09/2026). Quadro de produto: `docs/quadro-produto.md` (tese, outcomes, guardrails).
Leitura recomendada antes deste arquivo: [`arquitetura-explicativa.md`](arquitetura-explicativa.md) (componentes, integrações, decisões e justificativas — entregável 5) e
[`arquitetura-c4-apresentacao.html`](arquitetura-c4-apresentacao.html) (níveis 1 e 2 desenhados para apresentar, com as decisões).

## 0. Princípios que atravessam todos os níveis

| Princípio | Como aparece na arquitetura |
|---|---|
| **Núcleo determinístico manda** | Todo número, elegibilidade, comparação, termo e contratação nasce em `motor/` (Python puro, 100% testado). O LLM interpreta intenção, explica e responde — nunca calcula, nunca decide o fluxo. |
| **Ambos ganham** | O banco não abre mão do saldo devedor: muda taxa (rotativo/cheque 8–14% a.m. → 1,8% a.m.) e prazo (12–60x). Cliente: parcela menor, data para acabar, nome limpo. Banco: saldo integral + juros do acordo, em vez de dívida em atraso caminhando para provisão. |
| **Nenhum dado mockado** | Perfis vêm da base do evento (`hackathon_dados.extrato_sintetico`): cluster-alvo por k-means (BigQuery ML) ou segmentação por regras na amostra exportada. Dívidas inferidas ficam rotuladas "estimado do extrato". Renda ausente → a zera.ai pergunta. |
| **Consentimento e autonomia** | Preferências (proatividade, Open Finance), pré-condições de proatividade, só a ação `CONFIRM` contrata, pausa/recusa/escalonamento sempre disponíveis, LGPD (revogar). |
| **Guardrails RAI em três camadas** | Entrada (bloqueia sem chamar o modelo) → modelo → saída (bloqueia/redige; números conferidos com o motor) + Model Armor + consentimento por tool. |
| **Observável e com custo conhecido** | Toda etapa emite span, métrica e log estruturado; cada chamada ao Gemini registra tokens e custo; custo por jornada é uma métrica de produto. |
| **Sem beco sem saída** | Todo estado × ação tem transição definida (teste de matriz); texto livre é roteado antes do LLM; "nenhuma opção" traz diagnóstico e caminhos. |

---

## 1. Nível 1 — Contexto do sistema

```mermaid
C4Context
  title zera.ai — contexto
  Person(cliente, "Cliente Itaú", "Entrou no rotativo / tem atraso. Decide e autoriza toda ação financeira.")
  Person(humano, "Atendimento humano", "Recebe escalonamentos (pedido da cliente, vulnerabilidade, nenhuma opção, falha).")
  Person(negocio, "Produto, Crédito e Dados", "Definem catálogo/condições (politicas.py), acompanham funil, cumprimento, custo por jornada.")
  System(zera, "zera.ai", "Detecta o gatilho, calcula opções que cabem no mês, explica, contrata só com confirmação e acompanha o acordo.")
  System_Ext(app, "App Itaú (home)", "Onboarding, preferências (consentimento), balão proativo, botão flutuante.")
  System_Ext(bq, "BigQuery", "Extrato do evento → camada zera.* (features, perfis, clusters, dívidas derivadas, estado, eventos, telemetria).")
  System_Ext(vertex, "Vertex AI", "Gemini 3.8 Flash (endpoint global) · Agent Engine (sessões, P1) · Model Armor.")
  System_Ext(obs, "Cloud Observability", "Cloud Trace / Monitoring / Logging via Telemetry API (OTLP) + métricas de log + orçamento de billing.")
  System_Ext(tx, "Sistemas transacionais", "Contratação, débito automático, boleto (simulados no MVP).")
  Rel(cliente, app, "usa")
  Rel(app, zera, "abre a experiência / recebe PROACTIVE_MESSAGE", "HTTPS/JSON")
  Rel(zera, bq, "1 leitura de perfil por sessão; grava estado, eventos e telemetria", "BigQuery API")
  Rel(zera, vertex, "explicar / responder (atrás dos guardrails)", "Vertex AI, location global")
  Rel(zera, obs, "spans, métricas, logs, custo", "OTLP + stdout JSON")
  Rel(zera, tx, "contratação só após CONFIRM", "API (mock no MVP)")
  Rel(zera, humano, "escala com protocolo")
  Rel(negocio, bq, "Looker Studio / SQL sobre eventos e telemetria")
```

## 2. Nível 2 — Containers

```mermaid
C4Container
  title zera.ai — containers (um serviço no Cloud Run + BigQuery + Vertex AI + Observability)
  Person(cliente, "Cliente")
  System_Boundary(run, "Cloud Run · serviço zera (Docker multi-stage, SA zera-run com IAM mínimo)") {
    Container(ui, "App mobile (UI)", "React 19 · Vite 8 · Tailwind 4", "Perfis → onboarding → preferências → home (trigger) → experiência de 10 telas; renderiza por response_type; sem mock.")
    Container(api, "API", "FastAPI · Python 3.12 · uvicorn", "/v1/clientes · /perfil · /preferencias · /proativa · /experiencia(/evento) · /chat · /health /ready /metrics. Middleware: request id, latência, logs JSON.")
    Container(exp, "Orquestrador da experiência", "zera_agent/experiencia.py", "Máquina de estados + decision engine + roteamento determinístico de intenção + proatividade (7 pré-condições) + contrato estruturado.")
    Container(agent, "Agente ADK", "google-adk 2.10 · LlmAgent · Gemini 3.8 Flash", "Entende a intenção, conduz e explica; 16 tools (motor + conhecimento); HITL nativo; callbacks de guardrail; opcional multiagente (diagnóstico/negociador/acompanhamento).")
    Container(rag, "Base de conhecimento (RAG leve)", "conhecimento/ · busca lexical, sem vector store", "Política de renegociação, FAQ e glossário; consultar_conhecimento devolve até 3 trechos como evidência (nunca números); texto com cara de instrução é filtrado.")
    Container(motor, "Núcleo determinístico", "motor/ · Python puro", "capacidade · priorização · cenários (entrada + consolidação 12–60x) · hoje×nova · benefícios/claims · termos/CET · acordo · respiro · amortização · gatilhos.")
    Container(ctx, "Contexto do cliente", "zera_agent/contexto.py", "Perfil + capacidade em memória; estado (acordo, consentimentos, gatilhos, preferências, compromissos, renda informada); relógio de simulação.")
    Container(obsv, "Observabilidade & FinOps", "zera_agent/observabilidade.py", "OTel (ADK + spans próprios) → Telemetry API; logs JSON; métricas p50/p95; tokens/custo por chamada e jornada; lote para zera.telemetria.")
  }
  ContainerDb(dados, "Camada de dados", "BigQuery · dataset zera", "extrato (partição+cluster) · features_mensais · features_cliente · kmeans_perfis · clusters_clientes · perfil_clusters · perfis_demo · perfil_cliente · dividas_derivadas · estado_cliente · eventos · telemetria")
  System_Ext(vertex, "Vertex AI", "Gemini (global) · Agent Engine Sessions (P1) · Model Armor")
  System_Ext(obs, "Cloud Trace / Monitoring / Logging", "Telemetry API (OTLP) · métricas de log · alertas · Billing Budgets")
  Rel(cliente, ui, "usa", "HTTPS")
  Rel(ui, api, "{acao, payload} → resposta estruturada", "JSON")
  Rel(api, exp, "evento(acao, payload)")
  Rel(exp, motor, "situacao_hoje · montar_cenarios · validar_beneficios · termos · criar_acordo_de_cenario")
  Rel(exp, agent, "explicador(pergunta com FATOS, numeros_permitidos) — só EXPLAINING / ASK_QUESTION")
  Rel(agent, motor, "function tools")
  Rel(agent, rag, "consultar_conhecimento")
  Rel(agent, vertex, "generate_content · Model Armor sanitize")
  Rel(exp, ctx, "lê/grava estado")
  Rel(ctx, dados, "carregar_perfil (1 query) · estado/eventos append-only")
  Rel(api, obsv, "medir() · registrar_metrica() · registrar_llm()")
  Rel(obsv, obs, "OTLP traces/metrics · stdout JSON → Cloud Logging")
  Rel(obsv, dados, "zera.telemetria (lote)")
```

**Por que um serviço só**: a demo precisa de um deploy, uma URL e um custo previsível; o ADK roda embutido na API (Runner) e o
estado de conversa fica em memória (1 worker) ou no Agent Engine Sessions (`ZERA_SESSOES=vertex`) para produção com várias instâncias.

## 3. Nível 3 — Componentes

### 3a. Núcleo determinístico (`motor/`)

```mermaid
C4Component
  title motor/ — nenhuma função chama LLM; toda saída traz numeros_permitidos
  Container_Boundary(m, "motor/") {
    Component(pol, "politicas.py", "dict + carregar_politica", "Alavancas fictícias: percentil da sobra (25), colchão 5%, fator 0,75, respiros 2, taxa de renegociação 1,8% a.m., prazos 12/18/24/36/48/60, conforto 70% p/ renda irregular (CV ≥ 0,12), débito automático 2%, instituições renegociáveis.")
    Component(cap, "capacidade.py", "calcular_capacidade", "sobra[m] = renda − essenciais − compromissos; P25 − colchão → sobra segura → parcela máxima; meses fracos → respiros.")
    Component(pri, "priorizacao.py", "priorizar_dividas", "custo mensal (saldo × taxa) + peso da consequência (negativação) quando há atraso relevante.")
    Component(alo, "alocacao.py", "alocar_entrada · montar_cenarios", "Entrada: quita as mais caras que couberem, abate a mais cara restante. Um cenário por prazo: saldo consolidado integral à taxa de renegociação; viável se parcela+mantidas ≤ máxima e meses ruins ≤ respiros. Rótulos: recomendado (menor prazo com conforto), mais_barato, mais_folga, guardar_extra. Diagnóstico quando nada cabe (parcela disponível, entrada necessária).")
    Component(con, "consolidacao.py", "situacao_hoje · projecao_mesmo_prazo · resumo_cenario · termos", "Hoje sem 'total mágico': pagamentos, saldo devedor, juros/mês, sem prazo; projeção like-for-like por prazo; nova opção: total = saldo + juros; termos com CET, 1º/último vencimento, dívidas incluídas (fonte).")
    Component(ben, "beneficios.py", "validar_beneficios · claims · tradeoffs · criterio_recomendacao", "LOWER_MONTHLY_PAYMENT, LOWER_TOTAL_COST (mesmo prazo), LOWER_INTEREST_RATE, CLEAN_NAME, DEFINED_TERM, SINGLE_PAYMENT; trade-offs incluem o que o banco recebe.")
    Component(sim, "simulacao.py", "pmt · pv · cet_anual · simular_planos · criar_acordo_de_cenario · registrar_pagamento · acionar_respiro · amortizar · processar_vencimentos", "Price; acordo com componente por dívida; respiro sem mora; amortização 1:1 no componente mais pesado.")
    Component(gat, "gatilhos.py", "detectar_gatilhos", "entrada_rotativo > pre_negativacao (≥45 dias) > risco_parcela (D-3, sobra prevista < parcela) > dinheiro_extra (≥40% da renda mediana ou 13º/IRPF/FGTS/PLR).")
    Component(mod, "modelos.py", "dataclasses", "Divida (instituicao, fonte, rotativo), PerfilFinanceiro (renda_desconhecida, renda_informada, persona, fonte), Capacidade, Acordo; brl(); r2().")
  }
  Rel(alo, cap, "parcela máxima, colchão, respiros")
  Rel(alo, sim, "pmt / pv")
  Rel(con, sim, "CET, vencimentos")
  Rel(ben, con, "compara hoje × nova")
```

**Fórmulas** (todas em `motor/`, testadas em `tests/test_motor.py`):

- `parcela_maxima = 0,75 × max(0, P25(sobra) − 0,05 × renda_mediana)`; `parcela_conforto = 0,70 × parcela_maxima` se `CV(renda) ≥ 0,12`.
- `parcela(n) = Price(saldo_consolidado, 1,8%, n)`; `custo_total = entrada + n × parcela = saldo_original + juros_acordo`; `ganho_banco = juros_acordo`.
- Viável: `parcela + mantidas ≤ parcela_maxima` **e** `#meses com (sobra − colchão) < parcela ≤ respiros`.
- Hoje: `pagamento_mensal = Σ(parcela ou juros)`, `juros_mensais = Σ saldo × taxa`, `projecao(n) = Σ Price(saldo_i, taxa_i, n) × n` (comparação de custo total no mesmo prazo).
- Diagnóstico (nada cabe): `parcela_disponivel = min(parcela_maxima, (respiros+1)-ésima menor sobra líquida) − mantidas`; `entrada_necessaria = saldo − PV(parcela_disponivel, 1,8%, 60)`.

### 3b. Orquestração, agente, guardrails e observabilidade (`zera_agent/`)

```mermaid
C4Component
  title zera_agent/
  Container_Boundary(z, "zera_agent/") {
    Component(exp, "experiencia.py", "Experiencia", "Estados IDLE→…→COMPLETED | NO_SUITABLE_OPTION | ERROR; 19 ações; roteamento de intenção (regex pt-BR sem acento) antes do LLM; proatividade com 7 checks; contrato {state, response_type, content, options, quick_replies, allowed_actions, requires_confirmation, context, finops}.")
    Component(ctx, "contexto.py", "Contexto", "Perfil (loader), capacidade, estado (JSON | BigQuery append-only), compromissos e renda informados, roteiro do relógio (13º em dez/26, IRPF em mai/27), gatilhos.")
    Component(agent, "agent.py", "LlmAgent", "root 'zera' (Gemini 3.8 Flash, temperatura 0,2) · ZERA_MULTIAGENTE=1: sub-agentes diagnóstico/negociador/acompanhamento.")
    Component(tools, "tools.py", "16 function tools", "get_perfil_financeiro · informar_renda · informar_gasto_fixo (dados insuficientes: sem renda no histórico as tools de cálculo recusam e a cliente informa) · calcular_capacidade · priorizar_dividas · montar_cenarios · comparar_com_padrao · registrar_consentimento · revogar_consentimento · fechar_acordo · status_acordo · acionar_respiro · amortizar · listar_gatilhos · escalar_humano · consultar_conhecimento (RAG leve). HITL nativo: fechar_acordo, acionar_respiro e amortizar(aplicar) são FunctionTool(require_confirmation) — o ADK pausa e só executa com a confirmação humana (canal hitl_app registrado no consentimento).")
    Component(gr, "guardrails.py", "4 callbacks", "before_model: Model Armor + injeção/jailbreak, engenharia social, fora de escopo (resposta fixa, modelo não chamado), PII redigida, vulnerabilidade, contexto. before_tool: exigir_consentimento (recusa humana → tool não roda, bloqueios_consentimento++). after_tool: números permitidos. after_model: pressão, promessa, vazamento, PII, números fora das tools → [valor a confirmar].")
    Component(obsv, "observabilidade.py", "medir · registrar_metrica · registrar_llm · resumo", "OTel via ADK (telemetry.googleapis.com) ou OTLP genérico; logs JSON com trace id; histogramas p50/p95; custo por chamada/jornada; lote para zera.telemetria.")
    Component(pr, "prompts.py", "instruções", "Regras invioláveis: números só das tools; parcela ≤ máxima; confirmação explícita; sem cobrança; escalar em vulnerabilidade.")
    Component(kb, "conhecimento/ (RAG leve)", "busca.py + base/*.md", "Política de renegociação, FAQ, glossário; busca lexical top-3, chunks por parágrafo; trechos com cara de instrução removidos; nunca fonte de números.")
  }
  Rel(exp, ctx, "estado")
  Rel(exp, agent, "explicador(prompt com FATOS do estado)")
  Rel(agent, tools, "function calling")
  Rel(agent, gr, "callbacks")
  Rel(tools, ctx, "perfil, capacidade, acordo")
  Rel(tools, kb, "consultar_conhecimento")
  Rel(exp, obsv, "spans/métricas por etapa")
```

### 3c. Dados (`dados/`)

| Componente | Responsabilidade |
|---|---|
| `loader.py` | `ZERA_FONTE=bigquery` → `perfil_cliente` + `dividas_derivadas` + `perfis_demo` + `clusters_clientes` (1 query); se o runtime não puder consultar (IAM), cai para o snapshot exportado no deploy (`dados/exportar_snapshot_bq.py`, fonte rotulada `bigquery_snapshot`); fallback extrato bruto. `amostra` → export real (`amostra_bq_extrato_sintetico.csv`, gerado por `sql/exportar_amostra.sql`) + `segmentacao.py`. `fixture` → só testes. Renda = média mensal das entradas do histórico (`renda_media`, `meses_com_renda`, `renda_fonte`); sem entradas → `renda_desconhecida` → a experiência/agente perguntam. |
| `segmentacao.py` | Mesmas features do SQL em pandas; índice de endividamento; pseudônimos determinísticos (medoide = "Cleide"). |
| `sql/zera_tabelas.sql` | extrato (partição/cluster) → features_mensais → perfil_cliente → dividas_derivadas → estado/eventos/telemetria. |
| `sql/clusterizacao.sql` | features_cliente → `CREATE MODEL kmeans_perfis` (k-means++, features padronizadas) → `ML.PREDICT` → perfil_clusters (índice) → perfis_demo. |
| `publicar_bq.py` | Cria o dataset na location do evento e roda os dois scripts (idempotente); `--imprimir` para o console. |

### 3d. API (`api/main.py`)

| Rota | Uso | LLM? |
|---|---|---|
| `GET /health` `GET /ready` `GET /metrics` | liveness · readiness (fonte responde) · métricas/FinOps | não |
| `GET /v1/clientes` · `GET /v1/clientes/{id}/perfil` | perfis do cluster-alvo · perfil financeiro com fontes e capacidade | não |
| `GET/POST /v1/clientes/{id}/preferencias` | consentimento (proatividade, Open Finance) | não |
| `GET /v1/clientes/{id}/proativa` | PROACTIVE_MESSAGE ou `{silent, checks, reason}` | não |
| `GET /v1/clientes/{id}/experiencia` · `POST …/experiencia/evento` | resposta atual · ação → resposta estruturada | só ASK_WHY/ASK_QUESTION |
| `GET /chat/inicio` | abertura determinística da conversa: contexto (gatilho, renda desconhecida, acordo ativo), 3 proteções e sugestões (direcionamento) | não |
| `POST /chat` · `POST /chat/stream` | conversa com o agente ADK; o stream é NDJSON com um evento por linha: `llm` (tokens/custo) · `tool_call` · `tool_result` · `card` (raio_x, capacidade, prioridades, cenarios, planos, acordo, amortizacao) · `texto` · `hitl` · `guardrail` · `fim` (sugestões, FinOps, acordo) | sim |
| `POST /chat/contratar` | botão "Contratar" do card de cenários: gatilho determinístico — valida o cenário na sessão e devolve o card HITL (`request_id` `btn_…`) com os números do motor | não |
| `POST /chat/confirmar` · `POST /chat/confirmar/stream` | HITL: `request_id` do ADK → devolve a decisão humana como `FunctionResponse(adk_request_confirmation)` e a tool pausada executa (ou é recusada); `request_id` `btn_…` → o motor executa direto (consentimento `canal=botao_app`) e a mesma sequência de eventos é emitida | só na via do ADK |
| `POST /simular_tempo` · `GET /gatilhos/{id}` · `POST /reset/{id}` | relógio da demo · gatilhos · reset (LGPD) | não |

### 3e. UI (`ui/src`)

| Tela | response_type / origem | Design |
|---|---|---|
| `Perfis.tsx` | `GET /v1/clientes` | lista do cluster-alvo (medoide destacado), fonte e rótulos |
| `Onboarding.tsx` | preferências → `POST /preferencias` | "Conheça a zera.ai" + toggles (proactive_permission, Open Finance) |
| `Home.tsx` | `GET /proativa` | home do Itaú, balão no botão flutuante (faísca), silêncio explicado. Balão presente → toque abre a experiência guiada; sem balão → o botão abre a conversa com o agente |
| `Experiencia.tsx` | SUMMARY · QUESTION · STATUS · OPTION_DETAIL · OPTIONS_COMPARISON · TEXT · TERMS_REVIEW · CONFIRMATION_REQUEST · SUCCESS · ERROR | 10 telas + acompanhamento do acordo + quick replies + histórico da conversa + FinOps; link "Conversar" para o chat |
| `Chat.tsx` | `GET /chat/inicio` · `POST /chat/stream` · `POST /chat/confirmar/stream` | conversa com o agente em tempo real: chips de tool (ex.: "calculando capacidade"), cards do motor (raio-X, capacidade, prioridades, cenários com "Quero esta", planos, acordo), **card HITL** ("Contratar o acordo": opção, parcela, prazo, total, saldo devedor, juros → Confirmar / Agora não), selo de guardrail, caixa de proteções, sugestões de próximo passo, chip FinOps (tokens/custo do turno) |

## 4. Nível 4 — Código: máquina de estados e contrato

```mermaid
stateDiagram-v2
  [*] --> IDLE
  IDLE --> EVALUATING: START
  EVALUATING --> NEEDS_INFORMATION: renda desconhecida, ou sinal de gasto fora do extrato (essenciais/sobra destoam da renda)
  NEEDS_INFORMATION --> CALCULATING: ANSWER
  EVALUATING --> CALCULATING
  CALCULATING --> SHOWING_OPTIONS: opções válidas
  CALCULATING --> NO_SUITABLE_OPTION: nada cabe (diagnóstico)
  CALCULATING --> ERROR: falha de fonte (nunca inventa)
  SHOWING_OPTIONS --> EXPLAINING: ASK_WHY
  EXPLAINING --> SHOWING_OPTIONS: VIEW_OPTIONS
  SHOWING_OPTIONS --> REVIEWING: SELECT_OPTION
  REVIEWING --> AWAITING_CONFIRMATION: CONTINUE / SET_AUTOPAY
  AWAITING_CONFIRMATION --> REVIEWING: CANCEL
  AWAITING_CONFIRMATION --> EXECUTING: CONFIRM (única ação que contrata)
  EXECUTING --> COMPLETED: criar_acordo_de_cenario
  NO_SUITABLE_OPTION --> CALCULATING: ADJUST / RETRY
  NO_SUITABLE_OPTION --> NO_SUITABLE_OPTION: ESCALATE (protocolo)
  ERROR --> CALCULATING: RETRY
  SHOWING_OPTIONS --> IDLE: CANCEL (pausa)
  COMPLETED --> COMPLETED: acompanhamento (respiro, amortização, cancelar débito automático)
  COMPLETED --> EVALUATING: START nova_jornada (mais de uma opção contratada: só o que ficou fora do acordo)
```

Roteamento de texto livre (`_intencao`, antes do LLM): LGPD → apagar dados · pessoa/atendente → ESCALATE · agora não/depois → CANCEL (pausa) ·
número em NEEDS_INFORMATION → ANSWER · desconto/juros zero → resposta honesta (condição inexistente) · "sim" em AWAITING_CONFIRMATION → orienta o botão
(não contrata) · "sim/continuar" em REVIEWING → CONTINUE · "Nx/N meses" → seleciona ou explica prazos que cabem · "por que" → ASK_WHY · rótulo
(menor parcela…) → SELECT_OPTION · "opções/ajuda" → VIEW_OPTIONS/START · saudação → orientação · resto → LLM com FATOS do estado; se o LLM falhar → orientação com ações.

Contrato de resposta: `{state, response_type, content{title, description}, options[], quick_replies[{id,label,acao,payload,text,input}], allowed_actions[],
requires_confirmation, cta, status{steps}, current, option, benefit, claims[], tradeoffs[], terms, final_terms, diagnosis, paths[], escalation, context, jornada_id, finops, numeros_permitidos[]}`.

## 5. ADK graph (agente)

```mermaid
flowchart LR
  subgraph exp["Experiência (determinística)"]
    E[Experiencia.evento] -->|ASK_WHY / ASK_QUESTION| X[explicador]
  end
  subgraph chat["Conversa (Chat.tsx)"]
    U[cliente digita / toca] -->|POST /chat/stream| S[api._stream_chat<br/>NDJSON: llm · tool_call · tool_result · card · texto · hitl · guardrail · fim]
    H[card HITL no app<br/>Confirmar / Agora não] -->|POST /chat/confirmar/stream<br/>FunctionResponse adk_request_confirmation| S
  end
  X -->|Runner.run_async · state_delta ultimos_numeros| R((Runner ADK))
  S --> R
  R --> A[LlmAgent zera<br/>Gemini 3.8 Flash · temp 0,2]
  A -.->|ZERA_MULTIAGENTE=1| D[diagnostico] & N[negociador] & C[acompanhamento]
  subgraph cb["Callbacks (guardrails RAI)"]
    B1[before_model: guardrail_entrada<br/>Model Armor · injeção · eng. social · escopo · PII · vulnerabilidade · contexto]
    B2[before_tool: exigir_consentimento<br/>recusa humana → tool não roda]
    B3[after_tool: registrar_numeros]
    B4[after_model: guardrail_saida<br/>pressão · promessa · vazamento · PII · números ∉ tools]
  end
  A --- B1 & B2 & B3 & B4
  subgraph tools["Function tools (motor/, zero LLM)"]
    T1[get_perfil_financeiro] --- T2[calcular_capacidade] --- T3[priorizar_dividas]
    T4[montar_cenarios] --- T5[simular_planos] --- T6[comparar_com_padrao]
    T7[registrar_consentimento] --- T8[[fechar_acordo ✋]] --- T9[status_acordo]
    T10[[acionar_respiro ✋]] --- T11[[amortizar aplicar ✋]] --- T12[listar_gatilhos]
    T13[escalar_humano] --- T14[revogar_consentimento] --- T15[consultar_conhecimento<br/>RAG leve: conhecimento/]
  end
  A --> tools
  T8 & T10 & T11 -->|require_confirmation → evento adk_request_confirmation<br/>invocação pausa| H
  R -->|usage_metadata| F[observabilidade.registrar_llm<br/>tokens · custo · jornada]
  R -->|spans invocation/agent/call_llm/execute_tool| O[(Telemetry API → Cloud Trace)]
```

**HITL nativo do ADK (✋)**: as três tools com efeito são `FunctionTool(func, require_confirmation=True)` (`amortizar` só quando
`aplicar=True`). Quando o modelo decide chamá-las, o ADK **não executa**: emite a function call `adk_request_confirmation`
(`originalFunctionCall{id,name,args}`) e encerra a invocação. A API transforma isso no card HITL com os números do motor (cenário/plano
guardado na sessão, nunca o texto do modelo) e o app responde em `/chat/confirmar` com `FunctionResponse(id=request_id, name=
adk_request_confirmation, response={confirmed, payload{frase_cliente}})`; só então a tool roda, registrando o consentimento com
`canal=hitl_app` e a frase. Recusa → `before_tool` devolve `acao_recusada` e a tool não roda (`bloqueios_consentimento++`). Métricas:
`zera.hitl_pedido{tool}` e `zera.hitl_resposta{confirmed}`. "Sim" digitado nunca contrata — só o botão.

**Compreensão de contexto antes do agente**: cumprimento/agradecimento/despedida têm resposta determinística (0 tokens, sem tools);
a sequência Entender → Opções → Escolher → Confirmar no app → Acompanhar é emitida como eventos `etapa` (derivados das tools chamadas e do HITL)
e só avança quando a cliente pede a ação — o prompt proíbe rodar a bateria de tools sem pedido.

**Interação visível e rápida**: `/chat/stream` devolve cada evento do Runner assim que acontece — o app mostra o chip da tool
("calculando capacidade…"), o card com o resultado do motor (`state_delta.ui`), o texto final, o card HITL e o selo de guardrail, com
tokens/custo do turno. A abertura (`/chat/inicio`) é determinística (0 tokens): contexto do gatilho, as três proteções e as sugestões
de próximo passo (direcionamento do produto).

Sessões: `InMemorySessionService` (1 worker) ou `VertexAiSessionService` (Agent Engine, `ZERA_SESSOES=vertex`). Memória de longo prazo
(Agent Engine Memory Bank) é P1. O agente é o mesmo no `adk web`, no `/chat` e no explicador da experiência.

## 5b. Diagramas de sequência (exemplos da solução)

Os mesmos quatro caminhos da apresentação (`arquitetura-c4-apresentacao.html`, seção Sequências).

### O que o desenho diz
      
        Clienteusa o app; a zera.ai só aparece proativamente se ela autorizou nas preferências. Ela pode corrigir informações, pausar, recusar e pedir uma pessoa a qualquer momento.
        zera.ai → BigQueryuma leitura pequena por sessão (perfil de 12 meses agregado, nunca o extrato bruto) e escrita append-only de estado, eventos e telemetria.
        zera.ai → Vertex AIo Gemini entra para entender a intenção e explicar; toda chamada passa pelos guardrails de entrada e de saída.
        zera.ai → humanoescalonamento com protocolo quando a cliente pede, quando há sinal de vulnerabilidade, quando nada cabe ou quando um guardrail bloqueia.
        zera.ai → transacionala contratação acontece só depois do CONFIRM no app; no MVP o acordo é criado pelo motor (termos, CET, componente por dívida).
      
    
    
      Decisões que moldam este nível
      
        O LLM nunca calculaPor quê: um erro de R$ 1 numa renegociação é erro de conformidade. Todo número nasce no motor determinístico; o guardrail de saída confere o texto do modelo contra os números das tools.
        Só a cliente contrataPor quê: consentimento explícito e auditável (canal, frase, horário). "Sim" digitado nunca contrata; só o card de confirmação no app.
        Nenhum dado mockadoPor quê: a jornada precisa funcionar com os casos difíceis reais: renda ausente no extrato, nada cabe, mais de um acordo. Renda = média das entradas; ausente, a zera.ai pergunta.
        Humano é uma saída corretaPor quê: a cliente nunca vê um selo técnico. Um bloqueio vira uma mensagem acolhedora com "falar com uma pessoa" em primeiro lugar; o bloqueio fica registrado no backend.
        Ambos ganhamPor quê: o banco mantém o saldo devedor e recebe os juros do acordo (1,8% a.m.); a cliente troca 8–14% a.m. por parcela que cabe e prazo definido (12–60x).
      
    
  




  C4 · Nível 2 · Containers
  Um serviço no Cloud Run com sete peças, e três serviços gerenciados em volta
  Dentro da linha tracejada, tudo roda na mesma imagem. Fora dela, o Google Cloud faz o que é gerenciado: modelo, dados e observabilidade.

  
    
      
        
      

      
      
      Cloud Run · serviço zera · us-central1 · 1 instância
      1 vCPU · 1 GiB · concurrency 40 · Docker multi-stage
      usuário sem privilégio · identidade do serviço (sem chave)

      
      
      HTTPS

      
      JSON
      NDJSON

      
      evento(ação) · 0 tokens

      
      Runner · /chat/stream · HITL

      
      explicador

      
      callbacks

      
      generate
      sanitize

      
      16 function tools

      

      
      perfil
      capacidade
      acordos

      
      consultar_conhecimento

      
      OTLP · JSON

      
      carregar perfil · salvar estado

      
      query → tabelas (sem job) → snapshot embarcado · estado/eventos/telemetria por streaming insert

      
      pessoaCliente (pelo app Itaú)

      
      App mobile (UI)React 19 · Vite 8 · Tailwind 4Perfis → onboarding → preferências → home com gatilho → experiência guiada · conversa com cards e card de confirmação.
      APIFastAPI · Python 3.12REST + stream NDJSON; roteamento determinístico (abertura, saudações, botão Contratar); request id e logs.

      
      Orquestrador da experiênciazera_agent/experiencia.pyMáquina de estados, proatividade (7 checks), contrato estruturado, intenção sem LLM.
      Agente ADKADK 2.10 · Gemini 3.8 FlashEntende, conduz e explica. 16 tools determinísticas; 3 pausam até a confirmação no app (HITL).
      Guardrailsguardrails.py · Model ArmorEntrada · tool · saída, como callbacks do ADK; Model Armor opcional; números conferidos com o motor.

      
      Contexto e estadozera_agent/contexto.pyPerfil + capacidade em memória; acordos (vários), consentimentos, gatilhos, renda/gastos informados; relógio da demo.
      Motor determinísticomotor/ · Python puroCapacidade, priorização, cenários por prazo, hoje × nova opção, benefícios, termos/CET, acordo, respiro, amortização, gatilhos.
      RAG leveconhecimento/*.mdPolítica, FAQ e glossário; busca lexical, top-3 trechos como evidência — nunca números; instruções embutidas filtradas.

      
      Acesso a dadosloader.py · repositório de estadoFonte rotulada; fallbacks se o IAM recusa.

      
      Observabilidade & FinOpstodas as camadas emitem spans OTel, métricas p50/p95, logs JSON com request/trace id, tokens e custo por jornada (observabilidade.py). Só no backend.

      
      Vertex AIGemini 3.8 Flash · endpoint global · temperatura 0,2 · credencial = identidade do serviço.Model Armor · template zera-guardrails.
      Cloud Trace · Monitoring · LoggingTelemetry API (OTLP): spans invocation · call_llm · execute_tool · motor.*; métricas zera.*; métricas de log, alerta 5xx, Billing Budgets.
      BigQuery · dataset zeraextrato (partição/cluster) · features · kmeans_perfis (BigQuery ML) · perfis_demo · perfil_cliente · dividas_derivadas · estado_cliente (append-only) · eventos · telemetria.
    
  

  
    
      Como as peças conversam
      
        UI → APIa experiência guiada manda {ação, payload} e recebe uma resposta estruturada (response_type); o chat recebe um evento por linha: etapa · tool_call · tool_result · card · texto · hitl · fim.
        API → Orquestradoro fluxo guiado inteiro roda sem modelo (0 tokens); o Gemini só entra para explicar ("por que essa opção?") com os fatos do estado.
        API → Agentecada mensagem livre vai ao Runner do ADK; saudações, agradecimentos e o botão Contratar são resolvidos antes, sem modelo.
        Agente → Guardrails → Vertex AItoda chamada ao Gemini passa por before_model e after_model; toda tool por before_tool (consentimento) e after_tool (números permitidos).
        Agente → Motor16 function tools; as três com efeito (fechar_acordo, acionar_respiro, amortizar) pausam a invocação até a confirmação no app.
        Agente → Base de conhecimentoconsultar_conhecimento recupera até 3 trechos da política de renegociação, FAQ e glossário para explicar termos e regras (respiro, cheque especial, negativação). Números nunca vêm daqui: só das tools do motor.
        Contexto → Dados → BigQueryuma leitura por sessão; estado em zera.estado_cliente (append-only) com fallback JSON local.
      
    
    
      Decisões que moldam este nível
      
        Um serviço, uma instânciaPor quê: um deploy, uma URL, custo previsível. Sessões do ADK e cache de contexto ficam em processo sem split-brain. Evolução: VertexAiSessionService (Agent Engine) libera max-instances &gt; 1.
        ADK com HITL nativo + botão determinísticoPor quê: FunctionTool(require_confirmation=True) pausa a tool até a resposta humana; o botão Contratar (POST /chat/contratar) abre o mesmo card sem depender de o modelo "decidir" chamar a tool. Os dois caminhos produzem os mesmos eventos.
        Guardrails como callbacks, em três camadasPor quê: a entrada bloqueia sem chamar o modelo (injeção, morse/base64, PII, fora de escopo, 3 bloqueios → humano); a saída substitui pressão, promessa e número fora das tools. Números valem a sessão inteira e caducam quando o estado muda.
        Dados: query → tabelas → snapshotPor quê: no projeto do evento a identidade de runtime não pode criar jobs no BigQuery e ninguém do time altera IAM. O deploy exporta o resultado do k-means com a credencial de quem publica; em runtime a API tenta a query, depois tabledata.list, depois o snapshot, sempre rotulando a fonte.
        Experiência guiada sem LLMPor quê: 10 telas previsíveis, testáveis por matriz estado × ação, custo zero de tokens. O modelo fica onde agrega: entender intenção e explicar.
        Observabilidade só no backendPor quê: a cliente não precisa ver tokens nem bloqueios. Traces, métricas, logs e custo por jornada vão para o Cloud Observability e para /metrics; a banca vê lá.
      
    
  




  Dinâmica · um turno de conversa
  O caminho de uma mensagem até a resposta, e o caminho de um toque em "Contratar"
  A sequência Entender → Opções → Escolher → Confirmar no app → Acompanhar só avança quando a cliente pede cada etapa.

  
    Cliente digita"Quais opções cabem no meu bolso?"
    Roteamento na APIsaudação/agradecimento → resposta fixa (0 tokens); senão vai ao agente
    Guardrail de entradaModel Armor, injeção, PII redigida, escopo, vulnerabilidade
    Gemini decidechama montar_cenarios (ou pergunta a renda se o histórico não tem entradas)
    Motor calculacenários por prazo, viabilidade, rótulos; numeros_permitidos
    Guardrail de saídanúmero fora das tools → mensagem acolhedora com "falar com uma pessoa"
    Eventos em streametapa · tool_call · card · texto · fim renderizados conforme chegam
    Toque em Contratar/chat/contratar → card de confirmação com os números do motor → /chat/confirmar executa
  

  
    Via do modelo (HITL nativo)O Gemini chama fechar_acordo → o ADK emite adk_request_confirmation e pausa → card no app → FunctionResponse(confirmed, frase) → a tool roda com consentimento canal=hitl_app. Recusa → acao_recusada, nada executa.
    Via do botão (determinística)Cada opção do card tem um botão. A API valida o cenário na sessão, abre o mesmo card (request_id btn_…) e, na confirmação, executa fechar_por_cenario no motor com consentimento canal=botao_app. Zero tokens.
    Dado insuficienteSem entradas no histórico, as tools de cálculo recusam (renda_desconhecida). A zera.ai pergunta; informar_renda grava com fonte "informada pela cliente" e tudo é recalculado. Nada é imputado.
  




  Diagramas de sequência · exemplos da solução
  Quatro caminhos que a demo percorre, passo a passo
  Cada diagrama mostra quem faz o quê: o modelo entende e explica, o motor calcula, os guardrails conferem e a cliente confirma.

  
    
      1 · Um turno de conversa — "Quais opções cabem no meu bolso?"

O roteamento determinístico trata saudações e opções digitadas; o resto vai ao agente. Toda chamada ao Gemini passa pelos guardrails de entrada e de saída; toda tool, pelo de consentimento e pelo registro de números.

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente (app)
  participant API as API FastAPI
  participant R as Runner ADK
  participant G as Guardrails
  participant M as Gemini 3.8 Flash
  participant T as Tools · Motor
  C->>API: POST /chat/stream "Quais opções cabem no meu bolso?"
  API->>API: roteamento determinístico (saudação? opção digitada?) → não
  API->>R: run_async(mensagem)
  R->>G: before_model (injeção, PII, escopo, vulnerabilidade)
  G-->>R: ok
  R->>M: generate_content (instruções + histórico + tools)
  M-->>R: function_call montar_cenarios(parcela_alvo=0)
  R->>G: before_tool (exige consentimento? não)
  R->>T: montar_cenarios → cenários C1…Cn + numeros_permitidos
  R->>G: after_tool (números da sessão)
  R-->>API: tool_call · tool_result · card cenários
  API-->>C: NDJSON: etapa "opções" + card (Contratar por opção)
  R->>M: generate_content (resultado da tool)
  M-->>R: "A melhor é a C1… 1) Contratar a C1 2) Entender por quê 3) Falar com uma pessoa"
  R->>G: after_model (pressão, promessa, PII, números ∉ tools)
  alt números conferem
    G-->>R: texto aprovado
  else número fora das tools
    G-->>R: resposta acolhedora + escalar_sugerido (bloqueio só na observabilidade)
  end
  R-->>API: texto final
  API->>API: extrai "1) 2) 3)" → opcoes (botões)
  API-->>C: texto + botões + fim (sugestões)
```

### 2 · Contratar pelo botão — via determinística com confirmação humana

O botão não depende de o modelo "decidir" chamar a tool: a API valida o cenário na sessão, abre o card de confirmação com os números do motor e, só depois do toque, executa. Nada passa pelo Gemini.

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente (app)
  participant API as API FastAPI
  participant S as Sessão ADK (estado)
  participant Mo as Motor (fechar_por_cenario)
  participant E as Estado do cliente (BigQuery · JSON)
  C->>API: POST /chat/contratar {cenario_id: "C1"}
  API->>S: C1 existe em state.cenarios e é viável?
  S-->>API: sim → request_id btn_…
  API-->>C: card HITL: parcela, prazo, total, saldo devedor, juros
  Note over C: passo humano — "Confirmo a contratação" ou "Agora não"
  C->>API: POST /chat/confirmar/stream {request_id, confirmed: true, frase}
  API->>E: consentimento (canal=botao_app, frase, data/hora)
  API->>Mo: fechar_por_cenario(C1)
  Mo-->>API: acordo (componente por dívida, termos, CET)
  API->>E: acordo salvo (append-only)
  API->>S: histórico: "[Toquei em Contratar C1 e confirmei]" + "Pronto: acordo fechado…" + ultimas_opcoes
  API-->>C: etapa confirmar → tool_call/tool_result → card acordo → texto + botões → etapa acompanhar
```

### 3 · HITL nativo do ADK — quando o modelo decide chamar fechar_acordo

As tools com efeito são FunctionTool(require_confirmation=True): o ADK pausa a invocação e só executa com a resposta humana. Um "sim" digitado nunca contrata.

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente (app)
  participant API as API FastAPI
  participant R as Runner ADK
  participant M as Gemini 3.8 Flash
  participant T as fechar_acordo (require_confirmation)
  C->>API: "quero fechar a C1"
  API->>R: run_async
  R->>M: generate_content
  M-->>R: function_call fechar_acordo(plano_id="C1")
  R-->>API: adk_request_confirmation(originalFunctionCall) — invocação pausada
  API-->>C: card HITL com os números da sessão (nunca o texto do modelo)
  C->>API: POST /chat/confirmar {request_id, confirmed, frase}
  API->>R: FunctionResponse(adk_request_confirmation, {confirmed, frase_cliente})
  alt confirmado
    R->>T: executa (consentimento canal=hitl_app + frase)
    T-->>R: acordo
    R->>M: resultado → texto
    R-->>API: card acordo + texto
  else recusado
    R-->>API: acao_recusada — a tool não roda ("nada foi contratado")
  end
  API-->>C: eventos NDJSON (etapa, card, texto, fim)
```

### 4 · Proatividade e dado insuficiente — o balão só aparece se as 7 pré-condições passam

Sem renda no extrato não há cálculo nem abordagem proativa: a zera.ai pergunta, a cliente informa e tudo é recalculado com o valor dito por ela.

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente
  participant App as App (home)
  participant API as API FastAPI
  participant D as Dados (BigQuery · snapshot)
  participant Mo as Motor
  participant X as Orquestrador da experiência
  App->>API: GET /v1/clientes/{id}/proativa
  API->>D: 1 leitura: perfil_cliente (12 meses) + dividas_derivadas
  D-->>API: perfil (renda = média das entradas, dívidas rotuladas)
  API->>Mo: detectar_gatilhos
  Mo-->>API: entrada_rotativo (cheque especial a 8% a.m.)
  API->>X: avaliar_proatividade (permissão, gatilho, oportunidade, benefício, contexto, ação, frequência)
  alt renda não identificada
    X-->>App: {silent: true, reason: "sem contexto suficiente"} → sem balão
    C->>API: no chat: "quanto eu devo?" → tools de cálculo recusam (renda_desconhecida) → a zera.ai pergunta
    C->>API: "minha renda é 2.500" → informar_renda → capacidade e cenários recalculados
  else tudo ok
    X-->>App: PROACTIVE_MESSAGE "Diminua suas parcelas"
    C->>App: toca no balão → experiência guiada (0 tokens) ou conversa
  end
```

## 6. Pipeline de dados e ciência de dados

```mermaid
flowchart TB
  S[(hackathon_dados.extrato_sintetico)] -->|CREATE TABLE … PARTITION BY dia CLUSTER BY id_usuario| E[(zera.extrato)]
  E -->|classe: renda · divida · parcela · essencial · assinatura · outros| FM[(features_mensais)]
  FM --> PC[(perfil_cliente<br/>12 meses em arrays, renda_conhecida, cv_renda)]
  FM --> FC[(features_cliente<br/>pct_essenciais, pct_servico_divida, parcelas, meses_no_vermelho, pior_saldo, sinais rotativo/empréstimo, cv_renda)]
  FC -->|CREATE MODEL k-means++ · standardize · k=4| KM{{kmeans_perfis}}
  KM -->|ML.PREDICT| CC[(clusters_clientes<br/>cluster, distância)]
  CC -->|índice de endividamento = média dos z-scores| PK[(perfil_clusters<br/>cluster_alvo)]
  E -->|regras: saldo<0 → cheque; k/N → crediário; descr → cartão/empréstimo| DD[(dividas_derivadas · fonte=derivada_extrato)]
  PK & CC & PC & DD --> PD[(perfis_demo<br/>ordenado por distância · medoide = persona)]
  PD --> API[/GET /v1/clientes/]
  PC & DD --> CTX[Contexto → capacidade P25/colchão/CV → cenários → gatilhos]
  CTX --> EV[(eventos · estado_cliente · telemetria)]
  EV --> LS[Looker Studio / SQL: funil, cumprimento, reincidência, custo por jornada]
```

**Decisões de ciência de dados**

| Etapa | Escolha | Por quê / como validar |
|---|---|---|
| Features | 12 meses por cliente; proporções (essenciais/saídas, serviço de dívida/saídas) e sinais binários | Robustas quando a renda não aparece no extrato (base do evento pode não ter entradas). |
| Segmentação | k-means (BigQuery ML), k=4, k-means++, features padronizadas | Roda onde os dados estão, sem mover dados. `ML.EVALUATE` do modelo de produção (base completa, 1.000 clientes): Davies-Bouldin 1,569, distância quadrática média 7,286; curva por k com `dados/avaliar_k.py` (`zera.kmeans_avaliacao`, gráfico na apresentação). |
| Cluster-alvo | maior índice de endividamento (média de z-scores de vermelho, pior saldo, serviço de dívida, parcelas, rotativo, empréstimo) | Regra explícita e auditável; a mesma fórmula roda em pandas no modo local (`segmentacao.py`). |
| Persona | medoide do cluster-alvo (menor distância ao centróide) recebe o nome "Cleide" | Persona = cliente real mais típico do segmento; identidade fictícia (quadro item 19). |
| Dívidas | derivadas por regras (rotuladas) — o evento não traz cadastro | Substituir por cadastro real na integração; a interface já mostra a fonte. |
| Capacidade | P25 da sobra − colchão 5% × 0,75; conforto 70% se CV(renda) ≥ 0,12 | Premissas documentadas em `politicas.py`; sensibilidade testada (gasto de R$ 80 muda a recomendação; R$ 300 → nenhuma opção). |
| Renda ausente | perguntar (informação confirmada pela cliente), nunca imputar | Quadro itens 13/14: dados insuficientes; entrada atípica ≠ renda livre. |
| Gatilhos | entrada_rotativo, pre_negativacao, risco_parcela, dinheiro_extra | P1: scheduled query diária (BigQuery Data Transfer) + Pub/Sub → serviço. |
| Avaliação do agente | golden set de perguntas (guardrails, números, tom) em `tests/`; `adk eval` / Gen AI Evaluation (P1) | Métricas do quadro (itens 21–24): cumprimento D+90, conversão, reincidência, respostas sem respaldo, bloqueios. |

## 7. Deployment

```mermaid
C4Deployment
  title zera.ai — deployment no GCP (batalha-time-03-vhxk)
  Deployment_Node(dev, "Estação / Cloud Shell", "gcloud · python · node") {
    Container(src, "Repositório", "git main", "Dockerfile multi-stage · infra/*.sh · dados/sql/*.sql")
  }
  Deployment_Node(gcp, "Google Cloud", "projeto batalha-time-03-vhxk") {
    Deployment_Node(cb, "Cloud Build", "gcloud run deploy --source") {
      Container(img, "Imagem", "Artifact Registry", "python:3.12-slim + ui/dist · usuário sem privilégio")
    }
    Deployment_Node(cr, "Cloud Run · us-central1", "min 1 / max 2 · 1 vCPU · 1 GiB · concurrency 40 · SA zera-run") {
      Container(svc, "zera", "uvicorn --workers 1", "API + agente + UI")
    }
    Deployment_Node(va, "Vertex AI · global", "") { Container(gem, "Gemini 3.8 Flash", "generate_content", "+ Model Armor template zera-guardrails") }
    Deployment_Node(bq, "BigQuery · location do evento", "") { ContainerDb(ds, "dataset zera", "tabelas + modelo k-means", "partição/cluster; estado append-only") }
    Deployment_Node(ob, "Observability", "") { Container(tel, "Telemetry API → Trace/Monitoring; Cloud Logging; Billing Budgets", "", "") }
  }
  Rel(src, img, "build")
  Rel(img, svc, "deploy (revisão com label versao=git sha)")
  Rel(svc, gem, "HTTPS", "roles/aiplatform.user")
  Rel(svc, ds, "BigQuery API", "roles/bigquery.dataEditor + jobUser")
  Rel(svc, tel, "OTLP + stdout", "roles/logging.logWriter · monitoring.metricWriter · cloudtrace.agent · telemetry.*Writer")
```

Runbook: `infra/deploy_app.sh` (build+deploy+IAM) → `curl $URL/ready` → `infra/observabilidade.sh` → rollback com
`gcloud run services update-traffic zera --to-revisions=<anterior>=100`. Falhas comuns: 404 do modelo (`GOOGLE_CLOUD_LOCATION` deve ser `global`;
`unset` no shell), `Reauthentication`/ADC ausente (só afeta o LLM), BigQuery `Not found: Dataset` (rodar `publicar_bq`), JOIN entre locations (dataset
`zera` é criado na location do evento).

## 8. Observabilidade e FinOps (em todas as camadas)

| Camada | Sinal | Onde | Como usar |
|---|---|---|---|
| HTTP | `http.latencia_ms{rota,metodo}`, `zera.http_status{rota,status}`, log `http` (request id) | Monitoring (OTel) · Logs · `/metrics` | p50/p95 por rota; alerta 5xx (`infra/observabilidade.sh`) |
| Experiência | `zera.evento{acao,estado,resultado}`, `zera.transicao{de,para}`, `zera.opcoes_apresentadas`, `zera.opcao_selecionada`, `zera.acordo_fechado`, `zera.nenhuma_opcao`, `zera.escalado`, `zera.erro`, `zera.intencao` | Monitoring · Logs (`transicao`) · `zera.eventos` | funil (item 23), taxa de "nenhuma opção", escalonamentos, intenções não cobertas |
| Motor | spans `motor.montar_cenarios`, `motor.criar_acordo` + latência | Cloud Trace · `/metrics` | custo zero de tokens; latência de cálculo (~1 ms) |
| Agente (ADK) | spans `invocation`, `agent_run`, `call_llm` (tokens), `execute_tool`; `zera.llm.*`; log `chamada_llm` | Cloud Trace · Monitoring · `zera.telemetria` | tokens, latência e custo por chamada; taxa de bloqueio dos guardrails (`zera.guardrail_bloqueio{camada,tipo}`) |
| Guardrails | evento `guardrail_bloqueio`, contadores `alucinacao_numerica`, `pii_redigida`, `bloqueios_consentimento` (session state) | `zera.eventos` · Logs | item 24: números divergentes, respostas sem respaldo, violações de tom |
| HITL (conversa) | `zera.hitl_pedido{tool}`, `zera.hitl_resposta{confirmed}`; consentimento com `canal=hitl_app` + frase no estado do cliente | Monitoring · `zera.estado_cliente` | taxa de confirmação por ação; nenhuma ação com efeito sem par pedido→resposta |
| Dados | `dados.listar_clientes.latencia_ms`, `/ready` | Monitoring | readiness real (a fonte responde) |
| FinOps | `custo_usd = tokens × preço/1M` por chamada; `custo_da_jornada(jornada_id)`; `/metrics.finops` (custo médio por acordo/jornada); orçamento de billing 50/90/100% | `/metrics` · `zera.telemetria` · Billing Budgets | custo por jornada concluída (item 25); o LLM entra em 2 das 10 telas |

Modelo de custo por jornada (referência): 0 tokens no fluxo guiado; "por que essa opção?" ≈ 1 chamada (~1,5k tokens de entrada, ~150 de saída);
cada pergunta livre ≈ 1 chamada (~1,2k/120). Com preços de referência da classe Flash (US$ 0,30/1M entrada, US$ 2,50/1M saída), uma jornada com
"por que" + 2 perguntas ≈ **US$ 0,002**. Infra: Cloud Run min 1 instância ≈ custo fixo baixo; BigQuery on-demand com partição/cluster
(1 leitura de perfil por sessão, sem varrer o extrato). Latência: eventos determinísticos < 10 ms de API; LLM 1–4 s (p95 alvo < 6 s).

## 9. Segurança e RAI

- **Entrada → modelo → saída** (workshop RAI): `guardrails.py` + Model Armor (`ZERA_MODEL_ARMOR=1`, template criado em `infra/setup_gcp.sh`). Golden set de ataques em `tests/test_guardrails_ataques.py`.
- **Consentimento**: preferências explícitas; na experiência guiada `CONFIRM` é a única ação que contrata; na conversa, as tools com efeito exigem a confirmação humana nativa do ADK (`require_confirmation` → card no app → `/chat/confirmar`), registrada com `canal=hitl_app` e a frase da cliente; "sim" digitado não contrata.
- **Dados**: contexto mínimo (agregados, nunca o extrato bruto no prompt), PII redigida na entrada e na saída, identidades fictícias, `revogar_consentimento` (LGPD), estado append-only com `apagado=true`.
- **IAM**: service account dedicada `zera-run` com papéis mínimos (Vertex user, BigQuery dataEditor/jobUser, logging/monitoring/trace writers, Model Armor user). Segredos de terceiros só no Secret Manager.
- **Runtime**: container sem privilégio, 1 worker, timeouts, CORS por env, docs desligados em produção (`ZERA_DOCS=0`).

## 10. Uso de cada serviço GCP habilitado no projeto

| Serviço (API habilitada) | Uso no zera.ai | Status |
|---|---|---|
| Vertex AI / Agent Platform (`aiplatform`) | Gemini 3.8 Flash via ADK (endpoint global); Agent Engine Sessions (`ZERA_SESSOES=vertex`) e deploy gerenciado (`infra/deploy_agent_engine.sh`); Gen AI Evaluation para o golden set | MVP (modelo) · P1 (sessões/eval) |
| BigQuery (+ Storage, Connection, Data Policy, Reservation, Data Transfer, Migration) | camada de dados completa, k-means (BigQuery ML), estado/eventos/telemetria; Data Transfer = scheduled query diária de features/clusters; Data Policy = mascaramento de colunas (P1) | MVP |
| Cloud Run | serviço único (API + agente + UI) com SA dedicada | MVP |
| Cloud Build · Artifact Registry · Container Registry | build da imagem (`gcloud run deploy --source`) | MVP |
| Cloud Logging | logs JSON estruturados com trace id; métricas de log (`infra/observabilidade.sh`) | MVP |
| Cloud Monitoring · Telemetry API | métricas OTel (`workload.googleapis.com/zera.*`) e traces do ADK via `telemetry.googleapis.com`; alerta 5xx | MVP |
| Model Armor | sanitização de prompt e resposta (template `zera-guardrails`) | MVP (flag) |
| Cloud Billing · Billing Budgets | orçamento com alertas 50/90/100% | MVP |
| Pub/Sub | P1: eventos de gatilho (scheduled query → Pub/Sub → serviço) e trilha de eventos para outros consumidores | P1 |
| Secret Manager | credenciais de integrações futuras (Open Finance, sistemas transacionais) | P1 |
| Cloud Storage | staging de deploy/Agent Engine; exportações | apoio |
| IAM · IAM Credentials · Resource Manager · Service Usage · API Keys | SA e papéis mínimos; habilitação de APIs | MVP |
| Dataform · Dataplex | P1: versionar as transformações SQL (zera_tabelas/clusterizacao) como pipeline Dataform; catálogo/linhagem no Dataplex | P1 |
| Dialogflow · Discovery Engine (Vertex AI Search) · Gemini API (generativelanguage) | não usados: a conversa é ADK + Gemini no Vertex (governança/observabilidade); Discovery Engine seria RAG de FAQ do produto (P2) | não usado (justificado) |
| Analytics Hub | não usado no MVP (compartilhamento de datasets entre times) | não usado |
| Cloud Shell | operação (publicar_bq, deploy) | apoio |

Não habilitados e por isso fora do desenho: Firestore (estado em BigQuery append-only), Cloud Scheduler (substituído por scheduled query + Pub/Sub), Cloud Trace API clássica (substituída pela Telemetry API OTLP).

## 11. Boas práticas adotadas

Determinismo testável (56 testes sem rede, matriz estado × ação); configuração 12-factor por env (`env.demo`); idempotência (SQL `CREATE OR REPLACE`/`IF NOT EXISTS`, reset por cliente, segundo `CONFIRM` não duplica acordo); contrato de API estável (UI reage a `response_type`); observabilidade como código; IAM mínimo; imagem sem root; sem dado sintético na aplicação (fixtures só em testes); documentação viva (README + este desenho + quadro de produto).

## 12. Spec → código

| Spec / quadro | Onde |
|---|---|
| §2 evento ≠ recomendação; §7 pré-condições de proatividade | `Experiencia.avaliar_proatividade` (`checks`) |
| §5.1 não perguntar o que já sabemos; §5.3 confirmar inferência crítica; item 13 dados insuficientes | `_proxima_pergunta` (renda só se ausente; gasto uma vez) |
| §5.2 dado financeiro só de fonte confiável | `Contexto` ← `dados/loader` (BigQuery/amostra) → `motor` |
| §5.4 ação sensível → consequência + confirmação; §17 só CONFIRM autoriza | `_confirmacao` → `_confirm` (estado `AWAITING_CONFIRMATION`) |
| §10 claims validados; §11 recommended explicável | `motor/beneficios` · `criterio_recomendacao` |
| §16 débito automático recalcula tudo | `termos(..., debito_automatico)` |
| item 13 exceções (recusar, pausar, atendimento, nenhuma oferta, condição inexistente) | `_cancel(texto)`, `_escalate`, `_sem_opcao`, `_condicao_inexistente`, `_pedido_de_prazo` |
| item 15 motor; item 16 papel do LLM | `motor/` · `_prompt_pergunta` (FATOS) + guardrail de números |
| item 19/20 guardrails de dados, financeiros e de experiência | `guardrails.py` · `tests/test_guardrails_ataques.py` · trade-offs antes da decisão |
| itens 21–25 métricas, monitoramento, FinOps | `observabilidade.py` · `zera.eventos` · `zera.telemetria` · `/metrics` |
| §19 AT01–AT10 | `tests/test_experiencia.py` |
