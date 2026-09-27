/* Cliente HTTP da API zera.ai (api/main.py). Sem mock: toda tela vem do backend (núcleo determinístico + agente + BigQuery).
   Em dev, /api é proxied pelo Vite para http://localhost:8080; em produção a própria API serve a UI (mesma origem). */

import type { Acao, ChatInicio, Clientes, EstadoDemo, EventoChat, Hitl, Perfil, Preferencias, Resposta } from './types'

const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? '/api' : '')
const SESSAO_ID = `ui-${Math.random().toString(36).slice(2, 8)}`

/** cliente selecionado na tela de perfis (persistido na URL: ?cliente=...) */
let clienteId: string = new URLSearchParams(window.location.search).get('cliente') ?? import.meta.env.VITE_CLIENTE_ID ?? ''
export const getCliente = () => clienteId
export function setCliente(id: string) {
  clienteId = id
  const url = new URL(window.location.href)
  url.searchParams.set('cliente', id)
  window.history.replaceState({}, '', url.toString())
}

export class ApiError extends Error {
  status?: number
  constructor(message: string, status?: number) { super(message); this.status = status }
}

async function req<T>(path: string, init?: RequestInit, timeoutMs = 60_000): Promise<T> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal, ...init })
    if (!r.ok) throw new ApiError(`${r.status} ${(await r.text()).slice(0, 200)}`, r.status)
    return (await r.json()) as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError(e instanceof Error && e.name === 'AbortError' ? 'A zera.ai demorou demais para responder.' : 'Não foi possível falar com a zera.ai agora.')
  } finally { clearTimeout(t) }
}

/** Converte falha de rede/servidor no contrato ERROR da spec — a UI renderiza a tela de recuperação (AT09). */
function comoErro(e: unknown, state: Resposta['state'] = 'ERROR'): Resposta {
  const msg = e instanceof Error ? e.message : String(e)
  return { state, response_type: 'ERROR', content: { title: 'Não consegui concluir esta etapa agora.', description: 'Nenhum valor foi inventado. Você pode tentar de novo em instantes ou falar com uma pessoa do time.' },
    options: [], quick_replies: [{ id: 'RETRY', label: 'Tentar de novo', acao: 'RETRY' }, { id: 'ESCALATE', label: 'Falar com uma pessoa', acao: 'ESCALATE' }],
    allowed_actions: ['RETRY', 'ESCALATE', 'HOME'], requires_confirmation: false, error: msg }
}

const base = () => `/v1/clientes/${encodeURIComponent(clienteId)}`

export const api = {
  health: () => req<{ ok: boolean; modelo: string; fonte: string; versao: string }>('/health', undefined, 8_000),
  clientes: () => req<Clientes>('/v1/clientes', undefined, 30_000),
  perfil: () => req<Perfil>(`${base()}/perfil`),
  preferencias: (p: Preferencias) => req<{ ok: boolean }>(`${base()}/preferencias`, { method: 'POST', body: JSON.stringify(p) }),
  proativa: () => req<Resposta>(`${base()}/proativa`),
  experiencia: async (): Promise<Resposta> => { try { return await req<Resposta>(`${base()}/experiencia`) } catch (e) { return comoErro(e) } },
  evento: async (acao: Acao, payload: Record<string, unknown> = {}): Promise<Resposta> => {
    try { return await req<Resposta>(`${base()}/experiencia/evento`, { method: 'POST', body: JSON.stringify({ acao, payload, sessao_id: SESSAO_ID }) }) }
    catch (e) { return comoErro(e) }
  },
  estado: () => req<EstadoDemo>(`/gatilhos/${encodeURIComponent(clienteId)}`),
  simularTempo: (ate: string) => req<EstadoDemo>('/simular_tempo', { method: 'POST', body: JSON.stringify({ cliente_id: clienteId, ate }) }),
  reset: () => req<unknown>(`/reset/${encodeURIComponent(clienteId)}`, { method: 'POST' }),
  metrics: () => req<any>('/metrics', undefined, 8_000),
  // --- conversa com o agente ADK (tools + guardrails + HITL) ---
  chatInicio: (sessaoId: string) => req<ChatInicio>(`/chat/inicio?cliente_id=${encodeURIComponent(clienteId)}&sessao_id=${encodeURIComponent(sessaoId)}`),
  chatStream: (sessaoId: string, mensagem: string, onEvento: (e: EventoChat) => void) =>
    stream('/chat/stream', { cliente_id: clienteId, sessao_id: sessaoId, mensagem }, onEvento),
  chatContratar: (sessaoId: string, cenario_id: string) => req<{ hitl: Hitl; etapa: string }>('/chat/contratar', { method: 'POST', body: JSON.stringify({ cliente_id: clienteId, sessao_id: sessaoId, cenario_id }) }),
  chatConfirmar: (sessaoId: string, request_id: string, confirmed: boolean, frase: string, onEvento: (e: EventoChat) => void) =>
    stream('/chat/confirmar/stream', { cliente_id: clienteId, sessao_id: sessaoId, request_id, confirmed, frase }, onEvento),
}

/** Lê NDJSON do backend e entrega cada evento do ADK assim que chega (tool_call, tool_result, card, texto, hitl, guardrail, fim). */
async function stream(path: string, body: unknown, onEvento: (e: EventoChat) => void): Promise<void> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), 120_000)
  try {
    const r = await fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal })
    if (!r.ok || !r.body) throw new ApiError(`${r.status} ${(await r.text()).slice(0, 200)}`, r.status)
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const linhas = buf.split('\n'); buf = linhas.pop() ?? ''
      for (const l of linhas) if (l.trim()) onEvento(JSON.parse(l) as EventoChat)
    }
    if (buf.trim()) onEvento(JSON.parse(buf) as EventoChat)
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError(e instanceof Error && e.name === 'AbortError' ? 'A zera.ai demorou demais para responder.' : 'Não foi possível falar com a zera.ai agora.')
  } finally { clearTimeout(t) }
}
