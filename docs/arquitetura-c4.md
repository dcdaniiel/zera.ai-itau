# zera.ai — Arquitetura (C4 Model)

Projeto `batalha-time-03-vhxk` · região `us-central1` (modelo via endpoint `global`) · Batalha de Agentes Itaú × Google.

Princípio que atravessa os quatro níveis: **o LLM interpreta, pergunta, explica e orquestra; todo número, elegibilidade,
comparação e contratação nasce no núcleo determinístico (`motor/`)** — spec "Agent Behavior & Content Specification v1", §3.

---

## Nível 1 — Contexto do sistema

```mermaid
C4Context
  title zera.ai — contexto
  Person(cliente, "Cliente Itaú", "Pessoa endividada / negativada. Decide e autoriza toda ação financeira.")
  Person(humano, "Atendimento humano", "Recebe escalonamentos (vulnerabilidade, nenhuma opção adequada, falha).")
  System(zera, "zera.ai", "Agente que detecta a anomalia de entrada, decide o que quitar/renegociar e acompanha até o nome limpo.")
  System_Ext(app, "App Itaú", "Home do banco: onboarding, preferências (consentimento) e mensagem proativa.")
  System_Ext(bq, "BigQuery (dados do banco)", "Extrato do cliente e camada semântica zera.* (perfil, dívidas derivadas, estado, eventos).")
  System_Ext(gemini, "Vertex AI / Gemini", "Modelo de linguagem (Gemini 3.8 Flash) + Agent Engine + Model Armor.")
  System_Ext(of, "Open Finance", "Dívidas de outras instituições (consentimento do cliente).")
  System_Ext(tx, "Sistemas transacionais", "Contratação, débito automático e pagamento (simulados no MVP).")
  Rel(cliente, app, "Usa")
  Rel(app, zera, "Abre a experiência / recebe PROACTIVE_MESSAGE", "HTTPS")
  Rel(zera, bq, "Lê perfil agregado (1 query/sessão); grava estado e eventos", "BigQuery API")
  Rel(zera, gemini, "Explica e responde perguntas livres (atrás dos guardrails)", "Vertex AI")
  Rel(zera, of, "Consolida dívidas externas", "APIs OF (P2)")
  Rel(zera, tx, "Envia contratação só após CONFIRM", "API (mock)")
  Rel(zera, humano, "Escala")
```

## Nível 2 — Containers

```mermaid
C4Container
  title zera.ai — containers (um serviço no Cloud Run + dados no BigQuery)
  Person(cliente, "Cliente")
  System_Boundary(zera, "zera.ai") {
    Container(ui, "App mobile (UI)", "React 19 · Vite · Tailwind 4", "Renderiza por response_type: SUMMARY, QUESTION, STATUS, OPTION_DETAIL, OPTIONS_COMPARISON, TEXT, TERMS_REVIEW, CONFIRMATION_REQUEST, SUCCESS, ERROR. Modo demo offline com os mesmos números.")
    Container(api, "API", "FastAPI · Python 3.12 · Cloud Run", "/v1/clientes/{id}/preferencias · /proativa · /experiencia · /experiencia/evento · /chat · /simular_tempo. Serve a UI em /.")
    Container(exp, "Orquestrador da experiência", "zera_agent/experiencia.py", "Máquina de estados IDLE→…→COMPLETED, decision engine ASK/TOOL/CONFIRM/RESPOND, proatividade (pré-condições), contrato estruturado.")
    Container(agent, "Agente conversacional", "Google ADK 2.x · Gemini 3.8 Flash", "Explica opções e responde perguntas livres. Tools = wrappers do núcleo. Guardrails de entrada e saída (callbacks) + Model Armor.")
    Container(motor, "Núcleo determinístico", "Python puro · sem LLM · 100% testado", "capacidade, priorização, alocação (quitar/renegociar 12–36x/manter), consolidação hoje×nova, benefícios/claims, termos/CET, acordo, respiro, amortização, gatilhos.")
    Container(ctx, "Contexto do cliente", "zera_agent/contexto.py", "Perfil + capacidade em memória, estado (acordo, consentimentos, gatilhos, preferências), relógio de simulação.")
    ContainerDb(estado, "Estado & eventos", "BigQuery zera.estado_cliente / zera.eventos (append-only) — ou JSON local", "Snapshots do estado; eventos de negócio e de guardrail → Looker Studio.")
  }
  ContainerDb(dados, "Dados do banco", "BigQuery hackathon_dados.extrato_sintetico → zera.extrato (partição+cluster) → zera.features_mensais → zera.perfil_cliente / zera.dividas_derivadas", "Camada semântica; 1 linha por cliente.")
  System_Ext(gemini, "Vertex AI (Gemini, Agent Engine, Model Armor)")
  System_Ext(sched, "Cloud Scheduler + Cloud Run Job", "detector de gatilhos diário (anomalias, D-3, pré-negativação)")
  Rel(cliente, ui, "usa", "HTTPS")
  Rel(ui, api, "JSON: ação + payload → resposta estruturada", "HTTPS")
  Rel(api, exp, "evento(acao, payload)")
  Rel(exp, motor, "situacao_hoje · montar_cenarios · validar_beneficios · termos · criar_acordo_de_cenario")
  Rel(exp, agent, "explicador(pergunta, numeros_permitidos) — só EXPLAINING / ASK_QUESTION")
  Rel(agent, motor, "tools determinísticas")
  Rel(agent, gemini, "generate_content", "Vertex AI, location global")
  Rel(exp, ctx, "lê/grava estado")
  Rel(agent, ctx, "lê/grava estado")
  Rel(ctx, dados, "carregar_perfil (1 query/sessão)", "BigQuery")
  Rel(ctx, estado, "snapshot + eventos", "streaming insert")
  Rel(sched, estado, "grava gatilhos")
```

