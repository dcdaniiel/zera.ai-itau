-- ============================================================================
-- Clusterização de clientes no GCP (BigQuery ML, k-means) — projeto ${PROJETO}, dataset ${DATASET}
-- ============================================================================
-- Objetivo (quadro de produto, item 05): encontrar, na base real do evento, o segmento de clientes com o perfil da
-- persona do produto (endividada: meses no vermelho, rotativo/mínimo, parcelamentos, serviço de dívida alto).
-- k-means (BigQuery ML) sobre features de 12 meses -> cada cluster recebe um "índice de endividamento" (média das
-- features padronizadas do segmento-alvo) -> o cluster com maior índice é o CLUSTER-ALVO -> seus clientes reais viram
-- os perfis da demo (`perfis_demo`), do mais típico (menor distância ao centróide = medoide, que recebe o nome da
-- persona "Cleide") para o menos típico. Identidades fictícias (quadro item 19). Nenhum dado sintético.
--
-- Roda depois de dados/sql/zera_tabelas.sql (precisa de features_mensais, perfil_cliente, dividas_derivadas).
-- Reprodutível: features padronizadas (standardize_features), k-means++ e 4 clusters (ajuste NUM_CLUSTERS e valide
-- com ML.EVALUATE — Davies-Bouldin — antes de afirmar o número de segmentos).

-- ---------- 1) features por cliente (últimos 12 meses) ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.features_cliente`
CLUSTER BY id_usuario AS
WITH ult AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY id_usuario ORDER BY anomes DESC) AS rn
  FROM `${PROJETO}.${DATASET}.features_mensais`
)
SELECT
  id_usuario,
  COUNT(*)                                                             AS n_meses,
  IFNULL(APPROX_QUANTILES(renda, 4)[OFFSET(2)], 0)                     AS renda_mediana,
  IFNULL(SAFE_DIVIDE(STDDEV(renda), NULLIF(AVG(renda), 0)), 0)         AS cv_renda,
  IFNULL(AVG(essenciais), 0)                                           AS essenciais_media,
  IFNULL(AVG(saidas), 0)                                               AS saidas_media,
  IFNULL(SAFE_DIVIDE(AVG(essenciais), NULLIF(AVG(saidas), 0)), 0)      AS pct_essenciais,
  IFNULL(AVG(servico_divida), 0)                                       AS servico_divida_media,
  IFNULL(SAFE_DIVIDE(AVG(servico_divida), NULLIF(AVG(saidas), 0)), 0)  AS pct_servico_divida,
  IFNULL(AVG(parcelas), 0)                                             AS parcelas_media,
  IFNULL(AVG(qtd_parcelas), 0)                                         AS qtd_parcelas_media,
  IFNULL(AVG(assinaturas), 0)                                          AS assinaturas_media,
  COUNTIF(saldo_minimo < 0)                                            AS meses_no_vermelho,
  IFNULL(MIN(saldo_minimo), 0)                                         AS pior_saldo,
  IFNULL(SUM(sinais_rotativo), 0)                                      AS sinais_rotativo,
  IFNULL(SUM(sinais_emprestimo), 0)                                    AS sinais_emprestimo,
  IFNULL(AVG(novo_comprometimento_futuro), 0)                          AS comprometimento_futuro_medio
FROM ult
WHERE rn <= 12
GROUP BY id_usuario;

-- ---------- 2) modelo k-means (BigQuery ML) ----------
CREATE OR REPLACE MODEL `${PROJETO}.${DATASET}.kmeans_perfis`
OPTIONS (model_type = 'KMEANS', num_clusters = ${NUM_CLUSTERS}, standardize_features = TRUE,
         kmeans_init_method = 'KMEANS++', max_iterations = 50) AS
SELECT pct_essenciais, pct_servico_divida, parcelas_media, qtd_parcelas_media, assinaturas_media,
       meses_no_vermelho, pior_saldo, sinais_rotativo, sinais_emprestimo, cv_renda, comprometimento_futuro_medio
FROM `${PROJETO}.${DATASET}.features_cliente`;

-- ---------- 3) atribuição de cluster por cliente (persona incluída) ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.clusters_clientes`
CLUSTER BY id_usuario AS
SELECT
  id_usuario,
  CENTROID_ID AS cluster,
  (SELECT d.DISTANCE FROM UNNEST(NEAREST_CENTROIDS_DISTANCE) d ORDER BY d.DISTANCE LIMIT 1) AS distancia,
  * EXCEPT (id_usuario, CENTROID_ID, NEAREST_CENTROIDS_DISTANCE)
FROM ML.PREDICT(MODEL `${PROJETO}.${DATASET}.kmeans_perfis`,
                (SELECT * FROM `${PROJETO}.${DATASET}.features_cliente`));

