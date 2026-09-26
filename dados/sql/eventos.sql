-- Tabela de eventos do agente (aceite, consentimento, respiro, amortização) para Looker Studio / experimentos
CREATE TABLE IF NOT EXISTS `zera.eventos` (
  evento_id STRING,
  cliente_id STRING,
  sessao_id STRING,
  tipo STRING,                 -- diagnostico_visto | plano_proposto | consentimento_registrado | acordo_fechado | respiro_acionado | amortizacao | escalado_humano
  payload JSON,
  variante_experimento STRING, -- A = parcela que cabe + respiro | B = padrão
  data_simulada DATE,
  timestamp TIMESTAMP
)
PARTITION BY DATE(timestamp);
