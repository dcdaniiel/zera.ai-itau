# zera.ai — Documento explicativo da arquitetura

**Entregável 5 da submissão** · Batalha de Agentes Itaú × Google (26–27/09/2026) · projeto GCP `batalha-time-03-vhxk`
Complementa: [`arquitetura-c4.md`](arquitetura-c4.md) (diagramas C4, grafo do ADK, pipeline de dados) · [`arquitetura-c4-apresentacao.html`](arquitetura-c4-apresentacao.html) (níveis 1 e 2 para apresentar) · [`PRD-MVP.md`](PRD-MVP.md) · [`estrategia-dados.md`](estrategia-dados.md) · [`quadro-produto.md`](quadro-produto.md) · [`../infra/producao.md`](../infra/producao.md)

---

## 1. Resumo em um parágrafo

A zera.ai é um agente do Itaú que detecta quando a cliente entra no rotativo (ou no cheque especial), convida — só se ela autorizou — a
organizar os pagamentos, calcula **opções de renegociação que cabem no mês dela**, explica cada opção em linguagem simples e **contrata
apenas com confirmação explícita no app**. A arquitetura separa em camadas o que precisa ser **exato** do que precisa ser **compreensível**:
um **motor determinístico** em Python puro produz todo número, elegibilidade e termo; um **agente ADK com Gemini (Vertex AI)** interpreta a
intenção, conduz a conversa e explica, chamando o motor por *function tools*; **guardrails em três camadas** garantem que nenhum número
inventado, promessa ou pressão chegue à cliente; os dados vêm **só da base do evento** (BigQuery + BigQuery ML), nunca de mock; e tudo
roda em **um serviço no Cloud Run** com observabilidade no Cloud Trace / Logging / Monitoring. O princípio de negócio é **"ambos ganham"**:
o banco não abre mão do saldo devedor — muda taxa e prazo — e a cliente ganha parcela que cabe, data para acabar e nome limpo.

```
cliente (app) ──► UI React ──► API FastAPI ──┬─► Orquestrador da experiência guiada (0 tokens)  ──┐
                                             ├─► Agente ADK (Gemini 3.8 Flash) ── tools ─────────┼─► Motor determinístico ─► Contexto/Estado
                                             │        ▲ guardrails: entrada · tool · saída        │            ▲
                                             └─► Rotas determinísticas (/chat/inicio, /chat/contratar, saudações)            │
                                                                                                    dados/loader ◄─── BigQuery zera.* (k-means) | snapshot | amostra real
observabilidade (backend): OTel → Cloud Trace / Monitoring · logs JSON → Cloud Logging · zera.telemetria / zera.eventos (BigQuery)
```

## 2. Princípios que orientaram cada decisão

| # | Princípio | O que significa na prática | Por quê |
|---|---|---|---|
| P1 | **Núcleo determinístico manda** | Todo número (capacidade, parcela, total, CET, prioridade), toda elegibilidade e toda contratação nascem em `motor/`. O LLM nunca calcula nem decide fluxo. | Um erro de R$ 1 numa renegociação é um erro de produto e de conformidade. LLMs erram aritmética; código testado não. |
| P2 | **Nenhum dado mockado** | Perfis reais da base do evento (`hackathon_dados.extrato_sintetico`), segmentados por k-means no BigQuery ML; a amostra local também é export real; fixtures só em testes. | A banca avalia a jornada sobre dados de verdade; dado inventado esconde os casos difíceis (renda ausente, nada cabe). |
| P3 | **Dado que falta se pergunta, não se inventa** | Sem entradas no histórico → `renda_desconhecida` → o motor recusa calcular e a zera.ai pergunta; a resposta vira `renda_informada` com fonte visível. | "Dados insuficientes" é um cenário obrigatório do quadro de produto (item 13); imputar renda seria decidir pela cliente. |
| P4 | **Só a cliente contrata** | Na experiência guiada, só a ação `CONFIRM`; na conversa, só o card HITL (nativo do ADK ou aberto pelo botão **Contratar**). "Sim" digitado nunca contrata. | Consentimento explícito e auditável (`canal`, frase, timestamp) — exigência de RAI e de LGPD. |
| P5 | **Ambos ganham** | O banco mantém o saldo integral e recebe os juros do acordo (1,8% a.m.); a cliente troca 8–14% a.m. por parcela que cabe e prazo definido. | Renegociação sustentável (métrica principal: cumprimento em D+90), não desconto que destrói margem. |
| P6 | **Sem beco sem saída** | Toda combinação estado × ação tem transição; texto livre é roteado antes do LLM; "nenhuma opção" traz diagnóstico e caminhos; bloqueio de guardrail vira encaminhamento humano acolhedor. | Encaminhar a um humano é uma saída correta, não uma falha (quadro item 25). |
| P7 | **Observável e com custo conhecido** | Cada etapa emite span, métrica e log; cada chamada ao Gemini registra tokens e custo; nada disso aparece na interface da cliente. | FinOps e monitoramento do agente (itens 24/25) — e a interface fica limpa. |
| P8 | **Simples de operar** | Um serviço, uma imagem, um deploy idempotente, fallbacks automáticos quando o IAM do projeto do evento não permite algo. | Hackathon: o que não sobe com um comando não é apresentado. |

---

