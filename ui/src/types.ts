/* Contrato estruturado da experiência zera.ai (spec v1 §12–§17). O front renderiza por `response_type`, nunca pelo texto. */

export type Estado = 'IDLE' | 'EVALUATING' | 'NEEDS_INFORMATION' | 'CALCULATING' | 'SHOWING_OPTIONS' | 'EXPLAINING' | 'REVIEWING'
  | 'AWAITING_CONFIRMATION' | 'EXECUTING' | 'COMPLETED' | 'NO_SUITABLE_OPTION' | 'ERROR'

export type TipoResposta = 'PROACTIVE_MESSAGE' | 'TEXT' | 'QUESTION' | 'STATUS' | 'SUMMARY' | 'OPTIONS_COMPARISON' | 'OPTION_DETAIL'
  | 'TERMS_REVIEW' | 'CONFIRMATION_REQUEST' | 'SUCCESS' | 'ERROR'

export type Acao = 'START' | 'ANSWER' | 'VIEW_OPTIONS' | 'ASK_WHY' | 'ASK_QUESTION' | 'SELECT_OPTION' | 'CONTINUE' | 'SET_AUTOPAY'
  | 'CONFIRM' | 'CANCEL' | 'DISMISS' | 'RESET' | 'GET' | 'ESCALATE' | 'RETRY' | 'ADJUST' | 'FOLLOW' | 'HOME' | 'CANCEL_AUTOPAY'

export type Beneficio = {
  benefit_type: string; monthly_difference?: number; total_difference?: number; basis?: string
  current_monthly_payment?: number; proposed_monthly_payment?: number; regular_payment?: number; autopay_payment?: number; monthly_discount?: number
  current_rate_pct?: number; proposed_rate_pct?: number; term_months?: number
}

export type AcaoDivida = { divida_id: string; nome: string; instituicao: string; saldo: number; acao: string; parcela: number; prazo: number; entrada: number; usa_caixa: number; descricao: string; taxa_hoje?: number }

export type Opcao = {
  id: string; cenario_id: string; objective: string; label: string; description: string; recommended: boolean; highlight: boolean
  monthly_payment: number; agreement_payment: number; term_months: number; total_cost: number; total_installments: number; interest_total: number
  rate_monthly_pct: number; cet_annual_pct: number; principal: number; consolidated_balance: number
  down_payment: number; payoffs_value: number; reserve: number; uses_cash: number; bank_gain: number; bank_receives: number
  today_same_term: { prazo_meses: number; parcela: number; total: number; juros: number }; savings_same_term: number
  payments_count: number; freed_per_month: number
  benefits: Beneficio[]; claims: string[]; tradeoffs: string[]; actions: AcaoDivida[]; resolve_negativacao: boolean
  autopay: { desconto_mensal: number; parcela_com_desconto: number; total_com_desconto: number }
}

export type DividaHoje = { divida_id: string; nome: string; instituicao: string; produto: string; saldo: number; pagamento_mensal: number; juros_mes: number; prazo_meses: number | null; dias_atraso: number; taxa_mensal_pct: number; rotativo: boolean; fonte: string; descricao: string }

export type SituacaoHoje = {
  pagamento_mensal: number; qtd_pagamentos: number; prazo_meses: number | null; prazo_indefinido: boolean
  saldo_devedor: number; juros_mensais: number; taxa_maxima_pct: number; taxa_media_pct: number; amortiza_por_mes: number
  projecoes: Record<string, { prazo_meses: number; parcela: number; total: number; juros: number }>; dividas: DividaHoje[]; maior_atraso: number
}

export type DividaIncluida = { divida_id: string; nome: string; instituicao: string; saldo: number; taxa_hoje_pct: number; acao: string; parcela: number; prazo: number; usa_caixa: number; entrada: number; saldo_base: number; fonte: string; descricao: string }

export type Termos = {
  cenario_id: string; parcela_mensal: number; parcela_acordo: number; compromissos_mantidos_mes: number; desconto_debito_automatico: number
  prazo_meses: number; total_a_pagar: number; entrada: number; quitacoes_valor: number; abatimentos_valor: number; total_parcelas: number
  saldo_original: number; saldo_consolidado: number; juros_acordo: number; taxa_mensal_pct: number; cet_mensal_pct: number; cet_anual_pct: number
  primeiro_vencimento: string; ultimo_vencimento: string; debito_automatico: boolean
  dividas_incluidas: DividaIncluida[]; quitacoes: DividaIncluida[]; renegociacoes: DividaIncluida[]; mantidas: DividaIncluida[]
  reducao_mensal?: number; pagamento_antes?: number
}

