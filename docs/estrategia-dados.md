# Estratégia de dados — Zera (projeto `batalha-time-03-vhxk`, us-central1)

**Decisão:** BigQuery é a única camada de dados (analítica **e** de serving). Firestore não está liberado no projeto; nada de banco extra.
O agente **não lê transações brutas por turno**: lê **1 linha agregada por cliente** e grava estado/eventos **append-only**.

## Por que não consultar o extrato bruto direto do agente

| Opção | Latência por turno | Custo | Risco | Veredito |
|---|---|---|---|---|
| Query no `hackathon_dados.extrato_sintetico` a cada tool | 1–3 s (scan da tabela inteira; sem partição/cluster) | scan completo por chamada | lento na demo, PII bruta no agente | ❌ |
| **Cópia `zera.extrato` particionada por dia e clusterizada por `id_usuario`** | 0,3–0,8 s | só os blocos do cliente | ok como fallback | ✅ fallback |
| **`zera.perfil_cliente` (1 linha/cliente, arrays de 12 meses) + `zera.dividas_derivadas`** | ~0,3 s, **1 query por sessão**, depois memória | mínimo | dados agregados = minimização (LGPD) | ✅ **principal** |
| Export CSV/Parquet no GCS lido pelo Cloud Run | ~0 | ~0 | dados param no tempo; ok só para a persona | ✅ persona da demo (`dados/cleide_12m.csv`) |
| Vertex AI Feature Store / AlloyDB / Cloud SQL | — | — | overkill para 2 dias | ❌ |

## Formato

**Fonte da verdade (analítica):** `zera.extrato` — cópia CTAS do extrato do evento, `PARTITION BY dia`, `CLUSTER BY id_usuario`, colunas normalizadas (`tipo` S/E, `descr` minúsculo, `vlr` absoluto, `macro`/`micro`).

**Camada semântica (o que o motor consome):**
- `zera.features_mensais` — por `id_usuario × anomes`: renda (tipo E), essenciais (casa, mercado, transporte público, combustível, educação, saúde), parcelas (k/N), serviço da dívida (juros/mínimo/empréstimo por descrição), assinaturas, saldo mínimo, lançamentos no vermelho, novo comprometimento futuro, créditos atípicos. Materializada; **scheduled query diária**.
- `zera.perfil_cliente` — 1 linha por cliente: `meses[]`, `renda_mensal[]`, `essenciais_mensal[]`, `parcelas_mensal[]` (últimos 12, ordenados), `renda_mediana`, `cv_renda`, `meses_no_vermelho`, `gerado_em`. É exatamente o `PerfilFinanceiro` do motor.
- `zera.dividas_derivadas` — a base do evento não tem cadastro de dívidas; inferimos do último mês: cheque especial = pior saldo negativo; crediário = estoque de parcelas k/N; cartão rotativo / empréstimo = lançamentos com descrição financeira (taxas fictícias em `motor/politicas.py`). Substituível pelo cadastro real do banco sem mudar o motor.

**Estado e eventos (append-only, streaming insert):**
- `zera.estado_cliente` — snapshot JSON por gravação (acordo com componentes, consentimentos, gatilhos, memória); leitura = último snapshot (`zera.estado_atual`); direito de esquecer = snapshot `apagado=true`.
- `zera.eventos` — negócio (cenários propostos, consentimento, acordo, respiro, amortização, escalonamento) e **guardrail** (`guardrail_bloqueio`) com `variante_experimento` → Looker Studio.

**Anomalias (o gatilho da jornada):** `creditos_atipicos` em `features_mensais` (crédito ≥ 40% da renda mediana fora do padrão, ou descrição 13º/IRPF/FGTS/PLR) — mesmo critério de `motor/gatilhos.py`.

## Como ligar

```bash
infra/setup_gcp.sh                       # cria zera.* (dados/sql/zera_tabelas.sql + eventos.sql)
# zera_agent/.env
ZERA_FONTE=bigquery                      # perfil_cliente + dividas_derivadas; fallback: extrato clusterizado + derivar_dividas()
ZERA_ESTADO=bigquery                     # estado_cliente + eventos (senão JSON local em .zera_state/)
ZERA_FONTE=bigquery python -m dados.bq_perfil --cliente <id_usuario> --extra 2800   # QA de um cliente real
```

Persona da demo: a Cleide sintética (`ZERA_FONTE=csv`) garante os números ensaiados; um `id_usuario` real (ex.: `2e85f8ba-…`, `595db4d9-…`) entra pelo caminho BigQuery para mostrar que é a mesma esteira.

## Custos e limites
- 1.000 clientes × ~12 meses: tabelas de KB/MB — custo de query desprezível; clustering garante leitura só do cliente.
- Streaming insert: linhas disponíveis para leitura em segundos; sem update/delete imediato — por isso snapshots append-only.
- Minimização: o agente recebe agregados e IDs pseudonimizados; o extrato bruto nunca entra no prompt.