## 3. Visão geral (C4 níveis 1 e 2, em texto)

**Contexto (nível 1).** Atores: a **cliente** (decide e autoriza tudo), o **atendimento humano** (recebe escalonamentos), e **Produto/Crédito/Dados**
(definem catálogo e políticas, acompanham funil e custo). Sistemas externos: **BigQuery** (base do evento e camada `zera.*`), **Vertex AI**
(Gemini 3.8 Flash no endpoint `global`, Model Armor), **Cloud Observability** (Trace/Monitoring/Logging) e os **sistemas transacionais** do banco
(contratação/débito automático — simulados no MVP, marcados como tal).

**Containers (nível 2).** Um único serviço no **Cloud Run** (`zera`, `us-central1`) contém sete containers lógicos:

| Container | Tecnologia | Responsabilidade |
|---|---|---|
| **UI (app mobile)** | React 19 · Vite 8 · Tailwind 4 (servida pela própria API) | Perfis → onboarding → preferências → home com gatilho → experiência guiada de 10 telas · conversa com o agente (cards, HITL, trilha de etapas) |
| **API** | FastAPI · Python 3.12 · uvicorn (1 worker) | Rotas REST + streaming NDJSON do chat; roteamento determinístico; middleware de request id/latência/logs |
| **Orquestrador da experiência** | `zera_agent/experiencia.py` | Máquina de estados, proatividade (7 pré-condições), contrato de resposta estruturado, roteamento de intenção sem LLM |
| **Agente ADK** | google-adk 2.10 · `LlmAgent` · Gemini 3.8 Flash | Entende intenção, conduz a conversa, explica; 16 *function tools*; HITL nativo; 4 callbacks de guardrail |
| **Motor determinístico** | `motor/` · Python puro | Capacidade, priorização, cenários por prazo, hoje × nova opção, benefícios validados, termos/CET, acordo, respiro, amortização, gatilhos |
| **Contexto e estado** | `zera_agent/contexto.py` | Perfil + capacidade em memória; estado (acordos, consentimentos, gatilhos, renda/gastos informados) em BigQuery com fallback JSON; relógio da demo |
| **Observabilidade & FinOps** | `zera_agent/observabilidade.py` | OTel (spans do ADK + spans próprios) → Telemetry API; logs JSON; métricas p50/p95; tokens/custo por chamada e por jornada |

Fora do serviço: **BigQuery** (dataset `zera`: extrato particionado, features, modelo k-means, clusters, perfis, dívidas derivadas, estado, eventos,
telemetria), **Vertex AI** (Gemini + Model Armor) e **Cloud Trace / Monitoring / Logging / Billing Budgets**. Os diagramas estão em
[`arquitetura-c4.md`](arquitetura-c4.md) §1–§2 e, em versão para apresentar, em [`arquitetura-c4-apresentacao.html`](arquitetura-c4-apresentacao.html).

---

## 4. Componentes em detalhe

### 4.1 Motor determinístico (`motor/`)

Python puro, sem I/O, sem LLM, 100% coberto por `tests/test_motor.py`. Cada função devolve, além do resultado, a lista `numeros_permitidos`
que o guardrail de saída usa para conferir o texto do modelo.

| Módulo | Função | O que faz |
|---|---|---|
| `politicas.py` | `carregar_politica` | Alavancas de crédito (fictícias, documentadas): percentil da sobra (25), colchão 5%, fator 0,75, respiros 2, taxa de renegociação 1,8% a.m., prazos 12/18/24/36/48/60, conforto 70% quando a renda é irregular (CV ≥ 0,12), `pct_essenciais_minimo` 30% e `pct_sobra_suspeita` 55% (sinais de gasto fora do extrato). |
| `capacidade.py` | `calcular_capacidade` · `sinais_gastos_invisiveis` | `sobra[m] = renda − essenciais − compromissos` por mês; `parcela_maxima = 0,75 × max(0, P25(sobra) − 0,05 × renda_mediana)`; meses fracos → respiros. Sinais de gasto invisível: essenciais < 30% da renda ou sobra > 55% → a pergunta "tem gasto fixo fora do extrato?" só aparece quando os dados sugerem. |
| `priorizacao.py` | `priorizar_dividas` | Custo mensal (saldo × taxa) + peso da consequência (negativação) quando há atraso relevante; dívidas a 0% são explicadas como "sem juros". |
| `alocacao.py` | `alocar_entrada` · `montar_cenarios` | Entrada (13º/IRPF) quita as dívidas mais caras que couberem e abate a mais cara restante; um cenário por prazo com o saldo consolidado integral à taxa de renegociação; viável se `parcela + mantidas ≤ parcela_maxima` e meses ruins ≤ respiros. Rótulos: **recomendado** (menor prazo com conforto), **mais_barato**, **mais_folga**, **guardar_extra**; com `parcela_alvo`, marca as que atendem e diz a menor parcela possível e a entrada necessária. Diagnóstico quando nada cabe. |
| `consolidacao.py` | `situacao_hoje` · `projecao_mesmo_prazo` · `resumo_cenario` · `termos` | "Hoje" sem total mágico (pagamentos, saldo devedor, juros/mês, sem prazo); projeção like-for-like por prazo; nova opção: total = saldo + juros; termos com CET, vencimentos, dívidas incluídas e fonte. |
| `beneficios.py` | `validar_beneficios` · `claims` · `tradeoffs` · `criterio_recomendacao` | Só afirma o que o número comprova (parcela menor, custo total menor no mesmo prazo, taxa menor, nome limpo, prazo definido, pagamento único); trade-offs incluem o que o banco recebe. |
| `simulacao.py` | `pmt` · `pv` · `cet_anual` · `criar_acordo_de_cenario` · `registrar_pagamento` · `acionar_respiro` · `amortizar` · `processar_vencimentos` | Tabela Price; acordo com componente por dívida; respiro sem mora; amortização 1:1 no componente mais caro. |
| `gatilhos.py` | `detectar_gatilhos` | `entrada_rotativo` (cartão rotativo **ou** cheque especial com juros, o mais caro primeiro) > `pre_negativacao` (≥ 45 dias) > `risco_parcela` (D-3, sobra prevista < parcela) > `dinheiro_extra` (≥ 40% da renda mediana ou 13º/IRPF/FGTS/PLR). |
| `modelos.py` | dataclasses | `Divida`, `PerfilFinanceiro` (`renda_media`, `meses_com_renda`, `renda_desconhecida`, `renda_fonte`, `renda_informada`, persona), `Capacidade`, `Acordo`; `brl()`. |

