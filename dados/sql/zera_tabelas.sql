-- ============================================================================
-- Camada de dados do zera.ai no BigQuery  (projeto ${PROJETO}, dataset ${DATASET})
-- ============================================================================
-- Script BigQuery (multi-statement). Rode com:
--   python -m dados.publicar_bq            (publica a persona, roda este script e a clusterização)
--   ou: bq query --use_legacy_sql=false --project_id=${PROJETO} < dados/sql/zera_tabelas.sql
--
-- Estratégia (docs/estrategia-dados.md): a tabela do evento é a fonte da verdade. O agente NUNCA lê transações
-- brutas por turno: lê 1 linha de `perfil_cliente` (arrays de 12 meses) + dívidas (cadastro ou derivadas).
--   1) extrato       : cópia de hackathon_dados.extrato_sintetico particionada por dia e clusterizada por id_usuario
--   2) features_mensais / features_cliente : o que o motor e a clusterização precisam
--   3) perfil_cliente : 1 linha por cliente (12 meses em arrays) -> 1 leitura por sessão
--   4) dividas_derivadas : dívidas inferidas do extrato (regras explícitas, rotuladas fonte=derivada_extrato)
--   5) estado_cliente / eventos / telemetria : estado append-only (Firestore não está liberado), métricas e FinOps
-- A clusterização (BigQuery ML k-means) está em dados/sql/clusterizacao.sql e gera `perfis_demo` (clientes reais do cluster-alvo).
-- Nada aqui é mock: não existe dado sintético na aplicação — só a base do evento e o que é derivado dela por regras explícitas.

-- ---------- 1) extrato unificado, particionado + clusterizado ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.extrato`
PARTITION BY dia
CLUSTER BY id_usuario AS
WITH bruto AS (
  SELECT CAST(id_usuario AS STRING) AS id_usuario, TIMESTAMP(anomesdia) AS anomesdia, SAFE_CAST(anomes AS INT64) AS anomes,
         CAST(tipo AS STRING) AS tipo, CAST(descr AS STRING) AS descr, CAST(vlr AS FLOAT64) AS vlr,
         CAST(nom_cate_macro AS STRING) AS nom_cate_macro, CAST(nom_cate_micro AS STRING) AS nom_cate_micro,
         SAFE_CAST(saldo_apos AS FLOAT64) AS saldo_apos,
         SAFE_CAST(parcela_atual AS INT64) AS parcela_atual, SAFE_CAST(parcela_total AS INT64) AS parcela_total,
         'evento' AS origem
  FROM `${PROJETO}.${DATASET_EVENTO}.extrato_sintetico`
)
SELECT
  id_usuario,
  DATE(anomesdia)                 AS dia,
  anomes,
  UPPER(tipo)                     AS tipo,          -- S = saída, E = entrada
  LOWER(descr)                    AS descr,
  ABS(vlr)                        AS vlr,
  LOWER(nom_cate_macro)           AS macro,
  LOWER(nom_cate_micro)           AS micro,
  saldo_apos,
  parcela_atual,
  parcela_total,
  origem,
  CASE
    WHEN UPPER(tipo) = 'E' THEN 'renda'
    WHEN REGEXP_CONTAINS(LOWER(descr), r'juros|encargo|iof|tarifa|multa|rotativo|minimo|emprest|financ|renegoc|acordo|fatura') THEN 'divida'
    WHEN parcela_total IS NOT NULL THEN 'parcela'
    WHEN LOWER(nom_cate_macro) IN ('casa','mercado','transporte publico','posto de combustivel','educacao','saude','contas e servicos')
         AND LOWER(nom_cate_micro) NOT IN ('jardinagem','lavanderia') THEN 'essencial'
    WHEN LOWER(nom_cate_macro) = 'assinaturas' THEN 'assinatura'
    ELSE 'outros'
  END AS classe
FROM bruto;

-- ---------- 2) features mensais (materializada; agende como scheduled query diária — BigQuery Data Transfer) ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.features_mensais`
PARTITION BY RANGE_BUCKET(anomes, GENERATE_ARRAY(202301, 202812, 1))
CLUSTER BY id_usuario AS
SELECT
  id_usuario, anomes,
  SUM(IF(classe = 'renda', vlr, 0))        AS renda,
  SUM(IF(classe = 'essencial', vlr, 0))    AS essenciais,
  SUM(IF(classe = 'parcela', vlr, 0))      AS parcelas,
  SUM(IF(classe = 'divida', vlr, 0))       AS servico_divida,
  SUM(IF(classe = 'assinatura', vlr, 0))   AS assinaturas,
  SUM(IF(classe = 'outros', vlr, 0))       AS outros,
  SUM(IF(tipo = 'S', vlr, 0))              AS saidas,
  MIN(saldo_apos)                          AS saldo_minimo,
  COUNTIF(saldo_apos < 0)                  AS lancamentos_no_vermelho,
  COUNTIF(classe = 'parcela')              AS qtd_parcelas,
  SUM(IF(parcela_atual = 1, vlr * (parcela_total - 1), 0)) AS novo_comprometimento_futuro,
  COUNTIF(REGEXP_CONTAINS(descr, r'minimo|rotativo'))       AS sinais_rotativo,
  COUNTIF(REGEXP_CONTAINS(descr, r'emprest|financ|consign'))AS sinais_emprestimo,
  COUNT(*)                                 AS lancamentos
