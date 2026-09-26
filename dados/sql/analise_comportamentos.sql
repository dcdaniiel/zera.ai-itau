-- Análise de comportamentos na base completa `batalha-time-03-vhxk.hackathon_dados.extrato_sintetico`
-- Colunas: id_usuario, anomesdia (TIMESTAMP), anomes (INT), tipo (S=saída, E=entrada?), descr, vlr,
--          nom_cate_macro, nom_cate_micro, saldo_apos, parcela_atual, parcela_total
-- ATENÇÃO: o export de 10k linhas veio ordenado por `descr` (só "assin…" até "cart credito rest") —
-- sem entradas, juros, faturas, empréstimos. Rode estas queries na tabela inteira.

-- 0) O que existe além da amostra: tipos, meses, categorias e descrições "financeiras"
SELECT tipo, COUNT(*) n, COUNT(DISTINCT id_usuario) usuarios, MIN(anomes) de, MAX(anomes) ate
FROM `hackathon_dados.extrato_sintetico` GROUP BY tipo;

SELECT nom_cate_macro, nom_cate_micro, tipo, COUNT(*) n, ROUND(SUM(vlr),2) total
FROM `hackathon_dados.extrato_sintetico` GROUP BY 1,2,3 ORDER BY total DESC;

SELECT descr, tipo, COUNT(*) n, ROUND(AVG(vlr),2) medio
FROM `hackathon_dados.extrato_sintetico`
WHERE REGEXP_CONTAINS(LOWER(descr), r'juros|encargo|iof|tarifa|fatura|minimo|rotativo|emprest|financ|parc|cheque|limite|renegoc|acordo|cobranca|atraso|multa|salario|pix|ted|transf')
GROUP BY 1,2 ORDER BY n DESC LIMIT 200;

-- 1) Cheque especial: dias/lançamentos com saldo negativo por usuário-mês e gasto feito no vermelho
WITH base AS (
  SELECT id_usuario, anomes, DATE(anomesdia) dia, vlr, saldo_apos, tipo, nom_cate_macro
  FROM `hackathon_dados.extrato_sintetico`
)
SELECT anomes,
       COUNT(DISTINCT id_usuario) usuarios,
       COUNT(DISTINCT IF(saldo_apos < 0, id_usuario, NULL)) usuarios_negativos,
       ROUND(100 * COUNT(DISTINCT IF(saldo_apos < 0, id_usuario, NULL)) / COUNT(DISTINCT id_usuario), 1) pct_negativos,
       ROUND(SUM(IF(saldo_apos < 0 AND tipo = 'S', vlr, 0)), 2) gasto_no_vermelho,
       ROUND(APPROX_QUANTILES(IF(saldo_apos < 0, saldo_apos, NULL), 100)[OFFSET(50)], 0) saldo_neg_mediano
FROM base GROUP BY anomes ORDER BY anomes;

-- 1b) usuários cronicamente no vermelho (>= 3 meses com saldo negativo)
SELECT id_usuario, COUNT(DISTINCT anomes) meses_negativos, ROUND(MIN(saldo_apos),0) pior_saldo
FROM `hackathon_dados.extrato_sintetico` WHERE saldo_apos < 0
GROUP BY id_usuario HAVING meses_negativos >= 3 ORDER BY meses_negativos DESC, pior_saldo LIMIT 100;

-- 2) Parcelas invisíveis: comprometimento futuro por usuário (parcela 1/N iniciada no mês)
SELECT id_usuario, anomes,
       COUNT(*) compras_parceladas,
       ROUND(SUM(vlr), 2) parcela_mensal_nova,
       ROUND(SUM(vlr * (parcela_total - 1)), 2) comprometido_futuro,
       MAX(parcela_total) maior_prazo
FROM `hackathon_dados.extrato_sintetico`
WHERE parcela_total IS NOT NULL AND parcela_atual = 1
GROUP BY 1,2 HAVING comprometido_futuro > 1000 ORDER BY comprometido_futuro DESC LIMIT 100;