**Decisão:** renda = **média mensal das entradas (tipo `E`) do histórico de 12 meses**, com a fonte exibida. Sem nenhum mês com entrada, o
perfil fica `renda_desconhecida` e as funções de cálculo recusam (`erro: renda_desconhecida`) — nunca há capacidade "zero" silenciosa.

### 4.2 Camada de dados (`dados/`, BigQuery e BigQuery ML)

**Fonte única de verdade:** `hackathon_dados.extrato_sintetico` (base do evento). O SQL versionado em `dados/sql/` cria a camada `zera.*`:

```
extrato (partição por dia, cluster por id_usuario, classe da transação)
  → features_mensais → perfil_cliente (12 meses em arrays, renda_media, meses_com_renda, cv_renda)
  → features_cliente → CREATE MODEL kmeans_perfis (k-means++, features padronizadas, k=4)
  → ML.PREDICT → clusters_clientes → perfil_clusters (índice de endividamento = média de z-scores) → cluster_alvo
  → perfis_demo (clientes reais do cluster-alvo, ordenados por renda_conhecida DESC e distância ao centróide; medoide = persona "Cleide")
  → dividas_derivadas (saldo < 0 → cheque especial; k/N → crediário; descrição → cartão/empréstimo; fonte = derivada_extrato)
  + estado_cliente (append-only) · eventos · telemetria
```

`dados/loader.py` decide a fonte por `ZERA_FONTE` e sempre rotula o que devolve:

| Modo | De onde vem | Quando |
|---|---|---|
| `bigquery` | 1 query pequena por sessão em `perfil_cliente` + `dividas_derivadas` + `perfis_demo` + `clusters_clientes` (nunca varre o extrato bruto) | Produção com `bigquery.jobs.create` |
| `bigquery` sem job | Se a query recebe 403 (`jobs.create` negado), lê as **tabelas diretamente** (`tabledata.list`, com cache) — basta acesso de dataset | Produção no projeto do evento, onde a identidade de runtime não pode criar jobs |
| `bigquery_snapshot` | `dados/snapshot_bq/*.json`, exportado pelo deploy com a credencial de quem publica (`dados/exportar_snapshot_bq.py`), rotulado com a hora da exportação | Fallback automático quando o BigQuery recusa tudo; a fonte aparece como `bigquery_snapshot (<hora>)` |
| `amostra` | `dados/amostra_bq_extrato_sintetico.csv` — export **real** (40 clientes do segmento × 12 meses, `dados/sql/exportar_amostra.sql`) + `segmentacao.py` (mesmas features em pandas) | Local sem credenciais |
| `fixture` | `tests/fixtures/` | **Só testes** |

Ordem de tentativa em runtime: **query → tabelas sem job → snapshot**. `/health` mostra qual está ativa. O extrato bruto nunca entra no prompt
(custo, latência e risco de PII/alucinação): o agente recebe agregados de 12 meses e o motor calcula em memória (< 10 ms).

### 4.3 Contexto e estado do cliente (`zera_agent/contexto.py`)

`Contexto.para(cliente_id)` carrega o perfil (loader), aplica renda e gastos informados, compromissos e **acordos ativos**, e calcula a capacidade.
Suporta **mais de um acordo**: as dívidas cobertas saem de `perfil.dividas`, as parcelas ativas entram como compromisso fixo, e uma nova jornada
só renegocia o que ficou de fora. O estado (acordos, consentimentos com canal e frase, gatilhos, preferências, renda/gastos informados) é
persistido por um **repositório resiliente**: BigQuery (`zera.estado_cliente`, append-only, "apagar" = snapshot com `apagado=true`) com fallback
para JSON local na primeira falha — consistente porque o serviço roda com **1 instância**. O relógio da demo (`ZERA_HOJE`, `/simular_tempo`)
permite mostrar o 13º em dez/26 e o mês fraco em jan/27.

### 4.4 Orquestrador da experiência guiada (`zera_agent/experiencia.py`)

