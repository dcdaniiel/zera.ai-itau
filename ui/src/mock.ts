/* Modo demo/offline: respostas roteirizadas com os MESMOS números que o motor produz para a Cleide
   (tests/test_motor.py). Serve como protótipo clicável e como plano B se o LLM/API cair. */

import type { Bloco, EstadoDemo, Gatilho, RespostaChat } from './types'

export const MESES = ['2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09']
const SOBRA = [800, 950, 1150, 200, 420, 750, 850, 650, 800, 250, 900, 750]

export const RAIO_X: Bloco = {
  tipo: 'raio_x',
  dados: {
    cliente: 'Cleide', hoje: '2026-09-26', total_dividas: 6800, custo_total_mensal: 641.5,
    renda_mediana: 2325, essenciais_mediana: 1550, sobra_mediana: 775, tem_reserva: false,
    meses: MESES, sobra_por_mes: Object.fromEntries(MESES.map((m, i) => [m, SOBRA[i]])),
    dividas: [
      { divida_id: 'dv_cartao', produto: 'cartao_rotativo', nome: 'Cartão (rotativo)', saldo: 3200, taxa_mensal: 0.14, custo_mensal: 448, dias_atraso: 60, consequencia: 'negativacao', prioridade: 1 },
      { divida_id: 'dv_emprestimo', produto: 'emprestimo', nome: 'Empréstimo pessoal', saldo: 2700, taxa_mensal: 0.045, custo_mensal: 121.5, dias_atraso: 60, consequencia: 'negativacao', prioridade: 2 },
      { divida_id: 'dv_cheque', produto: 'cheque_especial', nome: 'Cheque especial', saldo: 900, taxa_mensal: 0.08, custo_mensal: 72, dias_atraso: 0, consequencia: 'nenhuma', prioridade: 3 },
    ],
  },
}

export const CAPACIDADE: Bloco = {
  tipo: 'capacidade',
  dados: { sobra_p25: 592.5, colchao: 116.25, sobra_segura: 476.25, parcela_maxima: 357.19, parcela_conforto: 250.03, meses_fracos: ['2026-01', '2026-07'], respiros_ano: 2, sobra_mediana: 775, meses: MESES, sobra_mensal: SOBRA, perfil_risco: 'renda_irregular' },
}

const acoes = (c: Array<[string, string, string, number, number, number]>) =>
  c.map(([acao, id, nome, usa, parcela, prazo]) => ({ acao, divida_id: id, nome, usa_caixa: usa, parcela, prazo, desconto_pct: acao === 'quitar' ? 0.2 : id === 'dv_cheque' ? 0 : 0.08 }))

export const CENARIOS: Bloco = {
  tipo: 'cenarios',
  dados: {
    valor_extra: 2800, reserva_minima: 116.25, caixa_disponivel: 2683.75, parcela_maxima: 357.19, parcela_conforto: 250.03, perfil_risco: 'renda_irregular',
    prazos_oferecidos: [12, 18, 24, 36], recomendado: 'C1', total_combinacoes_avaliadas: 55,
    plano_padrao: { parcela: 573.55, prazo: 12, meses_em_que_nao_cabe: ['2026-01', '2026-02', '2026-05', '2026-07'] },
    cenarios: [
      { id: 'C1', rotulos: ['recomendado'], comprometimento_mensal: 241, parcela_mensal: 241, prazo_meses: 18, custo_total: 6402.94, reserva: 240, resolve_negativacao: true, respiros: 2,
        acoes: acoes([['quitar', 'dv_cartao', 'Cartão (rotativo)', 2560, 0, 0], ['renegociar_12x', 'dv_cheque', 'Cheque especial', 0, 82.51, 12], ['renegociar_18x', 'dv_emprestimo', 'Empréstimo pessoal', 0, 158.49, 18]]) },
      { id: 'C2', rotulos: ['mais_barato'], comprometimento_mensal: 285.16, parcela_mensal: 285.16, prazo_meses: 18, custo_total: 6326.5, reserva: 240, resolve_negativacao: true, respiros: 2,
        acoes: acoes([['quitar', 'dv_cartao', 'Cartão (rotativo)', 2560, 0, 0], ['renegociar_18x', 'dv_cheque', 'Cheque especial', 0, 57.43, 18], ['renegociar_12x', 'dv_emprestimo', 'Empréstimo pessoal', 0, 227.73, 12]]) },
      { id: 'C3', rotulos: ['mais_folga'], comprometimento_mensal: 122.34, parcela_mensal: 122.34, prazo_meses: 36, custo_total: 6964.24, reserva: 240, resolve_negativacao: true, respiros: 2,
        acoes: acoes([['quitar', 'dv_cartao', 'Cartão (rotativo)', 2560, 0, 0], ['renegociar_36x', 'dv_cheque', 'Cheque especial', 0, 32.54, 36], ['renegociar_36x', 'dv_emprestimo', 'Empréstimo pessoal', 0, 89.8, 36]]) },
      { id: 'C4', rotulos: ['mais_rapido'], comprometimento_mensal: 299.73, parcela_mensal: 227.73, juros_mantidos_mes: 72, prazo_meses: 12, custo_total: 7056.76, reserva: 240, resolve_negativacao: true, respiros: 2,
        acoes: acoes([['quitar', 'dv_cartao', 'Cartão (rotativo)', 2560, 0, 0], ['manter', 'dv_cheque', 'Cheque especial', 0, 72, 0], ['renegociar_12x', 'dv_emprestimo', 'Empréstimo pessoal', 0, 227.73, 12]]) },
    ],
  },
}

