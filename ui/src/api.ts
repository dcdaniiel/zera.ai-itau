/* Cliente HTTP da API zera.ai (api/main.py). Sem mock: toda tela vem do backend (núcleo determinístico + agente).
   Em dev, /api é proxied pelo Vite para http://localhost:8080; em produção a própria API serve a UI (mesma origem). */

import type { Acao, EstadoDemo, Preferencias, Resposta } from './types'

const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? '/api' : '')
export const CLIENTE_ID = import.meta.env.VITE_CLIENTE_ID ?? 'cli_001'
const SESSAO_ID = `ui-${Math.random().toString(36).slice(2, 8)}`

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
    options: [], quick_replies: [], allowed_actions: ['RETRY', 'ESCALATE'], requires_confirmation: false, error: msg }
}

const base = `/v1/clientes/${CLIENTE_ID}`

export const api = {
  health: () => req<{ ok: boolean; modelo: string }>('/health', undefined, 8_000),
  preferencias: (p: Preferencias) => req<{ ok: boolean }>(`${base}/preferencias`, { method: 'POST', body: JSON.stringify(p) }),
  proativa: () => req<Resposta>(`${base}/proativa`),
  experiencia: async (): Promise<Resposta> => { try { return await req<Resposta>(`${base}/experiencia`) } catch (e) { return comoErro(e) } },
  evento: async (acao: Acao, payload: Record<string, unknown> = {}): Promise<Resposta> => {
    try { return await req<Resposta>(`${base}/experiencia/evento`, { method: 'POST', body: JSON.stringify({ acao, payload, sessao_id: SESSAO_ID }) }) }
    catch (e) { return comoErro(e) }
  },
  estado: () => req<EstadoDemo>(`/gatilhos/${CLIENTE_ID}`),
  simularTempo: (ate: string) => req<EstadoDemo>('/simular_tempo', { method: 'POST', body: JSON.stringify({ cliente_id: CLIENTE_ID, ate }) }),
  reset: () => req<unknown>(`/reset/${CLIENTE_ID}`, { method: 'POST' }),
}