Máquina de estados `IDLE → EVALUATING → (NEEDS_INFORMATION) → CALCULATING → SHOWING_OPTIONS → REVIEWING → AWAITING_CONFIRMATION → EXECUTING → COMPLETED`,
com `NO_SUITABLE_OPTION` e `ERROR`, 19 ações e um contrato de resposta estável (`{state, response_type, content, options, quick_replies,
allowed_actions, requires_confirmation, …, numeros_permitidos}`) que a UI renderiza por `response_type`. Roda **sem LLM** (0 tokens): o Gemini só
entra em `ASK_WHY`/`ASK_QUESTION` como explicador, recebendo os FATOS do estado e a lista de números permitidos.

A **proatividade** passa por 7 pré-condições explícitas (`proactive_permission`, `trigger_present`, `opportunity_found`, `benefit_validated`,
`required_context_available` — renda conhecida —, `action_available`, `contact_frequency_allowed`) e devolve `{silent, checks, reason}` quando
alguma falha — o silêncio é explicado, nunca mudo. `_proxima_pergunta` só pergunta o que os dados não dizem:
renda se ausente; gasto fixo apenas quando `sinais_gastos_invisiveis` aponta, com os números reais na pergunta. Depois de `COMPLETED`, `START`
abre uma nova jornada para o que ficou fora do acordo.

### 4.5 Agente ADK (`zera_agent/agent.py`, `tools.py`, `prompts.py`)

- **Topologia:** um `LlmAgent` "zera" (Gemini 3.8 Flash via Vertex AI, endpoint `global`, temperatura 0,2) com todas as tools — mais previsível
  na demo. `ZERA_MULTIAGENTE=1` liga a topologia root + sub-agentes **diagnóstico / negociador / acompanhamento** (mesmas tools divididas por papel).
- **16 function tools**, todas determinísticas e sempre com o `cliente_id` vindo da sessão (nunca do modelo):
  `get_perfil_financeiro`, `informar_renda`, `informar_gasto_fixo`, `calcular_capacidade`, `priorizar_dividas`, `montar_cenarios(valor_extra, parcela_alvo)`,
  `comparar_com_padrao`, `fechar_acordo` ✋, `status_acordo`, `acionar_respiro` ✋, `amortizar` ✋ (quando `aplicar=True`), `listar_gatilhos`,
  `registrar_consentimento`, `revogar_consentimento`, `escalar_humano`, `consultar_conhecimento`. Sem renda no histórico, as tools de cálculo
  devolvem `erro: renda_desconhecida` e a pergunta — o modelo não tem como "seguir em frente" sem o dado.
- **HITL nativo do ADK (✋):** as tools com efeito são `FunctionTool(func, require_confirmation=True)`. Quando o modelo decide chamá-las, o
  ADK **não executa**: emite `adk_request_confirmation` e pausa a invocação; a API transforma isso no **card HITL** com os números do motor
  (cenário guardado na sessão, nunca o texto do modelo); o app responde em `/chat/confirmar` com um `FunctionResponse(confirmed, frase_cliente)`
  e só então a tool roda, registrando o consentimento com `canal=hitl_app`. Recusa → `before_tool` devolve `acao_recusada` e nada é executado.
- **Botão "Contratar" (via determinística):** cada opção do card de cenários tem um botão. `POST /chat/contratar` valida o cenário na sessão e
  devolve o mesmo card HITL (`request_id` `btn_…`); `POST /chat/confirmar` executa `fechar_por_cenario` no motor sem passar pelo modelo
  (consentimento `canal=botao_app`) e emite a mesma sequência de eventos. Assim a contratação nunca depende de o LLM "decidir" chamar a tool.
- **Prompt (`prompts.py`):** regras invioláveis (números só das tools; parcela ≤ máxima; confirmação explícita; sem cobrança; escalar em
  vulnerabilidade) e **direcionamento**: tools só quando a cliente pede, um passo por resposta, nunca a bateria completa; no primeiro contato com
  gatilho, usa os números do gatilho sem tools; apresenta opções card-first; usa `parcela_alvo` quando a cliente diz um valor; parágrafos curtos
  com **negrito** nos valores.
- **Base de conhecimento (`conhecimento/`):** política de renegociação, FAQ e glossário em Markdown, busca por palavra-chave (sem embeddings) via
  `consultar_conhecimento`; trechos com cara de instrução são removidos antes de sair (o conteúdo é evidência, nunca comando). Dados financeiros
  da cliente nunca passam por aqui.

### 4.6 Guardrails em três camadas (`zera_agent/guardrails.py` + Model Armor)

| Camada | Callback do ADK | O que faz |
|---|---|---|
| **Entrada** | `before_model_callback = guardrail_entrada` | Model Armor (opcional, `ZERA_MODEL_ARMOR=1`); injeção/jailbreak; conteúdo codificado (morse, base64); engenharia social; fora de escopo (resposta fixa, modelo **não é chamado**); PII redigida (CPF, telefone, cartão, e-mail); sinais de vulnerabilidade → escalonamento; validação da frase de consentimento; **escalonamento forçado após 3 bloqueios** na sessão. |
| **Tool** | `before_tool_callback = exigir_consentimento` | Tools com efeito só rodam com a confirmação humana registrada; recusa → `acao_recusada` e `bloqueios_consentimento++`. |
| **Números** | `after_tool_callback = registrar_numeros` | Guarda `numeros_sessao` (válidos a sessão inteira) e os invalida quando uma tool **muda o estado** (`informar_renda`, `informar_gasto_fixo`, `fechar_acordo`, `acionar_respiro`, `amortizar`, `revogar_consentimento`). Números ditos pela cliente e do gatilho também são permitidos. |
| **Saída** | `after_model_callback = guardrail_saida` | Pressão, promessa, vazamento de prompt, PII e **número fora das tools**: em vez de um selo técnico, a cliente recebe uma mensagem acolhedora ("Quero ter certeza de cada número antes de te passar…") com **"falar com uma pessoa do time" em primeiro lugar**; `escalar_sugerido=True` reordena as sugestões; o bloqueio fica registrado só na observabilidade do backend. |

