export type Bloco = { tipo: string; dados: any }

export type Mensagem = {
  id: string
  autor: 'zera' | 'cliente' | 'sistema'
  texto?: string
  blocos?: Bloco[]
  guardrail?: { camada: 'entrada' | 'saida'; tipo: string }
  ts: number
}

export type RespostaChat = {
  texto: string
  ui: Bloco[]
  estado?: { alucinacao_numerica?: number; bloqueios_consentimento?: number; vulneravel?: boolean; gatilho?: any[]; bloqueios_guardrail?: any[] }
}

export type Gatilho = { tipo: 'dinheiro_extra' | 'risco_parcela' | 'pre_negativacao'; mensagem: string; valor?: number; parcela?: number; sobra_prevista?: number; vencimento?: string }

export type EstadoDemo = { hoje: string; gatilhos: Gatilho[]; acordo: any | null }
