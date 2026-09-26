-- Camada de dados do Zera no BigQuery (projeto batalha-time-03-vhxk, us-central1)
-- Rode uma vez (bq query --use_legacy_sql=false < dados/sql/zera_tabelas.sql) e agende o passo 2 (scheduled query diária).
--
-- Estratégia: a tabela do evento é a fonte da verdade (analítica). O agente NÃO lê transações brutas por turno:
--   1) cópia particionada por dia e CLUSTERIZADA por id_usuario  -> consultas por cliente baratas e rápidas
--   2) features mensais por cliente (tabela materializada)         -> o que o motor precisa
--   3) perfil_cliente: 1 linha por cliente com arrays de 12 meses  -> 1 leitura por sessão (BigQuery ou Firestore)
--   4) dividas_derivadas: dívidas inferidas do extrato (saldo negativo, parcelas, juros/empréstimo por descrição)

-- ---------- 1) extrato particionado + clusterizado ----------
CREATE TABLE IF NOT EXISTS `zera.extrato`
PARTITION BY dia
CLUSTER BY id_usuario AS
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
  parcela_total
FROM `hackathon_dados.extrato_sintetico`;

-- ---------- 2) features mensais (materializada; agende com scheduled query) ----------
CREATE OR REPLACE TABLE `zera.features_mensais`
PARTITION BY RANGE_BUCKET(anomes, GENERATE_ARRAY(202301, 202812, 1))
CLUSTER BY id_usuario AS
WITH c AS (
  SELECT *,
    CASE
      WHEN tipo = 'E' THEN 'renda'
      WHEN REGEXP_CONTAINS(descr, r'juros|encargo|iof|tarifa|multa|rotativo|minimo|emprest|financ|renegoc|acordo') THEN 'divida'
      WHEN parcela_total IS NOT NULL THEN 'parcela'
      WHEN macro IN ('casa','mercado','transporte publico','posto de combustivel','educacao','saude','contas e servicos')
           AND micro NOT IN ('jardinagem','lavanderia') THEN 'essencial'
      WHEN macro = 'assinaturas' THEN 'assinatura'
      ELSE 'outros'
    END AS classe
  FROM `zera.extrato`
)
SELECT
  id_usuario, anomes,
  SUM(IF(classe = 'renda', vlr, 0))        AS renda,
  SUM(IF(classe = 'essencial', vlr, 0))    AS essenciais,
  SUM(IF(classe = 'parcela', vlr, 0))      AS parcelas,
  SUM(IF(classe = 'divida', vlr, 0))       AS servico_divida,
  SUM(IF(classe = 'assinatura', vlr, 0))   AS assinaturas,
  SUM(IF(classe = 'outros', vlr, 0))       AS outros,
  MIN(saldo_apos)                          AS saldo_minimo,
  COUNTIF(saldo_apos < 0)                  AS lancamentos_no_vermelho,
  SUM(IF(parcela_atual = 1, vlr * (parcela_total - 1), 0)) AS novo_comprometimento_futuro,
  COUNTIF(classe = 'renda' AND vlr >= 0.4 * (SELECT APPROX_QUANTILES(vlr, 2)[OFFSET(1)] FROM c c2 WHERE c2.id_usuario = c.id_usuario AND c2.classe = 'renda')) AS creditos_atipicos
FROM c
GROUP BY id_usuario, anomes;