Golden set de ataques em `tests/test_guardrails_ataques.py`.

### 4.7 API (`api/main.py`)

| Grupo | Rotas | LLM? | Notas |
|---|---|---|---|
| Saúde/operação | `GET /health` `GET /ready` `GET /metrics` `POST /simular_tempo` `GET /gatilhos/{id}` `POST /reset/{id}` | não | `/ready` confirma que a fonte responde; `/metrics` = p50/p95 e FinOps (backend); reset = LGPD |
| Perfis e experiência | `GET /v1/clientes`, `…/perfil`, `…/preferencias`, `…/proativa`, `…/experiencia`, `POST …/experiencia/evento` | só ASK_WHY/ASK_QUESTION | perfis do cluster-alvo com `renda_media`/`renda_fonte`/`meses_com_renda`; contrato estruturado |
| Conversa | `GET /chat/inicio` · `POST /chat` · `POST /chat/stream` | sim (exceto abertura e saudações) | abertura determinística (contexto + 3 proteções + sugestões); **roteamento determinístico** de cumprimento/agradecimento/despedida (0 tokens); stream NDJSON com um evento por linha: `etapa` · `llm` · `tool_call` · `tool_result` · `card` · `texto` · `hitl` · `guardrail` · `erro` · `fim` |
| Contratação | `POST /chat/contratar` · `POST /chat/confirmar(/stream)` | não (botão) / só na via do ADK | `btn_…` executa no motor; `request_id` do ADK retoma a invocação pausada |

A **trilha de etapas** (Entender → Opções → Escolher → Confirmar no app → Acompanhar) é derivada no backend das tools chamadas e do HITL (`ETAPAS`),
e só avança quando a cliente pede a ação — a UI apenas reflete.

### 4.8 UI (`ui/`)

React 19 + Vite 8 + Tailwind 4, paleta Itaú, servida pela própria API (mesma origem, sem CORS aberto). Telas: perfis (fonte e rótulos),
onboarding, preferências (consentimento), home com balão proativo no botão flutuante, experiência guiada (renderiza por `response_type`),
e a **conversa** (`Chat.tsx`): trilha de etapas, chips de tool, cards do motor (raio-X, capacidade, prioridades, cenários com botão **Contratar** por
opção — "Melhor para você" / "Melhor para o que você pediu" —, acordo), **card HITL** ("Nada é executado sem a sua confirmação aqui — este é o seu
passo."), sugestões de próximo passo e persistência da conversa ao navegar. O chat é sempre alcançável (botão flutuante, balão, link "Conversar",
texto digitado na tela guiada) e nenhum selo de guardrail, custo ou métrica aparece para a cliente.

### 4.9 Observabilidade e FinOps (`zera_agent/observabilidade.py`) — só no backend

- **Traces:** OTel do ADK (`invocation`, `agent_run`, `call_llm`, `execute_tool`) + spans próprios (`motor.*`, `agente.turno`) → Telemetry API → **Cloud Trace**.
- **Métricas:** `workload.googleapis.com/zera.*` (`zera.hitl_pedido{tool}`, `zera.hitl_resposta{confirmed}`, `zera.chat_roteado`, `zera.evento`, `zera.transicao`,
  `zera.guardrail_bloqueio{camada,tipo}`, `zera.llm.*`) → **Cloud Monitoring**; métricas de log e alerta 5xx via `infra/observabilidade.sh`.
- **Logs:** JSON estruturado com request id e trace id (`http`, `chamada_llm`, `transicao`, `guardrail`) → **Cloud Logging**.
- **FinOps:** tokens × preço por chamada, `custo_da_jornada(jornada_id)`, `/metrics.finops`, lote para `zera.telemetria`; orçamento de billing 50/90/100%.
  Referência: fluxo guiado = 0 tokens; jornada com "por que" + 2 perguntas ≈ US$ 0,002.

---

## 5. Integrações (Google Cloud)

