import { ArrowUp, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { BlocoCard, Guardrail } from '../components/cards'
import { HeaderItau } from '../components/ui'
import type { Mensagem, RespostaChat } from '../types'

/* Tela 4 — conversa com a zera.ai: bolhas + cards das tools + respostas rápidas + confirmação explícita */

const uid = () => Math.random().toString(36).slice(2, 10)

function sugerirRespostas(texto: string, temCenario: boolean): string[] {
  const t = texto.toLowerCase()
  if (/confirma\?|voc[êe] confirma|confirma que/.test(t)) return ['Sim, confirmo', 'Ainda não']
  if (/respiro/.test(t) && /quer/.test(t)) return ['Quero usar o respiro', 'Vou pagar normal']
  if (/falar com uma pessoa|protocolo/.test(t)) return ['Sim, por favor', 'Agora não']
  if (temCenario) return ['Quero o recomendado', 'Ver alternativas']
  if (/quer ver|melhor uso|op[çc][õo]es/.test(t)) return ['Sim, quero ver', 'Quanto eu devo?']
  return ['Quanto eu devo?', 'O que cabe no meu mês?']
}

export function Chat({ onVoltar, mensagemInicial, aoAtualizarEstado }: { onVoltar: () => void; mensagemInicial?: string; aoAtualizarEstado: () => void }) {
  const [msgs, setMsgs] = useState<Mensagem[]>([])
  const [texto, setTexto] = useState('')
  const [digitando, setDigitando] = useState(false)
  const [sugestoes, setSugestoes] = useState<string[]>([])
  const [confirmacao, setConfirmacao] = useState<string | null>(null)
  const fim = useRef<HTMLDivElement>(null)
  const iniciou = useRef(false)

  useEffect(() => { fim.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, digitando])

  useEffect(() => {
    if (iniciou.current) return
    iniciou.current = true
    // o agente inicia a conversa a partir do gatilho pendente (a API injeta o gatilho no prompt); "oi" só abre o turno
    enviar(mensagemInicial ?? 'oi', !mensagemInicial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function enviar(t: string, silencioso = false) {
    const conteudo = t.trim()
    if (!conteudo || digitando) return
    setTexto('')
    setSugestoes([])
    if (!silencioso) setMsgs((m) => [...m, { id: uid(), autor: 'cliente', texto: conteudo, ts: Date.now() }])
    setDigitando(true)
    try {
      const r: RespostaChat = await api.chat(conteudo)
      const bloqueio = r.estado?.bloqueios_guardrail?.at(-1)
      const blocos = (r.ui ?? []).filter((b) => ['raio_x', 'capacidade', 'cenarios', 'acordo', 'amortizacao'].includes(b.tipo))
      setMsgs((m) => [...m, { id: uid(), autor: 'zera', texto: r.texto, blocos, guardrail: bloqueio ? { camada: bloqueio.camada, tipo: bloqueio.tipo } : undefined, ts: Date.now() }])
      const temCenario = blocos.some((b) => b.tipo === 'cenarios')
      setSugestoes(sugerirRespostas(r.texto, temCenario))
      if (/confirma\?|voc[êe] confirma/.test(r.texto.toLowerCase())) setConfirmacao(r.texto)
      if (blocos.some((b) => b.tipo === 'acordo')) aoAtualizarEstado()
    } catch (e) {
      setMsgs((m) => [...m, { id: uid(), autor: 'sistema', texto: 'Não consegui falar com a zera agora. Tente de novo em instantes.', ts: Date.now() }])
    } finally {
      setDigitando(false)
    }
  }

  const escolherCenario = (id: string) => enviar(id === 'C1' ? 'Quero o recomendado' : `Quero o cenário ${id}`)

  return (
    <div className="h-full bg-mist flex flex-col">
      <HeaderItau onBack={onVoltar} titulo="zera.ai" badge={<span className="chip bg-white/20 text-white text-[10px]"><ShieldCheck className="h-3 w-3" /> guardrails</span>} />
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {msgs.map((m) => (
          <div key={m.id} className={`rise ${m.autor === 'cliente' ? 'flex justify-end' : ''}`}>
            {m.autor === 'zera' && (
              <div className="flex items-end gap-2 max-w-[92%]">
                <div className="h-7 w-7 shrink-0 rounded-full bg-itau-orange text-white text-[10px] font-black grid place-items-center">z</div>
                <div className="space-y-2 min-w-0 flex-1">
                  {m.guardrail && <Guardrail camada={m.guardrail.camada} tipo={m.guardrail.tipo} />}
                  {m.texto && <div className="rounded-2xl rounded-bl-md bg-white border border-line px-4 py-3 text-[15px] leading-snug shadow-sm whitespace-pre-line">{m.texto}</div>}
                  {m.blocos?.map((b, i) => <BlocoCard key={i} bloco={b} onEscolher={b.tipo === 'cenarios' ? escolherCenario : undefined} />)}
                </div>
              </div>
            )}
            {m.autor === 'cliente' && <div className="max-w-[80%] rounded-2xl rounded-br-md bg-itau-orange text-white px-4 py-3 text-[15px] leading-snug shadow-sm">{m.texto}</div>}
            {m.autor === 'sistema' && <div className="text-center text-xs text-ink-soft">{m.texto}</div>}
          </div>
        ))}
        {digitando && (
          <div className="flex items-end gap-2"><div className="h-7 w-7 rounded-full bg-itau-orange text-white text-[10px] font-black grid place-items-center">z</div>
            <div className="rounded-2xl rounded-bl-md bg-white border border-line px-4 py-3 flex gap-1"><span className="dot h-2 w-2 rounded-full bg-ink-soft" /><span className="dot h-2 w-2 rounded-full bg-ink-soft" /><span className="dot h-2 w-2 rounded-full bg-ink-soft" /></div></div>
        )}
        <div ref={fim} />
      </div>

      {sugestoes.length > 0 && !digitando && (
        <div className="px-3 pb-2 flex gap-2 overflow-x-auto no-scrollbar">
          {sugestoes.map((s) => <button key={s} onClick={() => enviar(s)} className="chip bg-white border border-itau-orange/40 text-itau-orange whitespace-nowrap px-4 py-2 text-sm">{s}</button>)}
        </div>
      )}

      <div className="px-3 pb-5 pt-2 bg-mist border-t border-line">
        <form className="flex items-center gap-2 rounded-full bg-white border border-line px-4 py-2 shadow-sm" onSubmit={(e) => { e.preventDefault(); enviar(texto) }}>
          <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Pergunte qualquer coisa…" className="flex-1 bg-transparent outline-none text-[15px]" aria-label="Mensagem" />
          <button type="submit" disabled={!texto.trim() || digitando} aria-label="Enviar" className="h-9 w-9 grid place-items-center rounded-full bg-itau-orange text-white disabled:opacity-40"><ArrowUp className="h-5 w-5" /></button>
        </form>
      </div>

      {confirmacao && (
        <div className="absolute inset-0 z-20 bg-black/40 flex items-end" onClick={() => setConfirmacao(null)}>
          <div className="w-full rounded-t-3xl bg-white p-5 pb-8 rise" onClick={(e) => e.stopPropagation()}>
            <div className="mx-auto h-1.5 w-12 rounded-full bg-line" />
            <div className="mt-4 flex items-center gap-2 text-itau-orange font-bold"><ShieldCheck className="h-5 w-5" /> Você decide antes de qualquer ação</div>
            <div className="mt-2 text-[15px] leading-snug">{confirmacao}</div>
            <div className="mt-3 text-xs text-ink-soft">Ao confirmar, a zera.ai registra seu consentimento com data e hora e só então executa.</div>
            <button className="btn-primary w-full mt-4 rounded-2xl py-4 text-base" onClick={() => { setConfirmacao(null); enviar('Sim, confirmo') }}>Confirmar</button>
            <button className="w-full mt-2 py-2 text-itau-orange font-bold" onClick={() => { setConfirmacao(null); enviar('Ainda não') }}>Ainda não</button>
          </div>
        </div>
      )}
    </div>
  )
}