-- ---------- 3) perfil_cliente: 1 linha por cliente, últimos 12 meses em arrays (ordenados) ----------
CREATE OR REPLACE TABLE `zera.perfil_cliente`
CLUSTER BY id_usuario AS
WITH ult AS (
  SELECT id_usuario, anomes, renda, essenciais, parcelas, servico_divida, saldo_minimo,
         ROW_NUMBER() OVER (PARTITION BY id_usuario ORDER BY anomes DESC) AS rn
  FROM `zera.features_mensais`
)
SELECT
  id_usuario,
  ARRAY_AGG(FORMAT('%d-%02d', DIV(anomes, 100), MOD(anomes, 100)) ORDER BY anomes) AS meses,
  ARRAY_AGG(renda          ORDER BY anomes) AS renda_mensal,
  ARRAY_AGG(essenciais     ORDER BY anomes) AS essenciais_mensal,
  ARRAY_AGG(parcelas       ORDER BY anomes) AS parcelas_mensal,
  ARRAY_AGG(servico_divida ORDER BY anomes) AS servico_divida_mensal,
  ARRAY_AGG(saldo_minimo   ORDER BY anomes) AS saldo_minimo_mensal,
  APPROX_QUANTILES(renda, 4)[OFFSET(2)]     AS renda_mediana,
  SAFE_DIVIDE(STDDEV(renda), AVG(renda))    AS cv_renda,
  COUNTIF(saldo_minimo < 0)                 AS meses_no_vermelho,
  CURRENT_TIMESTAMP()                       AS gerado_em
FROM ult
WHERE rn <= 12
GROUP BY id_usuario;

-- ---------- 4) dívidas derivadas do extrato (o evento não traz cadastro de dívidas) ----------
-- Regras (fictícias, parametrizadas em motor/politicas.py): cheque especial = pior saldo negativo do último mês;
-- parcelas ativas = estoque de parcelas k/N do último mês; cartão/empréstimo = lançamentos com descrição financeira.
CREATE OR REPLACE TABLE `zera.dividas_derivadas`
CLUSTER BY id_usuario AS
WITH ultimo AS (
  SELECT id_usuario, MAX(anomes) AS anomes FROM `zera.extrato` GROUP BY id_usuario
),
e AS (
  SELECT x.* FROM `zera.extrato` x JOIN ultimo u USING (id_usuario, anomes)
),
cheque AS (
  SELECT id_usuario, 'cheque_especial' AS produto, -MIN(saldo_apos) AS saldo, 0.08 AS taxa_mensal,
         0 AS dias_atraso, 'nenhuma' AS consequencia, 'saldo negativo no último mês' AS descricao
  FROM e WHERE saldo_apos < 0 GROUP BY id_usuario
),
parc AS (
  SELECT id_usuario, 'crediario' AS produto,
         SUM(vlr * (parcela_total - parcela_atual + 1)) AS saldo, 0.0 AS taxa_mensal,
         0 AS dias_atraso, 'nenhuma' AS consequencia,
         FORMAT('%d parcelamentos ativos', COUNT(*)) AS descricao
  FROM e WHERE parcela_total IS NOT NULL GROUP BY id_usuario
),
cartao AS (
  SELECT id_usuario, 'cartao_rotativo' AS produto, SUM(vlr) * 6 AS saldo, 0.14 AS taxa_mensal,
         60 AS dias_atraso, 'negativacao' AS consequencia, 'pagamento mínimo/rotativo detectado' AS descricao
  FROM e WHERE REGEXP_CONTAINS(descr, r'minimo|rotativo|juros cart|encargo') GROUP BY id_usuario
),
emprestimo AS (
  SELECT id_usuario, 'emprestimo' AS produto, SUM(vlr) * 8 AS saldo, 0.045 AS taxa_mensal,
         0 AS dias_atraso, 'negativacao' AS consequencia, 'parcela de empréstimo detectada' AS descricao
  FROM e WHERE REGEXP_CONTAINS(descr, r'emprest|financ|consign') GROUP BY id_usuario
)
SELECT *, CONCAT('dv_', produto) AS divida_id FROM cheque
UNION ALL SELECT *, CONCAT('dv_', produto) FROM parc
UNION ALL SELECT *, CONCAT('dv_', produto) FROM cartao
UNION ALL SELECT *, CONCAT('dv_', produto) FROM emprestimo;

-- ---------- 5) leitura que o agente faz (1 query por sessão) ----------
-- SELECT p.*, ARRAY(SELECT AS STRUCT * FROM `zera.dividas_derivadas` d WHERE d.id_usuario = p.id_usuario) AS dividas
-- FROM `zera.perfil_cliente` p WHERE id_usuario = @cliente_id;