| Serviço | Como é usado | Configuração relevante | Justificativa |
|---|---|---|---|
| **Vertex AI — Gemini 3.8 Flash** | Modelo do `LlmAgent` via ADK | `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_GENAI_USE_ENTERPRISE=1`, `GOOGLE_CLOUD_LOCATION=global`, `ZERA_MODEL=gemini-3.8-flash` (fallback `gemini-2.5-flash`); credencial = identidade do serviço, sem chave | Governança e observabilidade do Vertex; Flash = latência 1–4 s e custo baixo; o endpoint `global` é onde a família 3.x é servida (404 em `us-central1`) |
| **Agent Development Kit (ADK 2.10)** | `LlmAgent`, `FunctionTool(require_confirmation)`, `Runner`, `InMemorySessionService`, callbacks | Mesmo agente no `adk web`, no `/chat` e no explicador | HITL nativo, callbacks de guardrail e sessões prontas; `VertexAiSessionService` (Agent Engine) é troca de uma linha para escala horizontal (P1) |
| **Model Armor** | Sanitização de prompt e resposta | Template `zera-guardrails` (`infra/setup_gcp.sh`), `ZERA_MODEL_ARMOR=1` | Camada gerenciada de RAI em cima dos guardrails em código |
| **BigQuery + BigQuery ML** | Camada de dados `zera.*`, k-means, estado/eventos/telemetria | `publicar_bq.py` idempotente; partição/cluster; leitura por sessão ≈ KB; streaming insert para estado/eventos | Roda onde os dados estão, sem mover dados; k-means auditável (`ML.EVALUATE`); Firestore não está liberado no projeto → estado append-only no BigQuery |
| **Cloud Run** | Serviço único (API + agente + UI) | `us-central1`, min 1 / **max 1**, 1 vCPU / 1 GiB, concurrency 40, timeout 300 s, cpu-boost, `--allow-unauthenticated` (demo), identidade padrão de computação | Um deploy, uma URL, custo previsível; 1 instância mantém sessões do ADK e cache em processo consistentes |
| **Cloud Build + Artifact Registry** | `gcloud run deploy --source` com Dockerfile multi-stage (Node build → Python slim, usuário sem privilégio) | `--image` aponta para o repositório já existente (o projeto não permite criar outro); `python -c "import api.main"` falha o build se faltar módulo | Build reproduzível; erros de dependência aparecem no build, não em runtime |
| **Cloud Trace / Monitoring / Logging (Telemetry API)** | Traces e métricas OTel; logs JSON; métricas de log; alerta 5xx | `ZERA_OTEL_GCP=1`, `ZERA_LOG_JSON=1`, `infra/observabilidade.sh` | Observabilidade como código, só no backend |
| **Cloud Billing Budgets** | Orçamento com alertas 50/90/100% | `infra/observabilidade.sh` | FinOps (item 25) |
| **Cloud Shell / gcloud / bq** | Operação: publicar dados, exportar amostra e snapshot, deploy, smoke test | `infra/deploy_app.sh`, `infra/smoke_prod.sh`, `infra/conceder_dataset.py` | Runbook em `infra/producao.md` |
| **P1 (desenhado, não ligado)** | Agent Engine Sessions/Memory Bank; scheduled query (Data Transfer) + Pub/Sub para gatilhos diários; Data Policy/DLP para mascaramento; Dataform para versionar o SQL; Gen AI Evaluation para o golden set | — | Ver §9 |

**Sistemas transacionais do banco** (contratação, débito automático, boleto) são simulados no MVP e marcados como tal na interface; o ponto de
integração é `fechar_por_cenario`/`criar_acordo_de_cenario` — o acordo já nasce com componente por dívida, termos e CET.

---

## 6. Fluxos principais

**A. Carga de dados (uma vez, idempotente).** `publicar_bq.py` → `zera_tabelas.sql` (extrato particionado, features, perfil, dívidas) →
`clusterizacao.sql` (`CREATE MODEL` k-means, `ML.PREDICT`, índice de endividamento, `perfis_demo`). O deploy exporta o resultado para
`dados/snapshot_bq/` com a credencial de quem publica.

**B. Proatividade.** Home chama `GET /proativa` → `detectar_gatilhos` sobre o perfil → 7 pré-condições → `PROACTIVE_MESSAGE` ("Diminua suas parcelas")
ou `{silent, checks, reason}`. Nada é enviado sem a permissão dada nas preferências.

**C. Um turno de conversa.** `POST /chat/stream` → roteamento determinístico (saudação/agradecimento → resposta fixa, 0 tokens) → senão `Runner.run_async`
→ `guardrail_entrada` → Gemini decide (ou não) chamar tools → `exigir_consentimento` → tool no motor → `registrar_numeros` → `guardrail_saida` →
eventos NDJSON (`etapa`, `tool_call`, `tool_result`, `card`, `texto`, `fim`) renderizados conforme chegam.

**D. Contratar pelo botão (via determinística).** Card de cenários → **Contratar C1** → `POST /chat/contratar` valida `state["cenarios"]` → card HITL
(`btn_…`) → **Confirmo a contratação** → `POST /chat/confirmar` → consentimento `canal=botao_app` → `fechar_por_cenario` → eventos `etapa` (Confirmar no app
→ Acompanhar), `card acordo`, `texto` → estado persistido (BigQuery/JSON).

**E. Contratar quando o modelo chama `fechar_acordo` (HITL nativo).** ADK emite `adk_request_confirmation` e pausa → card HITL com os números da sessão →
`POST /chat/confirmar` com `FunctionResponse` → tool executa (ou `acao_recusada`) → consentimento `canal=hitl_app` + frase.

**F. Dado insuficiente.** Perfil sem entradas → `get_perfil_financeiro` devolve `renda_conhecida=false` → tools de cálculo recusam → a zera.ai pergunta →
`informar_renda(valor)` → `numeros_sessao` reiniciam → tudo recalculado com a fonte "informada pela cliente".

