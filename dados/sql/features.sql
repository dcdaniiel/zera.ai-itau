-- Features mensais por cliente a partir do extrato do evento (schema real, 26/09).
-- Colunas: id_usuario, anomesdia, anomes, tipo (S=saída, E=entrada), descr, vlr, nom_cate_macro, nom_cate_micro,
--          saldo_apos, parcela_atual, parcela_total
CREATE OR REPLACE VIEW `zera.features_mensais` AS
WITH t AS (
  SELECT
    id_usuario                          AS cliente_id,
    anomes                              AS mes,
    UPPER(tipo)                         AS tipo,
    LOWER(descr)                        AS descricao,
    ABS(vlr)                            AS valor,
    LOWER(nom_cate_macro)               AS macro,
    LOWER(nom_cate_micro)               AS micro,
    saldo_apos, parcela_atual, parcela_total
  FROM `hackathon_dados.extrato_sintetico`
),
classificado AS (
  SELECT *,
    CASE
      WHEN tipo = 'E' THEN 'renda'
      WHEN tipo = 'S' AND REGEXP_CONTAINS(descricao, r'juros|encargo|iof|tarifa|multa|rotativo|minimo|emprest|financ|renegoc|acordo') THEN 'divida'
      WHEN tipo = 'S' AND parcela_total IS NOT NULL THEN 'parcela'
      WHEN tipo = 'S' AND macro IN ('casa','mercado','transporte publico','posto de combustivel','educacao','saude','contas e servicos')
           AND micro NOT IN ('jardinagem','lavanderia') THEN 'essencial'
      WHEN tipo = 'S' AND macro = 'assinaturas' THEN 'assinatura'
      ELSE 'outros'
    END AS classe
  FROM t
)
SELECT
  cliente_id, mes,
  SUM(IF(classe = 'renda', valor, 0))       AS renda,
  SUM(IF(classe = 'essencial', valor, 0))   AS essenciais,
  SUM(IF(classe = 'parcela', valor, 0))     AS parcelas,
  SUM(IF(classe = 'divida', valor, 0))      AS servico_divida,
  SUM(IF(classe = 'assinatura', valor, 0))  AS assinaturas,
  SUM(IF(classe = 'outros', valor, 0))      AS outros,
  SUM(IF(classe = 'renda', valor, 0)) - SUM(IF(classe = 'essencial', valor, 0)) - SUM(IF(classe = 'parcela', valor, 0)) AS sobra,
  MIN(saldo_apos)                           AS saldo_minimo,
  COUNTIF(saldo_apos < 0)                   AS lancamentos_no_vermelho,
  SUM(IF(parcela_atual = 1, valor * (parcela_total - 1), 0)) AS novo_comprometimento_futuro
FROM classificado
GROUP BY cliente_id, mes;

-- Candidatos à persona "Cleide": renda irregular + vermelho recorrente + parcelas
-- SELECT cliente_id,
--        COUNT(*) meses,
--        APPROX_QUANTILES(renda, 4)[OFFSET(2)] AS renda_mediana,
--        ROUND(STDDEV(renda)/NULLIF(AVG(renda),0), 2) AS cv_renda,
--        COUNTIF(saldo_minimo < 0) AS meses_no_vermelho,
--        ROUND(AVG(parcelas), 0) AS parcelas_media,
--        ROUND(AVG(servico_divida), 0) AS divida_media
-- FROM `zera.features_mensais` GROUP BY cliente_id
-- HAVING meses_no_vermelho >= 2 AND parcelas_media > 0 ORDER BY meses_no_vermelho DESC, divida_media DESC LIMIT 20;
