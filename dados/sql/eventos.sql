-- Estado e eventos do Zera no BigQuery (Firestore não está liberado no projeto do evento).
-- Ambas append-only via streaming insert (zera_agent/contexto.py: RepositorioBigQuery).

-- Snapshot do estado do cliente (acordo, consentimentos, gatilhos, memória). Leitura = último snapshot por cliente.
CREATE TABLE IF NOT EXISTS `zera.estado_cliente` (
  cliente_id STRING NOT NULL,
  gravado_em TIMESTAMP NOT NULL,
  apagado BOOL NOT NULL,            -- true = direito de esquecer (LGPD)
  estado STRING                     -- JSON serializado
)
PARTITION BY DATE(gravado_em)
CLUSTER BY cliente_id;

-- Eventos de negócio e de guardrail (aceite, consentimento, respiro, amortização, guardrail_bloqueio...) -> Looker Studio
CREATE TABLE IF NOT EXISTS `zera.eventos` (
  evento_id STRING,
  cliente_id STRING,
  sessao_id STRING,
  tipo STRING,                      -- cenarios_propostos | consentimento_registrado | acordo_fechado | respiro_acionado | amortizacao | escalado_humano | guardrail_bloqueio | tempo_avancado
  payload STRING,                   -- JSON serializado
  variante_experimento STRING,      -- A = parcela que cabe + respiro | B = padrão
  data_simulada DATE,
  timestamp TIMESTAMP
)
PARTITION BY DATE(timestamp)
CLUSTER BY cliente_id, tipo;

-- Visão de estado atual (1 linha por cliente)
CREATE OR REPLACE VIEW `zera.estado_atual` AS
SELECT * EXCEPT(rn) FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY gravado_em DESC) AS rn
  FROM `zera.estado_cliente`
) WHERE rn = 1 AND NOT apagado;
