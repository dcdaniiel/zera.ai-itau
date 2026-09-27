-- Ficha "2. Público prioritário e persona" — tudo direto do BigQuery, sobre a BASE COMPLETA (todos os registros do evento).
-- Uma única consulta; devolve linhas (bloco, metrica, valor) prontas para copiar na ficha.
--
--   bq query --project_id=batalha-time-03-vhxk --use_legacy_sql=false --max_rows=200 < dados/sql/ficha_segmento.sql
--   (por stdin: se passar o arquivo como argumento o bq lê os "-- …" como flags)
--
-- Pré-requisito: python -m dados.publicar_bq (zera.extrato, features, perfil_cliente, dividas_derivadas, kmeans_perfis,
-- clusters_clientes, perfil_clusters). O k-means roda sobre TODOS os clientes da base — não há amostra em nenhuma etapa.

WITH
base AS (
  SELECT COUNT(*) AS registros, COUNT(DISTINCT id_usuario) AS clientes,
         MIN(anomes) AS de, MAX(anomes) AS ate, COUNT(DISTINCT anomes) AS meses,
         COUNTIF(UPPER(CAST(tipo AS STRING)) = 'E') AS entradas, COUNTIF(UPPER(CAST(tipo AS STRING)) = 'S') AS saidas
  FROM `batalha-time-03-vhxk.hackathon_dados.extrato_sintetico`
),
alvo AS (
  SELECT cluster FROM `batalha-time-03-vhxk.zera.perfil_clusters` WHERE cluster_alvo LIMIT 1
),
cl AS (
  SELECT cluster, COUNT(*) AS clientes FROM `batalha-time-03-vhxk.zera.clusters_clientes` GROUP BY cluster
),
seg AS (   -- clientes do cluster-alvo
  SELECT id_usuario, distancia FROM `batalha-time-03-vhxk.zera.clusters_clientes` WHERE cluster = (SELECT cluster FROM alvo)
),
reg_seg AS (
  SELECT COUNT(*) AS registros FROM `batalha-time-03-vhxk.zera.extrato` e JOIN seg USING (id_usuario)
),
renda AS (
  SELECT APPROX_QUANTILES(pc.renda_media, 4) AS q, APPROX_QUANTILES(pc.meses_no_vermelho, 4) AS qv,
         COUNTIF(pc.renda_conhecida) AS com_renda, COUNT(*) AS n, AVG(pc.cv_renda) AS cv
  FROM `batalha-time-03-vhxk.zera.perfil_cliente` pc JOIN seg USING (id_usuario)
),
div_cli AS (
  SELECT d.id_usuario, SUM(d.saldo) AS total,
         COUNTIF(d.produto = 'cheque_especial') > 0 AS tem_cheque,
         COUNTIF(d.produto = 'crediario') > 0 AS tem_crediario,
         COUNTIF(d.produto = 'cartao_rotativo') > 0 AS tem_rotativo,
         COUNTIF(d.produto NOT IN ('cheque_especial', 'crediario', 'cartao_rotativo')) > 0 AS tem_outro
  FROM `batalha-time-03-vhxk.zera.dividas_derivadas` d JOIN seg USING (id_usuario) GROUP BY d.id_usuario
),
div AS (
  SELECT APPROX_QUANTILES(total, 4) AS q, COUNT(*) AS com_divida,
         COUNTIF(tem_cheque) AS cheque, COUNTIF(tem_crediario) AS crediario, COUNTIF(tem_rotativo) AS rotativo, COUNTIF(tem_outro) AS outro
  FROM div_cli
),
pc_alvo AS (
  SELECT * FROM `batalha-time-03-vhxk.zera.perfil_clusters` WHERE cluster_alvo
),
persona AS (   -- medoide: cliente real mais próximo do centróide do cluster-alvo
  SELECT s.id_usuario, s.distancia, pc.renda_media, pc.meses_no_vermelho,
         (SELECT SUM(saldo) FROM `batalha-time-03-vhxk.zera.dividas_derivadas` d WHERE d.id_usuario = s.id_usuario) AS dividas
  FROM seg s JOIN `batalha-time-03-vhxk.zera.perfil_cliente` pc USING (id_usuario)
  ORDER BY s.distancia LIMIT 1
),
modelo AS (
  SELECT davies_bouldin_index, mean_squared_distance FROM ML.EVALUATE(MODEL `batalha-time-03-vhxk.zera.kmeans_perfis`)
)
SELECT 1 AS ordem, 'base' AS bloco, 'registros (lançamentos)' AS metrica, FORMAT('%d', registros) AS valor FROM base
UNION ALL SELECT 2, 'base', 'clientes distintos', FORMAT('%d', clientes) FROM base
UNION ALL SELECT 3, 'base', 'período (anomes)', FORMAT('%d a %d (%d meses)', de, ate, meses) FROM base
UNION ALL SELECT 4, 'base', 'entradas / saídas', FORMAT('%d / %d', entradas, saidas) FROM base
UNION ALL SELECT 5, 'base', 'lançamentos por cliente (média)', FORMAT('%.0f', registros / clientes) FROM base
UNION ALL SELECT 10 + cluster, 'clusters', FORMAT('cluster %d — clientes', cluster),
                 FORMAT('%d (%.1f%% da base)', clientes, 100 * clientes / (SELECT clientes FROM base)) FROM cl