## Nível 3 — Componentes

### 3a. Núcleo determinístico (`motor/`) — "Deterministic services" da spec

```mermaid
C4Component
  title motor/ — núcleo determinístico (nenhuma função chama LLM)
  Container_Boundary(m, "motor/") {
    Component(pol, "politicas.py", "dict", "Parâmetros de negócio fictícios e alavancas de experimento: percentil da sobra, colchão, fator de segurança, prazos 12/18/24/36, faixas de desconto, débito automático 2%.")
    Component(cap, "capacidade.py", "calcular_capacidade", "sobra P25 − colchão → sobra segura → parcela máxima; meses fracos → respiros.")
    Component(pri, "priorizacao.py", "priorizar_dividas", "custo mensal × consequência (negativação, corte).")
    Component(alo, "alocacao.py", "montar_cenarios", "Enumera quitar / renegociar_N / manter por dívida; filtra por caixa, parcela máxima, respiros; ranqueia: sai da negativação > custo > parcela; parcela de conforto por perfil de risco (CV da renda).")
    Component(con, "consolidacao.py", "situacao_hoje · resumo_cenario · termos", "Hoje × nova opção em UM pagamento; CET; 1º vencimento; dívidas incluídas; desconto de débito automático.")
    Component(ben, "beneficios.py", "validar_beneficios · claims · tradeoffs · criterio_recomendacao", "LOWER_MONTHLY_PAYMENT, LOWER_TOTAL_COST, CLEAN_NAME, SINGLE_PAYMENT — claims só de benefício validado; critérios explicáveis de recommended=true.")
    Component(sim, "simulacao.py", "Price · criar_acordo_de_cenario · registrar_pagamento · acionar_respiro · amortizar", "Acordo com componentes por dívida; respiro sem mora; amortização no componente mais pesado.")
    Component(gat, "gatilhos.py", "detectar_gatilhos", "dinheiro_extra (anomalia ≥ 40% da renda mediana ou 13º/IRPF/FGTS/PLR), risco_parcela (D-3), pre_negativacao.")
    Component(mod, "modelos.py", "dataclasses", "Divida (instituição), PerfilFinanceiro, Capacidade, Acordo; brl(); numeros_de() → numeros_permitidos.")
  }
  Rel(alo, cap, "usa")
  Rel(alo, sim, "Price / faixas")
  Rel(con, sim, "CET, vencimento")
  Rel(ben, con, "compara")
```

### 3b. Orquestrador da experiência + agente (`zera_agent/`)

```mermaid
C4Component
  title zera_agent/ — orquestração, agente e guardrails
  Container_Boundary(z, "zera_agent/") {
    Component(exp, "experiencia.py", "Experiencia", "Estados e transições; decisão ASK (gasto não conhecido) / TOOL (motor) / CONFIRM (ação sensível) / RESPOND; proatividade: permission ∧ trigger ∧ opportunity ∧ benefit ∧ context ∧ action ∧ frequency; contrato {state, response_type, content, options, quick_replies, allowed_actions, requires_confirmation}.")
    Component(ctx, "contexto.py", "Contexto", "Perfil/capacidade em memória; estado; compromissos informados; relógio de simulação; repositórios JSON/BigQuery.")
    Component(agent, "agent.py", "LlmAgent (ADK)", "Zera root (opcional: sub-agentes Diagnóstico/Negociador/Acompanhamento). Gemini 3.8 Flash, temperatura 0,2.")
    Component(tools, "tools.py", "14 function tools", "get_perfil_financeiro, calcular_capacidade, priorizar_dividas, montar_cenarios, simular_planos, comparar_com_padrao, registrar_consentimento, fechar_acordo, status_acordo, acionar_respiro, amortizar, listar_gatilhos, escalar_humano, revogar_consentimento — todas devolvem numeros_permitidos.")
    Component(gr, "guardrails.py", "callbacks", "ENTRADA: Model Armor + injeção/jailbreak, engenharia social, fora de escopo → bloqueia sem chamar o modelo; PII redigida; vulnerabilidade → tom + escalar. FERRAMENTAS: consentimento por ação (uso único). SAÍDA: pressão, promessa, vazamento de prompt, fora de escopo → resposta fixa; PII; números fora das tools → [valor a confirmar].")
    Component(pr, "prompts.py", "instruções", "Regras invioláveis: números só das tools; parcela ≤ máxima; confirmação explícita; sem cobrança; escalar em vulnerabilidade.")
  }
  Rel(exp, ctx, "estado")
  Rel(exp, agent, "explicador (só texto)")
  Rel(agent, tools, "function calling")
  Rel(agent, gr, "before/after model, before/after tool")
  Rel(tools, ctx, "perfil, capacidade, acordo")
```