FROM `${PROJETO}.${DATASET}.extrato`
GROUP BY id_usuario, anomes;

-- ---------- 3) perfil_cliente: 1 linha por cliente, últimos 12 meses em arrays (ordenados) ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.perfil_cliente`
CLUSTER BY id_usuario AS
WITH ult AS (
  SELECT id_usuario, anomes, renda, essenciais, parcelas, servico_divida, saldo_minimo, saidas,
         ROW_NUMBER() OVER (PARTITION BY id_usuario ORDER BY anomes DESC) AS rn
  FROM `${PROJETO}.${DATASET}.features_mensais`
)
SELECT
  id_usuario,
  ARRAY_AGG(FORMAT('%d-%02d', DIV(anomes, 100), MOD(anomes, 100)) ORDER BY anomes) AS meses,
  ARRAY_AGG(renda          ORDER BY anomes) AS renda_mensal,
  ARRAY_AGG(essenciais     ORDER BY anomes) AS essenciais_mensal,
  ARRAY_AGG(parcelas       ORDER BY anomes) AS parcelas_mensal,
  ARRAY_AGG(servico_divida ORDER BY anomes) AS servico_divida_mensal,
  ARRAY_AGG(saldo_minimo   ORDER BY anomes) AS saldo_minimo_mensal,
  ARRAY_AGG(saidas         ORDER BY anomes) AS saidas_mensal,
  APPROX_QUANTILES(renda, 4)[OFFSET(2)]     AS renda_mediana,
  AVG(renda)                                AS renda_media,      -- média mensal das entradas (tipo E) do histórico: a renda do perfil
  COUNTIF(renda > 0)                        AS meses_com_renda,
  SAFE_DIVIDE(STDDEV(renda), AVG(renda))    AS cv_renda,
  COUNTIF(saldo_minimo < 0)                 AS meses_no_vermelho,
  COUNT(*)                                  AS n_meses,
  MAX(renda) > 0                            AS renda_conhecida,
  CURRENT_TIMESTAMP()                       AS gerado_em
FROM ult
WHERE rn <= 12
GROUP BY id_usuario;

-- ---------- 4) dívidas derivadas do extrato (o evento não traz cadastro de dívidas) ----------
-- Regras explícitas (fictícias, parametrizáveis em motor/politicas.py): cheque especial = pior saldo negativo do
-- último mês; parcelas ativas = estoque k/N do último mês; cartão/empréstimo = lançamentos com descrição financeira.
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.dividas_derivadas`
CLUSTER BY id_usuario AS
WITH ultimo AS (
  SELECT id_usuario, MAX(anomes) AS anomes FROM `${PROJETO}.${DATASET}.extrato` GROUP BY id_usuario
),
e AS (
  SELECT x.* FROM `${PROJETO}.${DATASET}.extrato` x JOIN ultimo u USING (id_usuario, anomes)
),
cheque AS (
  SELECT id_usuario, 'cheque_especial' AS produto, ROUND(-MIN(saldo_apos), 2) AS saldo, 0.08 AS taxa_mensal,
         0 AS dias_atraso, 0.0 AS parcela_atual, 0 AS parcelas_restantes, 'nenhuma' AS consequencia,
         'saldo negativo no último mês (estimado a partir do extrato)' AS descricao
  FROM e WHERE saldo_apos < 0 GROUP BY id_usuario
),
parc AS (
  SELECT id_usuario, 'crediario' AS produto,
         ROUND(SUM(vlr * (parcela_total - parcela_atual + 1)), 2) AS saldo, 0.0 AS taxa_mensal,
         0 AS dias_atraso, ROUND(SUM(vlr), 2) AS parcela_atual, MAX(parcela_total - parcela_atual + 1) AS parcelas_restantes,
         'nenhuma' AS consequencia, FORMAT('%d parcelamentos ativos (estimado a partir do extrato)', COUNT(*)) AS descricao
  FROM e WHERE parcela_total IS NOT NULL AND parcela_atual IS NOT NULL GROUP BY id_usuario
),
cartao AS (
  SELECT id_usuario, 'cartao_rotativo' AS produto, ROUND(SUM(vlr) * 6, 2) AS saldo, 0.14 AS taxa_mensal,
         60 AS dias_atraso, 0.0 AS parcela_atual, 0 AS parcelas_restantes, 'negativacao' AS consequencia,
         'pagamento mínimo/rotativo detectado (estimado a partir do extrato)' AS descricao
  FROM e WHERE REGEXP_CONTAINS(descr, r'minimo|rotativo|juros cart|encargo') GROUP BY id_usuario
),
emprestimo AS (
  SELECT id_usuario, 'emprestimo' AS produto, ROUND(SUM(vlr) * 8, 2) AS saldo, 0.045 AS taxa_mensal,
         0 AS dias_atraso, ROUND(SUM(vlr), 2) AS parcela_atual, 8 AS parcelas_restantes, 'negativacao' AS consequencia,
         'parcela de empréstimo detectada (estimado a partir do extrato)' AS descricao
  FROM e WHERE REGEXP_CONTAINS(descr, r'emprest|financ|consign') GROUP BY id_usuario
)
SELECT *, CONCAT('dv_', produto) AS divida_id, 'Itaú' AS instituicao, 'derivada_extrato' AS fonte FROM cheque
UNION ALL SELECT *, CONCAT('dv_', produto), 'Itaú', 'derivada_extrato' FROM parc
UNION ALL SELECT *, CONCAT('dv_', produto), 'Itaú', 'derivada_extrato' FROM cartao
UNION ALL SELECT *, CONCAT('dv_', produto), 'Itaú', 'derivada_extrato' FROM emprestimo;

