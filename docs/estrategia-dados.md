# Estratégia de dados — zera.ai (projeto `batalha-time-03-vhxk`)

**Regra número um: nenhum dado mockado.** A aplicação só conhece a base do evento (`hackathon_dados.extrato_sintetico`) e o que é
derivado dela por regras explícitas e versionadas (SQL em `dados/sql/`, espelhadas em `dados/segmentacao.py`). O perfil sintético
"Cleide" que existia no início virou **fixture de teste** (`tests/fixtures/`), nunca carregado pela API.

## Por que o agente não lê o extrato bruto

Um turno do agente não pode varrer milhares de lançamentos: custa (BigQuery cobra por bytes lidos), demora e coloca dado bruto
no prompt (risco de PII e de alucinação numérica). O agente lê **1 linha por cliente** (`zera.perfil_cliente`, 12 meses em arrays)
+ as dívidas (`zera.dividas_derivadas`) e o motor calcula em memória (< 10 ms). O extrato bruto só é consultado em fallback.

## Camadas (BigQuery, dataset `zera`, mesma location do dataset do evento)

| Camada | Tabela / modelo | Conteúdo | Atualização |
|---|---|---|---|
| Bruta | `zera.extrato` | cópia particionada por `dia` e **clusterizada por `id_usuario`** + `classe` (renda, dívida, parcela, essencial, assinatura, outros) | `publicar_bq` / scheduled query diária |
| Features | `zera.features_mensais`, `zera.features_cliente` | agregados mensais e por cliente (12 meses): renda, essenciais, parcelas, serviço de dívida, saldo mínimo, sinais de rotativo/empréstimo, CV da renda | idem |
| Segmentação | `zera.kmeans_perfis` (BigQuery ML), `zera.clusters_clientes`, `zera.perfil_clusters` | k-means++ com features padronizadas; índice de endividamento por cluster; `cluster_alvo` | `publicar_bq --so-cluster` |
| Perfis da demo | `zera.perfis_demo` | clientes reais do cluster-alvo, ordenados pela distância ao centróide; medoide = "Cleide"; pseudônimos determinísticos | idem |
| Perfil | `zera.perfil_cliente` | 1 linha por cliente (arrays de 12 meses, `renda_conhecida`, `cv_renda`, `meses_no_vermelho`) | idem |
| Dívidas | `zera.dividas_derivadas` | inferidas do último mês do extrato (saldo negativo → cheque especial; k/N → crediário; descrição → cartão/empréstimo), `fonte=derivada_extrato` | idem |
| Estado | `zera.estado_cliente` | snapshots JSON append-only (acordo, consentimentos, gatilhos, preferências, compromissos, renda informada); "apagar" = snapshot com `apagado=true` (LGPD) | por evento |
| Eventos | `zera.eventos` | eventos de negócio e de guardrail (funil, escalonamentos, bloqueios) → Looker Studio | streaming insert |
| Telemetria | `zera.telemetria` | métricas e custo por chamada ao LLM (FinOps) | lote (best-effort) |

Modo local sem credenciais (`ZERA_FONTE=amostra`): `dados/amostra_bq_extrato_sintetico.csv` é o **export real** da base do evento
(10 mil lançamentos, 1.000 clientes) e a segmentação roda por regras com as mesmas features. A amostra só tem saídas (`tipo=S`) de
um mês: por isso a renda aparece como "não identificada" e a zera.ai **pergunta** — comportamento correto para dados insuficientes.

## Como ligar

```
python -m dados.publicar_bq                 # 1x: tabelas + k-means + perfis_demo (ADC: gcloud auth application-default login)
ZERA_FONTE=bigquery ZERA_ESTADO=bigquery ZERA_TELEMETRIA_BQ=1 uvicorn api.main:app --port 8080
```

## Custos e limites

- Leitura por sessão: 1 query pequena em tabelas clusterizadas (bytes lidos ≈ KB). Sem varrer o extrato por turno.
- k-means: 1 job de treino sobre `features_cliente` (1 linha por cliente); reprocessar diariamente via BigQuery Data Transfer (scheduled query).
- Escrita: streaming insert (estado/eventos/telemetria) — gratuito até a cota, sem tabelas grandes.
- Validar o número de clusters com `ML.EVALUATE` (Davies-Bouldin) antes de afirmar "4 segmentos" na apresentação.