### 3c. UI (`ui/src`)

| Componente | Responsabilidade |
|---|---|
| `api.ts` | Cliente HTTP (`/v1/clientes/{id}/…`) com fallback automático para o modo demo; `VITE_MOCK=1`, `VITE_CLIENTE_ID` |
| `mock.ts` | Mesma máquina de estados e contrato, com os números do motor (plano B offline / protótipo clicável) |
| `screens/Onboarding.tsx` | "Conheça a zera.ai" + Preferências (proactive_permission, Open Finance) → `POST /preferencias` |
| `screens/Home.tsx` | Home do banco; mostra `PROACTIVE_MESSAGE` só se a API não devolveu `silent` |
| `screens/Experiencia.tsx` | Renderer por `response_type` (10 telas do design), STATUS com checklist, input livre → `ASK_QUESTION`, badge de guardrail |
| `components/ui.tsx` | Header Itaú, tiles, toggles, cards, chips (paleta Itaú) |

## Nível 4 — Código: o contrato que amarra tudo

```text
Ação do usuário ──► POST /v1/clientes/{id}/experiencia/evento {acao, payload}
                      │
                      ▼
   Experiencia.evento()  ── decision engine ──►  ASK      → QUESTION (quick_replies / input)
                                            ├──►  TOOL     → motor.* → OPTION_DETAIL / OPTIONS_COMPARISON / TERMS_REVIEW
                                            ├──►  CONFIRM  → CONFIRMATION_REQUEST (requires_confirmation=true)
                                            ├──►  EXECUTE  → motor.criar_acordo_de_cenario → SUCCESS
                                            └──►  RESPOND  → TEXT (LLM via explicador, guardrails) / ERROR
                      │
                      ▼
   {state, response_type, content{title, description}, options[], quick_replies[], allowed_actions[],
    requires_confirmation, benefit, claims[], tradeoffs[], terms, final_terms, status{steps}, numeros_permitidos[]}
```

Regras codificadas (spec → código):

| Spec | Onde |
|---|---|
| §2 evento ≠ recomendação; §7 pré-condições de proatividade | `Experiencia.avaliar_proatividade` (`checks`) |
| §5.1 não perguntar o que já sabemos; §5.3 inferência crítica → confirmar | `_start` (renda/dívidas do extrato; pergunta única sobre gasto fora do extrato) |
| §5.2 dado financeiro só de fonte confiável | tools/experiência só leem `motor` + `Contexto` (BigQuery/CSV); prompt proíbe cálculo |
| §5.4 ação sensível → consequência + confirmação | `_confirmacao` (trade-offs, termos finais) → `_confirm` |
| §10 claims validados | `motor/beneficios.validar_beneficios` + `claims` |
| §11 recommended por critério determinístico | `motor/alocacao` (ranking) + `criterio_recomendacao` |
| §16 débito automático recalcula tudo | `termos(..., debito_automatico)` em `_confirmacao` |
| §17 só CONFIRM autoriza | `_confirm` exige `AWAITING_CONFIRMATION`; selecionar/explicar nunca cria acordo |
| §19 AT01–AT10 | `tests/test_experiencia.py` |
| Guardrails RAI (entrada → modelo → saída) | `zera_agent/guardrails.py` + `tests/test_guardrails_ataques.py` |

## Deploy e dados

- **Runtime**: um serviço Cloud Run (`infra/deploy_app.sh`): FastAPI serve a UI (`ui/dist`) e a API; ADK + Gemini via Vertex AI (`GOOGLE_CLOUD_LOCATION=global`); opcional Agent Engine (`infra/deploy_agent_engine.sh`).
- **Dados**: `docs/estrategia-dados.md` — BigQuery como única camada (Firestore não liberado): extrato clusterizado → features → `perfil_cliente` (1 query por sessão) → estado/eventos append-only.
- **Observabilidade**: eventos (`cenarios_propostos`, `opcao_selecionada`, `acordo_fechado`, `guardrail_bloqueio`, `nenhuma_opcao_adequada`, `erro_experiencia`, `proativa_enviada`) → `zera.eventos` → Looker Studio; Cloud Logging/Trace via ADK.