export type QuickReply = { id: string; label: string; hint?: string; acao?: Acao; payload?: Record<string, unknown>; text?: string
  input?: { campo: string; tipo: string; placeholder?: string } }

export type Diagnostico = { parcela_minima_possivel?: number; prazo_da_parcela_minima?: number; parcela_maxima?: number; parcela_disponivel?: number
  falta_por_mes?: number; entrada_necessaria?: number | null; reducao_gastos_necessaria?: number; meses_em_que_nao_cabe?: string[]; respiros?: number; motivo?: string; valor_extra?: number }

export type Contexto = { cliente: string; persona: boolean; fonte: string; renda_desconhecida: boolean; renda_informada: number | null
  compromissos: Array<{ descricao: string; valor_mensal: number; data: string }>; valor_extra: number; parcela_maxima: number; parcela_conforto: number | null
  hoje_simulado: string; escalado: { protocolo: string } | null; autopay: boolean | null }

export type Resposta = {
  state: Estado; response_type: TipoResposta
  content: { title: string; description: string }
  options: Opcao[]; quick_replies: QuickReply[]
  allowed_actions: string[]; requires_confirmation: boolean; disclaimer?: string
  cta?: string; status?: { title: string; steps: string[] }; question?: 'renda' | 'gasto_recorrente' | 'autopay'
  summary?: SituacaoHoje; current?: SituacaoHoje; option?: Opcao; benefit?: Beneficio; claims?: string[]; tradeoffs?: string[]; criteria?: string[]
  terms?: Termos; final_terms?: Termos | null; selected_option?: Opcao; benefits?: Beneficio[]; account?: { banco: string; agencia: string; conta: string } | null
  agreement?: any; result?: { new_monthly_payment: number; first_due_date: string; last_due_date?: string; monthly_reduction: number }; next_steps?: string[]
  notice?: string; autopay?: boolean | null; error?: string; guardrail?: { camada: string; tipo: string }
  silent?: boolean; checks?: Record<string, boolean>; trigger?: string; reason?: string; repetida?: boolean; acompanhamento?: boolean
  diagnosis?: Diagnostico; paths?: string[]; escalation?: { protocolo: string; previsao_contato: string }; llm?: boolean
  context?: Contexto; jornada_id?: string; finops?: { chamadas: number; tokens_entrada: number; tokens_saida: number; custo_usd: number }
  compromissos?: Array<{ descricao: string; valor_mensal: number }>
}

export type Preferencias = { analisar: boolean; momentos: boolean; recomendar: boolean; avisar: boolean; open_finance: boolean }
export type EstadoDemo = { hoje: string; gatilhos: any[]; acordo: any | null }

export type PerfilResumo = { cliente_id: string; nome: string; persona: boolean; medoide?: boolean; cluster: number | null; distancia: number | null
  renda_mediana: number; renda_conhecida: boolean; total_dividas: number; qtd_dividas: number; meses_no_vermelho: number | null
  sinais: string; fonte_dividas: string; fonte: string; segmentacao?: string; score?: number }
export type Clientes = { fonte: string; perfis: PerfilResumo[]; clusters: Array<Record<string, any>> }
export type Perfil = { cliente_id: string; nome: string; persona: boolean; fonte: string; renda_desconhecida: boolean; renda_mediana: number
  essenciais_mediana: number; total_dividas: number; custo_total_mensal: number; dividas: any[]; capacidade: any; hoje_simulado: string; gatilhos: any[]; acordo: any | null }

/* ---------- conversa com o agente ADK ---------- */
export type CardChat = { tipo: string; dados: any }
export type Hitl = { request_id: string; tool: string; args: Record<string, unknown>; hint: string; titulo: string; detalhes: Array<{ k: string; v: string }>; resumo?: string; frase_sugerida: string }
export type EventoChat =
  | { tipo: 'tool_call'; nome: string; args: Record<string, unknown>; rotulo: string }
  | { tipo: 'tool_result'; nome: string; ok: boolean; explicacao: string }
  | { tipo: 'card'; bloco: CardChat }
  | { tipo: 'texto'; texto: string }
  | { tipo: 'llm'; tokens_entrada: number; tokens_saida: number; custo_usd: number }
  | { tipo: 'hitl'; hitl: Hitl }
  | { tipo: 'guardrail'; guardrail: { camada: string; tipo: string; trecho?: string } }
  | { tipo: 'erro'; erro: string; texto: string }
  | { tipo: 'fim'; sugestoes: string[]; finops: { chamadas: number; tokens_entrada: number; tokens_saida: number; custo_usd: number }; estado: Record<string, unknown>; acordo: any | null }
export type ChatInicio = { texto: string; sugestoes: string[]; protecoes: string[]; cliente: string; hoje_simulado: string; sessao_id: string }