**G. Bloqueio de guardrail na saída.** Número fora das tools → resposta substituída pela mensagem acolhedora com "falar com uma pessoa" em primeiro lugar →
`zera.guardrail_bloqueio` + evento no backend → sugestões reordenadas. A cliente nunca vê um selo técnico.

**H. Deploy.** `infra/deploy_app.sh`: pré-checagem do BigQuery → snapshot → Cloud Build → Cloud Run com as variáveis de produção → detecção de 403 →
`infra/smoke_prod.sh <URL>` valida health/ready, perfis, proatividade, experiência, chat com Gemini, botão Contratar → HITL → recusa, reset.

---

## 7. Decisões técnicas e justificativas

| # | Decisão | Alternativas consideradas | Por que assim | Consequências |
|---|---|---|---|---|
| D1 | **Motor determinístico separado do LLM**; o modelo só chama tools e explica | Deixar o Gemini calcular com *code execution*; prompt com fórmulas | Exatidão e auditabilidade; testes unitários sobre as fórmulas; `numeros_permitidos` fecha o ciclo com o guardrail de saída | O prompt precisa direcionar o modelo a **usar** as tools (regras de direcionamento); custo de tokens menor |
| D2 | **Google ADK** com `FunctionTool(require_confirmation=True)` para HITL | Implementar a pausa/retomada à mão; LangGraph | HITL nativo, sessões, callbacks e tracing prontos; o mesmo agente roda no `adk web`, na API e no explicador | Dependência do ciclo do ADK (v2.10); `InMemorySessionService` exige 1 instância (ou trocar por `VertexAiSessionService`) |
| D3 | **Botão "Contratar" determinístico** além do HITL do modelo | Confiar só na decisão do modelo de chamar `fechar_acordo` | O modelo às vezes explica em vez de agir; o botão garante o caminho de contratação sem tokens e com os números do motor | Duas vias produzem o mesmo card e os mesmos eventos; `canal` distingue `botao_app` de `hitl_app` |
| D4 | **Roteamento determinístico antes do agente** (saudações, agradecimentos, abertura) e **trilha de etapas derivada das tools** | Enviar tudo ao modelo | UX previsível, 0 tokens, e a sequência HITL só aparece quando a cliente realmente entra no fluxo | Regex pt-BR mantida em `api/main.py`; tudo o mais vai ao modelo |
| D5 | **Números válidos por sessão, invalidados quando o estado muda** | Reset a cada turno (gerou falsos "número fora das tools") | A cliente pergunta sobre um valor mostrado dois turnos atrás; o valor continua verdadeiro até uma mudança de estado | `MUTADORES_DE_ESTADO` precisa listar toda tool que altera perfil/acordo |
| D6 | **Bloqueio de guardrail vira hand-off humano acolhedor**, sem selo na UI | Mostrar "Guardrail de saída: número fora das tools" | Quadro itens 20/25: encaminhar é saída correta; a cliente não deve ver linguagem técnica | O bloqueio continua registrado (métrica + evento) para monitoramento |
| D7 | **Renda = média mensal das entradas; ausente → perguntar** | Imputar pela mediana do cluster; usar salário fixo da persona | Fonte real e explicável; imputar decidiria pela cliente | Perfis sem entradas exigem um turno a mais (a UI oferece o chip "preciso da sua renda") |
| D8 | **Pergunta de gasto fixo guiada por dados** (`sinais_gastos_invisiveis`) | Perguntar sempre | Não perguntar o que já sabemos (spec §5.1); a pergunta traz os números reais que a motivaram | Limiares em `politicas.py` (30% / 55%) documentados e ajustáveis |
| D9 | **Múltiplos acordos** com parcela ativa como compromisso | Um acordo por cliente | Realidade: dívida nova ou o que ficou fora do acordo; a capacidade já desconta o que foi contratado | `acordos` em lista; `avancar_tempo` processa todos |
| D10 | **BigQuery + BigQuery ML** para segmentação (k-means) e estado | Segmentação em pandas fora do BQ; Firestore para estado | Processa onde os dados estão; k-means auditável; Firestore não liberado no projeto | Estado append-only (LGPD por snapshot `apagado`); `segmentacao.py` espelha o SQL para o modo local |
| D11 | **Snapshot embarcado + leitura sem job** como fallbacks do BigQuery | Exigir IAM completo; mock | A identidade de runtime do projeto do evento não tem `bigquery.jobs.create` e a conta pessoal não altera IAM; produção precisava funcionar mesmo assim, com dado real | Ordem query → tabelas → snapshot; fonte sempre rotulada; `conceder_dataset.py` libera o modo ao vivo sem admin |
| D12 | **Um serviço no Cloud Run, 1 instância** | API + agente separados; Agent Engine desde já | Uma URL, um deploy, custo previsível; sessões e cache em processo sem split-brain | Escala horizontal exige `ZERA_SESSOES=vertex` e estado só no BigQuery (P1) |
| D13 | **Identidade padrão e repositório existente no deploy** | Service account dedicada + repositório novo | O projeto não permite criar SA nem repositório; o script detecta e segue, imprimindo o comando para o admin | `producao.md` registra os papéis mínimos ideais |
| D14 | **Observabilidade só no backend** | Chip de FinOps/guardrail na interface | A cliente não precisa ver tokens ou bloqueios; a banca vê no Cloud Trace/Monitoring e em `/metrics` | Nada de telemetria na UI; `zera.telemetria`/`zera.eventos` para análise |
| D15 | **Amostra local = export real** e fixtures só em testes | Perfil sintético "Cleide" carregado pela API | Regra "nenhum dado mockado"; a persona é o cliente real mais típico do cluster-alvo | Amostra gerada por `exportar_amostra.sql` (via stdin no `bq`) |
| D16 | **Modelo `gemini-3.8-flash` no endpoint `global`**, temperatura 0,2 | Pro; `us-central1` | Latência/custo da classe Flash; a família 3.x é servida em `global` | Fallback `gemini-2.5-flash` por variável; `.env` carregado automaticamente e aviso quando o shell diverge |
| D17 | **Base de conhecimento por palavra-chave**, sem vector store | RAG com embeddings / Vertex AI Search | Três arquivos curtos; simplicidade e zero infraestrutura; trechos com cara de comando são filtrados | Vertex AI Search é evolução natural (P2) |