export const ACORDO = (pagas = 0, respiros = 0, proximo = '2026-10-10'): Bloco => ({
  tipo: 'acordo',
  dados: {
    acordo_id: 'ac_demo', status: 'ativo', parcela: 241, prazo: 18, pagas, restantes: 18 - pagas, respiros_max: 2, respiros_usados: respiros,
    saldo_devedor: pagas === 0 ? 3384 : 2838.6, proximo_vencimento: proximo,
    quitacoes: [{ nome: 'Cartão (rotativo)', valor_pago: 2560, desconto_valor: 640 }],
    componentes: [
      { nome: 'Cheque especial', parcela: 82.51, prazo: 12, pagas, status: 'ativo' },
      { nome: 'Empréstimo pessoal', parcela: 158.49, prazo: 18, pagas, status: 'ativo' },
    ],
  },
})

export const GATILHO_EXTRA: Gatilho = { tipo: 'dinheiro_extra', valor: 2800, mensagem: 'Entrou R$ 2.800 (PIX — renda extra) — dá para quitar e renegociar com desconto.' }
export const GATILHO_RISCO: Gatilho = { tipo: 'risco_parcela', parcela: 241, sobra_prevista: 200, vencimento: '2027-01-10', mensagem: 'Parcela de R$ 241 vence em 3 dias e a sobra prevista é R$ 200.' }

export const ESTADO_INICIAL: EstadoDemo = { hoje: '2026-09-26', gatilhos: [GATILHO_EXTRA], acordo: null }

/* ---------- roteiro ---------- */
type Passo = 'inicio' | 'raio_x' | 'cenarios' | 'aguardando_confirmacao' | 'acordo' | 'risco' | 'aguardando_respiro' | 'respiro_ok'

let passo: Passo = 'inicio'
let estado: EstadoDemo = { ...ESTADO_INICIAL }

const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

const BLOQUEIO_ENTRADA = /(ignore .*(regras|instru)|system prompt|voce agora e|senha|token|\bpix (para|pra)|transfer|dividas? d[oa] (meu|minha)|investir|bitcoin|cripto|emprestimo novo)/

