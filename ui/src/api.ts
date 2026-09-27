/* Cliente da API do Zera (api/main.py) com fallback automático para o modo demo (mock.ts).
   - VITE_MOCK=1 força o modo demo.
   - Em dev, /api é proxied pelo Vite para http://localhost:8080; em produção a UI é servida pela própria API. */

import { mock } from './mock'
import type { EstadoDemo, RespostaChat } from './types'

const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? '/api' : '')
export const CLIENTE_ID = import.meta.env.VITE_CLIENTE_ID ?? 'cli_001'
const SESSAO_ID = `ui-${Math.random().toString(36).slice(2, 8)}`

let modo: 'api' | 'mock' = import.meta.env.VITE_MOCK === '1' ? 'mock' : 'api'
const ouvintes = new Set<(m: 'api' | 'mock') => void>()
export const getModo = () => modo
export const setModo = (m: 'api' | 'mock') => { modo = m; ouvintes.forEach((f) => f(m)) }
export const onModo = (f: (m: 'api' | 'mock') => void) => { ouvintes.add(f); return () => { ouvintes.delete(f) } }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), 45_000)
  try {
    const r = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal, ...init })
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
    return (await r.json()) as T
  } finally {
    clearTimeout(t)
  }
}

/** Se a API não responder, cai para o mock e avisa (badge "demo" no header). */
async function comFallback<T>(viaApi: () => Promise<T>, viaMock: () => Promise<T>): Promise<T> {
  if (modo === 'mock') return viaMock()
  try {
    return await viaApi()
  } catch (e) {
    console.warn('[zera] API indisponível, usando modo demo:', e)
    setModo('mock')
    return viaMock()
  }
}

export const api = {
  chat: (mensagem: string) =>
    comFallback<RespostaChat>(
      () => req('/chat', { method: 'POST', body: JSON.stringify({ cliente_id: CLIENTE_ID, sessao_id: SESSAO_ID, mensagem }) }),
      () => mock.chat(mensagem),
    ),
  gatilhos: () =>
    comFallback<EstadoDemo>(() => req(`/gatilhos/${CLIENTE_ID}`), async () => mock.estado()),
  simularTempo: (ate: string) =>
    comFallback<EstadoDemo>(
      () => req('/simular_tempo', { method: 'POST', body: JSON.stringify({ cliente_id: CLIENTE_ID, ate }) }),
      () => mock.simularTempo(ate),
    ),
  reset: () =>
    comFallback<unknown>(() => req(`/reset/${CLIENTE_ID}`, { method: 'POST' }), async () => mock.reset()),
}
