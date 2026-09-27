-- Amostra local REAL e completa para ZERA_FONTE=amostra: TODOS os lançamentos (entradas e saídas, todos os meses) dos
-- clientes mais parecidos com a persona do quadro de produto. Substitui o export anterior, que veio de um `LIMIT 10000`
-- ordenado por `descr`: 10 mil linhas só de janeiro/2025, só saídas ("assin…"), sem nenhuma entrada -> todo perfil ficava
-- "renda não identificada", a proatividade ficava em silêncio (dados insuficientes) e a capacidade dava zero.
--
-- Como rodar (máquina com gcloud/bq, ou Cloud Shell), a partir da raiz do repo:
--   bq query --project_id=batalha-time-03-vhxk --use_legacy_sql=false --format=csv --max_rows=2000000 \
--     < dados/sql/exportar_amostra.sql > dados/amostra_bq_extrato_sintetico.csv   # por stdin: o bq lê "-- …" do arquivo como flags se for argumento
--   uv run python -c "import pandas as pd; d=pd.read_csv('dados/amostra_bq_extrato_sintetico.csv'); print(len(d), d.id_usuario.nunique(), sorted(d.anomes.unique())[:3], d.tipo.value_counts().to_dict())"
--
-- Se `zera.perfis_demo` já existir (python -m dados.publicar_bq), prefira os perfis do cluster-alvo do k-means:
--   troque a CTE `cand` por:  SELECT id_usuario FROM `batalha-time-03-vhxk.zera.perfis_demo`
--
-- Critério (mesmos sinais do índice de endividamento de clusterizacao.sql, sem modelo): clientes com pelo menos 6 meses,
-- com entradas identificadas (tipo = 'E') primeiro, mais meses no vermelho, mais sinais de rotativo/empréstimo, mais
-- parcelamentos. 40 clientes × 12 meses ≈ 40–60 mil linhas (alguns MB). Nada é sintetizado: são linhas da base do evento.
WITH m AS (
  SELECT
    id_usuario, anomes,
    SUM(IF(UPPER(tipo) = 'E', vlr, 0))                                                        AS renda,
    MIN(saldo_apos)                                                                           AS saldo_min,
    COUNTIF(parcela_total IS NOT NULL)                                                        AS parcelas,
    COUNTIF(REGEXP_CONTAINS(LOWER(descr), r'minimo|mínimo|rotativo|emprest|financ|juros'))   AS sinais
  FROM `batalha-time-03-vhxk.hackathon_dados.extrato_sintetico`
  GROUP BY id_usuario, anomes
),
c AS (
  SELECT
    id_usuario,
    COUNT(*)                   AS n_meses,
    COUNTIF(renda > 0)         AS meses_com_renda,
    COUNTIF(saldo_min < 0)     AS meses_no_vermelho,
    MIN(saldo_min)             AS pior_saldo,
    AVG(parcelas)              AS parcelas_media,
    SUM(sinais)                AS sinais
  FROM m
  GROUP BY id_usuario
),
cand AS (
  SELECT id_usuario
  FROM c
  WHERE n_meses >= 6
  ORDER BY (meses_com_renda > 0) DESC, meses_no_vermelho DESC, sinais DESC, parcelas_media DESC, pior_saldo
  LIMIT 40
)
SELECT
  x.id_usuario, x.anomesdia, x.anomes, x.tipo, x.descr, x.vlr, x.nom_cate_macro, x.nom_cate_micro,
  x.saldo_apos, x.parcela_atual, x.parcela_total
FROM `batalha-time-03-vhxk.hackathon_dados.extrato_sintetico` x
JOIN cand USING (id_usuario)
ORDER BY x.id_usuario, x.anomesdia;