-- 2b) estoque de parcelas ativas no mês (todas as parcelas k/N em andamento) = "renda já comprometida"
SELECT id_usuario, anomes, COUNT(*) parcelas_ativas, ROUND(SUM(vlr),2) total_parcelas_mes
FROM `hackathon_dados.extrato_sintetico`
WHERE parcela_total IS NOT NULL
GROUP BY 1,2 ORDER BY total_parcelas_mes DESC LIMIT 100;

-- 3) Vazamentos: assinaturas por usuário
SELECT id_usuario, anomes, COUNT(*) assinaturas, ROUND(SUM(vlr),2) total_assinaturas
FROM `hackathon_dados.extrato_sintetico`
WHERE nom_cate_macro = 'Assinaturas'
GROUP BY 1,2 HAVING assinaturas >= 5 ORDER BY total_assinaturas DESC LIMIT 100;

-- 4) Renda (tipo = 'E'): mediana, variabilidade e sazonalidade por usuário
WITH renda AS (
  SELECT id_usuario, anomes, SUM(vlr) renda
  FROM `hackathon_dados.extrato_sintetico` WHERE tipo = 'E' GROUP BY 1,2
)
SELECT id_usuario,
       COUNT(*) meses,
       ROUND(APPROX_QUANTILES(renda, 4)[OFFSET(2)], 0) renda_mediana,
       ROUND(APPROX_QUANTILES(renda, 4)[OFFSET(1)], 0) renda_p25,
       ROUND(STDDEV(renda) / NULLIF(AVG(renda), 0), 2) cv_renda
FROM renda GROUP BY id_usuario ORDER BY cv_renda DESC LIMIT 100;

-- 5) Persona-alvo do Zera: vermelho recorrente + parcelas + (juros/encargos se existirem na base)
WITH neg AS (
  SELECT id_usuario, COUNT(DISTINCT anomes) meses_neg, MIN(saldo_apos) pior_saldo
  FROM `hackathon_dados.extrato_sintetico` WHERE saldo_apos < 0 GROUP BY 1
),
parc AS (
  SELECT id_usuario, ROUND(SUM(vlr),2) parcelas_total, COUNT(DISTINCT anomes) meses_com_parcela
  FROM `hackathon_dados.extrato_sintetico` WHERE parcela_total IS NOT NULL GROUP BY 1
),
assin AS (
  SELECT id_usuario, ROUND(AVG(n),1) assin_media FROM (
    SELECT id_usuario, anomes, COUNT(*) n FROM `hackathon_dados.extrato_sintetico`
    WHERE nom_cate_macro = 'Assinaturas' GROUP BY 1,2) GROUP BY 1
),
fin AS (
  SELECT id_usuario, ROUND(SUM(vlr),2) encargos
  FROM `hackathon_dados.extrato_sintetico`
  WHERE REGEXP_CONTAINS(LOWER(descr), r'juros|encargo|iof|tarifa|multa|rotativo|minimo') GROUP BY 1
)
SELECT n.id_usuario, n.meses_neg, n.pior_saldo, p.parcelas_total, p.meses_com_parcela, a.assin_media, f.encargos
FROM neg n
LEFT JOIN parc p USING (id_usuario)
LEFT JOIN assin a USING (id_usuario)
LEFT JOIN fin f USING (id_usuario)
WHERE n.meses_neg >= 2 AND p.parcelas_total IS NOT NULL
ORDER BY n.meses_neg DESC, f.encargos DESC NULLS LAST, n.pior_saldo
LIMIT 50;

-- 6) Extrato completo de um candidato a "Cleide" (troque o id)
-- SELECT DATE(anomesdia) dia, tipo, descr, vlr, nom_cate_macro, saldo_apos, parcela_atual, parcela_total
-- FROM `hackathon_dados.extrato_sintetico` WHERE id_usuario = '2e85f8ba-452e-4dff-bbfc-f3cdce456263' ORDER BY anomesdia;