-- ---------- 5) estado, eventos e telemetria (append-only; Firestore não está liberado no projeto) ----------
CREATE TABLE IF NOT EXISTS `${PROJETO}.${DATASET}.estado_cliente` (
  cliente_id STRING NOT NULL, gravado_em TIMESTAMP NOT NULL, apagado BOOL NOT NULL, estado STRING
) PARTITION BY DATE(gravado_em) CLUSTER BY cliente_id;

CREATE TABLE IF NOT EXISTS `${PROJETO}.${DATASET}.eventos` (
  evento_id STRING NOT NULL, cliente_id STRING NOT NULL, sessao_id STRING, tipo STRING NOT NULL, payload STRING,
  variante_experimento STRING, data_simulada STRING, timestamp TIMESTAMP NOT NULL
) PARTITION BY DATE(timestamp) CLUSTER BY cliente_id, tipo;

CREATE TABLE IF NOT EXISTS `${PROJETO}.${DATASET}.telemetria` (
  timestamp TIMESTAMP NOT NULL, servico STRING, versao STRING, tipo STRING NOT NULL, nome STRING NOT NULL,
  valor FLOAT64, atributos STRING
) PARTITION BY DATE(timestamp) CLUSTER BY tipo, nome;

-- ---------- 6) leitura que o agente faz (1 query por sessão) ----------
-- SELECT p.*, ARRAY(SELECT AS STRUCT * FROM `${DATASET}.dividas_derivadas` d WHERE d.id_usuario = p.id_usuario) AS derivadas
-- FROM `${DATASET}.perfil_cliente` p WHERE p.id_usuario = @cliente_id;