---

## 8. Segurança, privacidade e IA responsável

- **Consentimento** explícito e registrado (`canal`, frase, timestamp); preferências de proatividade e Open Finance; `revogar_consentimento` e `POST /reset` (LGPD, estado append-only com `apagado=true`).
- **Contexto mínimo:** agregados de 12 meses no prompt, nunca o extrato bruto; PII redigida na entrada e na saída; identidades fictícias (pseudônimos determinísticos).
- **Guardrails em código + Model Armor**; golden set de ataques (injeção, morse/base64, engenharia social, fora de escopo, PII, consentimento forjado).
- **Runtime:** container sem privilégio (uid 10001), 1 worker, timeouts, `ZERA_DOCS=0`, sem segredos em variáveis (credencial = identidade do serviço).
- **Tom:** sem cobrança, sem pressão, sem julgamento; vulnerabilidade → humano; "nenhuma opção" com diagnóstico e caminhos.

## 9. Qualidade e operação

- **94 testes sem rede** (`tests/`): motor (fórmulas e sensibilidade), fluxo ponta a ponta, agente com HITL (`FakeLlm`), API de chat (renda, botão Contratar, roteamento), guardrails (ataques), dados (amostra real, snapshot), conhecimento. Rodam no Mac (`uv run pytest -q`) e no CI local do time.
- **Idempotência:** SQL `CREATE OR REPLACE`/`IF NOT EXISTS`; segundo `CONFIRM` não duplica acordo; redeploy mantém a URL (versão = hash do commit).
- **Runbook** (`infra/producao.md`): deploy, smoke test, observabilidade, rollback (`update-traffic`), falhas conhecidas e o que fazer.
- **Ambiente:** 12-factor por variáveis (`zera_agent/env.demo`), mesmo código local/produção; `ZERA_FONTE`, `ZERA_ESTADO`, `ZERA_OTEL_GCP` trocam integrações sem alterar código.

## 10. Limitações conhecidas e evolução

| Item | Hoje | Próximo passo |
|---|---|---|
| Sessões do agente | em memória, 1 instância | `VertexAiSessionService` + Agent Engine Memory Bank; `max-instances > 1` |
| Gatilhos | calculados na leitura do perfil | scheduled query diária (BigQuery Data Transfer) + Pub/Sub → serviço |
| Contratação | simulada no motor (acordo com termos/CET) | integração com o sistema transacional e débito automático reais |
| Dívidas | derivadas do extrato por regras (rotuladas) | cadastro real de contratos; Open Finance para outras instituições |
| Segmentação | k-means k=4 (validar com `ML.EVALUATE`) | revisão de k, estabilidade dos centróides, Dataform para versionar o pipeline |
| Avaliação do agente | golden set em testes | Gen AI Evaluation / `adk eval` com rubrica (tom, números, escalonamento) |
| Base de conhecimento | busca por palavra-chave | Vertex AI Search (RAG) sobre política e FAQ |
| Mascaramento | PII por regex + pseudônimos | BigQuery Data Policy / DLP nas colunas de descrição |

## 11. Rastreabilidade (onde está cada coisa)

| Tema | Arquivos |
|---|---|
| Motor | `motor/{politicas,capacidade,priorizacao,alocacao,consolidacao,beneficios,simulacao,gatilhos,modelos}.py` |
| Dados | `dados/{loader,segmentacao,publicar_bq,exportar_snapshot_bq}.py`, `dados/sql/{zera_tabelas,clusterizacao,exportar_amostra}.sql`, `dados/amostra_bq_extrato_sintetico.csv` |
| Agente | `zera_agent/{agent,tools,prompts,guardrails,contexto,experiencia,observabilidade}.py`, `conhecimento/` |
| API e UI | `api/main.py`, `ui/src/{App.tsx,api.ts,types.ts,screens/*,components/ui.tsx}` |
| Infra | `Dockerfile`, `infra/{deploy_app.sh,smoke_prod.sh,conceder_dataset.py,observabilidade.sh,setup_gcp.sh,producao.md}` |
| Testes | `tests/test_{motor,fluxo_agente,api_chat,experiencia,guardrails_ataques,dados,conhecimento}.py`, `tests/fake_llm.py`, `tests/fixtures/` |