UNION ALL SELECT 20, 'segmento', 'cluster-alvo (maior índice de endividamento)', FORMAT('cluster %d', cluster) FROM alvo
UNION ALL SELECT 21, 'segmento', 'clientes no segmento', FORMAT('%d', clientes) FROM cl WHERE cluster = (SELECT cluster FROM alvo)
UNION ALL SELECT 22, 'segmento', 'participação na base', FORMAT('%.1f%%', 100 * clientes / (SELECT clientes FROM base)) FROM cl WHERE cluster = (SELECT cluster FROM alvo)
UNION ALL SELECT 23, 'segmento', 'lançamentos do segmento', FORMAT('%d', registros) FROM reg_seg
UNION ALL SELECT 24, 'segmento', 'índice de endividamento (média de z-scores)', FORMAT('%.2f', indice_endividamento) FROM pc_alvo
UNION ALL SELECT 25, 'segmento', 'meses no vermelho (média de 12)', FORMAT('%.1f', meses_no_vermelho) FROM pc_alvo
UNION ALL SELECT 26, 'segmento', 'pior saldo do mês (média, R$)', FORMAT('%.0f', pior_saldo) FROM pc_alvo
UNION ALL SELECT 27, 'segmento', 'serviço da dívida / saídas', FORMAT('%.1f%%', 100 * pct_servico_divida) FROM pc_alvo
UNION ALL SELECT 28, 'segmento', 'parcelas por mês (R$ · quantidade)', FORMAT('%.0f · %.1f', parcelas_media, qtd_parcelas_media) FROM pc_alvo
UNION ALL SELECT 29, 'segmento', 'assinaturas por mês (R$)', FORMAT('%.0f', assinaturas_media) FROM pc_alvo
UNION ALL SELECT 30, 'segmento', 'essenciais / saídas', FORMAT('%.1f%%', 100 * pct_essenciais) FROM pc_alvo
UNION ALL SELECT 31, 'segmento', 'CV da renda (regularidade)', FORMAT('%.3f', cv_renda) FROM pc_alvo
UNION ALL SELECT 32, 'segmento', 'sinais de rotativo · empréstimo (por ano)', FORMAT('%.1f · %.1f', sinais_rotativo, sinais_emprestimo) FROM pc_alvo
UNION ALL SELECT 33, 'segmento', 'renda média das entradas (R$/mês) — Q1 · mediana · Q3', FORMAT('%.0f · %.0f · %.0f', q[OFFSET(1)], q[OFFSET(2)], q[OFFSET(3)]) FROM renda
UNION ALL SELECT 34, 'segmento', 'clientes com renda identificada no extrato', FORMAT('%d de %d', com_renda, n) FROM renda
UNION ALL SELECT 35, 'segmento', 'meses no vermelho — Q1 · mediana · Q3', FORMAT('%d · %d · %d', qv[OFFSET(1)], qv[OFFSET(2)], qv[OFFSET(3)]) FROM renda
UNION ALL SELECT 36, 'segmento', 'dívidas inferidas do extrato por cliente (R$) — Q1 · mediana · Q3', FORMAT('%.0f · %.0f · %.0f', q[OFFSET(1)], q[OFFSET(2)], q[OFFSET(3)]) FROM div
UNION ALL SELECT 37, 'segmento', 'clientes com dívida inferida', FORMAT('%d', com_divida) FROM div
UNION ALL SELECT 38, 'segmento', 'com cheque especial · crediário · cartão rotativo · outras', FORMAT('%d · %d · %d · %d', cheque, crediario, rotativo, outro) FROM div
UNION ALL SELECT 40, 'persona', 'medoide (id · distância ao centróide)', FORMAT('%s · %.3f', id_usuario, distancia) FROM persona
UNION ALL SELECT 41, 'persona', 'renda média das entradas (R$/mês)', FORMAT('%.0f', renda_media) FROM persona
UNION ALL SELECT 42, 'persona', 'meses no vermelho (de 12)', FORMAT('%d', meses_no_vermelho) FROM persona
UNION ALL SELECT 43, 'persona', 'dívidas inferidas (R$)', FORMAT('%.0f', IFNULL(dividas, 0)) FROM persona
UNION ALL SELECT 50, 'modelo', 'k-means: Davies-Bouldin (menor = clusters mais separados)', FORMAT('%.3f', davies_bouldin_index) FROM modelo
UNION ALL SELECT 51, 'modelo', 'k-means: distância quadrática média', FORMAT('%.3f', mean_squared_distance) FROM modelo
ORDER BY ordem;