-- ---------- 4) perfil de cada cluster (escala original) + índice de endividamento + cluster-alvo ----------
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.perfil_clusters` AS
WITH z AS (   -- padronização global das features do segmento-alvo (mesma fórmula de dados/segmentacao.py)
  SELECT cluster,
         SAFE_DIVIDE(meses_no_vermelho - AVG(meses_no_vermelho) OVER (), NULLIF(STDDEV_POP(meses_no_vermelho) OVER (), 0)) AS z_vermelho,
         SAFE_DIVIDE(-LEAST(pior_saldo, 0) - AVG(-LEAST(pior_saldo, 0)) OVER (), NULLIF(STDDEV_POP(-LEAST(pior_saldo, 0)) OVER (), 0)) AS z_saldo,
         SAFE_DIVIDE(pct_servico_divida - AVG(pct_servico_divida) OVER (), NULLIF(STDDEV_POP(pct_servico_divida) OVER (), 0)) AS z_divida,
         SAFE_DIVIDE(qtd_parcelas_media - AVG(qtd_parcelas_media) OVER (), NULLIF(STDDEV_POP(qtd_parcelas_media) OVER (), 0)) AS z_parcelas,
         SAFE_DIVIDE(sinais_rotativo - AVG(sinais_rotativo) OVER (), NULLIF(STDDEV_POP(sinais_rotativo) OVER (), 0)) AS z_rotativo,
         SAFE_DIVIDE(sinais_emprestimo - AVG(sinais_emprestimo) OVER (), NULLIF(STDDEV_POP(sinais_emprestimo) OVER (), 0)) AS z_emprestimo,
         meses_no_vermelho, pior_saldo, pct_servico_divida, parcelas_media, qtd_parcelas_media, assinaturas_media, pct_essenciais, cv_renda,
         sinais_rotativo, sinais_emprestimo
  FROM `${PROJETO}.${DATASET}.clusters_clientes`
),
por_cluster AS (
  SELECT cluster, COUNT(*) AS clientes,
         ROUND(AVG(IFNULL(z_vermelho, 0) + IFNULL(z_saldo, 0) + IFNULL(z_divida, 0) + IFNULL(z_parcelas, 0) + IFNULL(z_rotativo, 0) + IFNULL(z_emprestimo, 0)), 4) AS indice_endividamento,
         ROUND(AVG(meses_no_vermelho), 2) AS meses_no_vermelho, ROUND(AVG(pior_saldo), 2) AS pior_saldo,
         ROUND(AVG(pct_servico_divida), 3) AS pct_servico_divida, ROUND(AVG(parcelas_media), 2) AS parcelas_media,
         ROUND(AVG(qtd_parcelas_media), 2) AS qtd_parcelas_media, ROUND(AVG(assinaturas_media), 2) AS assinaturas_media,
         ROUND(AVG(pct_essenciais), 3) AS pct_essenciais, ROUND(AVG(cv_renda), 3) AS cv_renda,
         ROUND(AVG(sinais_rotativo), 2) AS sinais_rotativo, ROUND(AVG(sinais_emprestimo), 2) AS sinais_emprestimo
  FROM z GROUP BY cluster
)
SELECT *, indice_endividamento = MAX(indice_endividamento) OVER () AS cluster_alvo, CURRENT_TIMESTAMP() AS gerado_em
FROM por_cluster;

-- ---------- 5) perfis disponíveis na demo: clientes REAIS do cluster-alvo (mais típicos primeiro) ----------
-- Identidade fictícia (quadro item 19): pseudônimo determinístico a partir do id; o medoide recebe o nome da persona.
CREATE OR REPLACE TABLE `${PROJETO}.${DATASET}.perfis_demo` AS
WITH alvo AS (
  SELECT cluster FROM `${PROJETO}.${DATASET}.perfil_clusters` WHERE cluster_alvo LIMIT 1
),
nomes AS (
  SELECT ['Ana', 'Bruno', 'Carla', 'Diego', 'Elaine', 'Fábio', 'Gisele', 'Heitor', 'Iara', 'Jorge', 'Kelly', 'Luan',
          'Marta', 'Nilton', 'Otávia', 'Paulo'] AS lista
),
cand AS (
  SELECT
    c.id_usuario, c.cluster, ROUND(c.distancia, 4) AS distancia,
    CONCAT(nomes.lista[OFFSET(MOD(ABS(FARM_FINGERPRINT(c.id_usuario)), 16))], ' ', UPPER(SUBSTR(c.id_usuario, 1, 4))) AS pseudonimo,
    p.renda_mediana, p.renda_media, p.meses_com_renda, p.renda_conhecida, p.meses_no_vermelho, ROUND(IFNULL(p.cv_renda, 0), 3) AS cv_renda, p.n_meses,
    c.qtd_parcelas_media, c.sinais_rotativo, c.sinais_emprestimo,
    (SELECT ROUND(SUM(saldo), 2) FROM `${PROJETO}.${DATASET}.dividas_derivadas` d WHERE d.id_usuario = c.id_usuario) AS total_dividas,
    (SELECT COUNT(*) FROM `${PROJETO}.${DATASET}.dividas_derivadas` d WHERE d.id_usuario = c.id_usuario) AS qtd_dividas
  FROM `${PROJETO}.${DATASET}.clusters_clientes` c
  JOIN `${PROJETO}.${DATASET}.perfil_cliente` p USING (id_usuario)
  CROSS JOIN nomes
  WHERE c.cluster = (SELECT cluster FROM alvo)
),
ordenado AS (
  SELECT *, ROW_NUMBER() OVER (ORDER BY renda_conhecida DESC, distancia) AS ordem FROM cand WHERE qtd_dividas > 0
)
SELECT
  * EXCEPT (pseudonimo),
  IF(ordem = 1, '${NOME_MEDOIDE}', pseudonimo) AS nome,
  ordem = 1 AS medoide,
  ARRAY_TO_STRING([
    IF(meses_no_vermelho > 0, FORMAT('%d meses no vermelho', meses_no_vermelho), NULL),
    IF(sinais_rotativo > 0, 'rotativo/mínimo do cartão', NULL),
    IF(sinais_emprestimo > 0, 'parcela de empréstimo', NULL),
    IF(qtd_parcelas_media >= 1, FORMAT('~%d parcelamentos/mês', CAST(ROUND(qtd_parcelas_media) AS INT64)), NULL),
    IF(NOT renda_conhecida, 'renda não identificada no extrato', NULL)
  ], ' · ') AS sinais,
  CURRENT_TIMESTAMP() AS gerado_em
FROM ordenado
WHERE ordem <= ${MAX_PERFIS};