export const mock = {
  reset(): EstadoDemo {
    passo = 'inicio'
    estado = { hoje: '2026-09-26', gatilhos: [GATILHO_EXTRA], acordo: null }
    return estado
  },
  estado(): EstadoDemo { return estado },

  async simularTempo(ate: string): Promise<EstadoDemo> {
    if (ate >= '2027-01-01' && estado.acordo) {
      estado = { hoje: ate, gatilhos: [GATILHO_RISCO], acordo: { ...ACORDO(3, 0, '2027-01-10').dados } }
      passo = 'risco'
    } else {
      estado = { ...estado, hoje: ate, gatilhos: [] }
    }
    return estado
  },

  async chat(mensagem: string): Promise<RespostaChat> {
    await new Promise((r) => setTimeout(r, 650 + Math.random() * 500))
    const m = norm(mensagem)

    if (BLOQUEIO_ENTRADA.test(m)) {
      return { texto: 'Por segurança eu não peço nem uso senhas, códigos ou dados de outras pessoas, e não faço transferências. Aqui eu só cuido das suas dívidas: quer ver as opções que cabem no seu mês?', ui: [], estado: { bloqueios_guardrail: [{ camada: 'entrada', tipo: 'engenharia_social' }] } }
    }
    if (/nao aguento|desesper|acabar com tudo/.test(m)) {
      return { texto: 'Cleide, sinto muito que esteja tão pesado. Não vamos falar de números agora. Posso pedir para uma pessoa do time te ligar hoje? Protocolo ZR-4F2A1C.', ui: [] }
    }

    if (passo === 'risco' || (estado.gatilhos[0]?.tipo === 'risco_parcela' && passo !== 'aguardando_respiro' && passo !== 'respiro_ok')) {
      passo = 'aguardando_respiro'
      return { texto: 'Cleide, vi que janeiro está apertado: a sobra prevista é R$ 200,00 e a parcela de R$ 241,00 vence dia 10. Você tem 2 respiros no acordo. Quer usar 1 agora? A parcela de janeiro vai para o fim, sem juros nem mora.', ui: [ACORDO(3, 0, '2027-01-10')] }
    }
    if (passo === 'aguardando_respiro') {
      if (/sim|quero|pode|confirmo|usar/.test(m)) {
        passo = 'respiro_ok'
        estado = { ...estado, gatilhos: [], acordo: ACORDO(3, 1, '2027-02-10').dados }
        return { texto: 'Feito. A parcela de janeiro foi para o fim do acordo, sem juros nem multa. Próximo vencimento: 10/02. Você ainda tem 1 respiro para este ano. Fevereiro costuma ser melhor — vou te avisar 3 dias antes.', ui: [ACORDO(3, 1, '2027-02-10')] }
      }
      passo = 'respiro_ok'
      return { texto: 'Combinado, mantemos a parcela de janeiro. Se mudar de ideia até o dia 10, é só me chamar.', ui: [] }
    }

    if (passo === 'inicio' || /quanto (eu )?devo|entrou|dinheiro|2\.?800|raio/.test(m)) {
      passo = 'raio_x'
      return {
        texto: 'Cleide, entrou R$ 2.800,00 hoje. Antes de esse dinheiro sumir no vermelho, olhei suas dívidas: você deve R$ 6.800,00 e a dívida cresce R$ 641,50 por mês só de juros. A que mais custa é o cartão (14% ao mês). Nos seus últimos 12 meses, depois das contas essenciais sobra em média R$ 775,00 — mas janeiro e julho apertam. Por isso a parcela segura para você é até R$ 357,19, e eu trabalho com R$ 250,03 de conforto porque sua renda varia. Quer ver o melhor uso desse dinheiro?',
        ui: [RAIO_X, CAPACIDADE],
      }
    }
    if (passo === 'raio_x' || /cenari|opcoes|melhor uso|ver/.test(m)) {
      passo = 'cenarios'
      return {
        texto: 'Avaliei 55 combinações. A que recomendo: quitar o cartão à vista por R$ 2.560,00 (20% de desconto), renegociar o empréstimo em 18x de R$ 158,49 e o cheque especial em 12x de R$ 82,51. Fica R$ 241,00 por mês por 18 meses, R$ 240,00 sobram como reserva e todas as dívidas saem do atraso. A renegociação padrão seria 12x de R$ 573,55 — não caberia em 4 dos últimos 12 meses.',
        ui: [CENARIOS],
      }
    }
    if (passo === 'cenarios' && /recomendad|c1|quero|esse/.test(m)) {
      passo = 'aguardando_confirmacao'
      return { texto: 'Só para confirmar: fechar o acordo com quitação do cartão por R$ 2.560,00, empréstimo em 18x de R$ 158,49 e cheque especial em 12x de R$ 82,51 — total de R$ 241,00 por mês, primeira parcela em 10/10/2026, com 2 respiros por ano. Você confirma?', ui: [] }
    }
    if (passo === 'aguardando_confirmacao') {
      if (/sim|confirmo|pode|fecha/.test(m)) {
        passo = 'acordo'
        estado = { ...estado, gatilhos: [], acordo: ACORDO().dados }
        return { texto: 'Acordo fechado. Cartão quitado por R$ 2.560,00; empréstimo em 18x de R$ 158,49 e cheque especial em 12x de R$ 82,51 — R$ 241,00 por mês, primeira parcela em 10/10/2026. Se um mês apertar, você tem 2 respiros. Eu te aviso 3 dias antes de cada vencimento.', ui: [ACORDO()] }
      }
      passo = 'cenarios'
      return { texto: 'Sem pressa. Posso mostrar as alternativas: mais barato (R$ 285,16/mês), mais folga (R$ 122,34/mês em 36x) ou mais rápido (12x). Qual você quer ver?', ui: [] }
    }
    if (/folga|barato|rapido|alternativ/.test(m)) {
      return { texto: 'Mais barato: cartão à vista + cheque em 18x de R$ 57,43 + empréstimo em 12x de R$ 227,73 → R$ 285,16/mês (custo total R$ 6.326,50). Mais folga: cheque e empréstimo em 36x → R$ 122,34/mês (custo total R$ 6.964,24). Mais rápido: empréstimo em 12x e cheque mantido → R$ 227,73 + R$ 72,00 de juros/mês. O recomendado equilibra custo e folga. Qual você prefere?', ui: [CENARIOS] }
    }
    return { texto: 'Posso te mostrar o raio-X das dívidas, os cenários que cabem no seu mês ou o status do acordo. O que prefere?', ui: [] }
  },
}
