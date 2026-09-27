/* Contrato estruturado da experiência zera.ai (spec v1 §12–§17). O front renderiza por `response_type`. */

export type Estado = 'IDLE' | 'EVALUATING' | 'NEEDS_INFORMATION' | 'CALCULATING' | 'SHOWING_OPTIONS' | 'EXPLAINING' | 'REVIEWING'
  | 'AWAITING_CONFIRMATION' | 'EXECUTING' | 'COMPLETED' | 'NO_SUITABLE_OPTION' | 'ERROR'

export type TipoResposta = 'PROACTIVE_MESSAGE' | 'TEXT' | 'QUESTION' | 'STATUS' | 'SUMMARY' | 'OPTIONS_COMPARISON' | 'OPTION_DETAIL'
  | 'TERMS_REVIEW' | 'CONFIRMATION_REQUEST' | 'SUCCESS' | 'ERROR'

export type Acao = 'START' | 'ANSWER' | 'VIEW_OPTIONS' | 'ASK_WHY' | 'ASK_QUESTION' | 'SELECT_OPTION' | 'CONTINUE' | 'SET_AUTOPAY'
  | 'CONFIRM' | 'CANCEL' | 'DISMISS' | 'RESET' | 'GET' | 'ESCALATE' | 'RETRY' | 'FOLLOW' | 'HOME'

export type Beneficio = { benefit_type: string; monthly_difference?: number; total_difference?: number; current_monthly_payment?: number; proposed_monthly_payment?: number; regular_payment?: number; autopay_payment?: number; monthly_discount?: number }

export type Opcao = {
  id: string; cenario_id: string; objective: string; label: string; description: string; recommended: boolean
  monthly_payment: number; term_months: number; total_cost: number; payments_count: number; reserve: number; uses_cash: number
  benefits: Beneficio[]; claims: string[]; tradeoffs: string[]; actions: any[]; resolve_negativacao: boolean
  autopay: { desconto_mensal: number; parcela_com_desconto: number; total_com_desconto: number }
}

export type SituacaoHoje = { pagamento_mensal: number; qtd_pagamentos: number; prazo_meses: number; total_a_pagar: number; dividas: Array<{ divida_id: string; nome: string; instituicao: string; saldo: number; pagamento_mensal: number; dias_atraso: number }> }

export type Termos = { parcela_mensal: number; desconto_debito_automatico: number; prazo_meses: number; total_a_pagar: number; cet_mensal_pct: number; primeiro_vencimento: string; debito_automatico: boolean; dividas_incluidas: Array<{ nome: string; instituicao: string; saldo: number; acao: string }> }

export type Resposta = {
  state: Estado; response_type: TipoResposta
  content: { title: string; description: string }
  options: Opcao[]; quick_replies: Array<{ id: string; label: string; hint?: string; input?: { campo: string; tipo: string } }>
  allowed_actions: string[]; requires_confirmation: boolean; disclaimer?: string
  cta?: string; status?: { title: string; steps: string[] }
  summary?: SituacaoHoje; current?: SituacaoHoje; option?: Opcao; benefit?: Beneficio; claims?: string[]; tradeoffs?: string[]; criteria?: string[]
  terms?: Termos; final_terms?: Termos; selected_option?: Opcao; benefits?: Beneficio[]; account?: { banco: string; agencia: string; conta: string } | null
  agreement?: any; result?: { new_monthly_payment: number; first_due_date: string; monthly_reduction: number }; next_steps?: string[]
  notice?: string; autopay?: boolean | null; error?: string; guardrail?: { camada: string; tipo: string }
  silent?: boolean; checks?: Record<string, boolean>; trigger?: string; reason?: string
}

export type Preferencias = { analisar: boolean; momentos: boolean; recomendar: boolean; avisar: boolean; open_finance: boolean }
export type EstadoDemo = { hoje: string; gatilhos: any[]; acordo: any | null }
