/* Experiência zera.ai — o front reage ao `response_type` do contrato (spec §12–§13), nunca ao texto livre.
   SUMMARY → entrada / acordo · QUESTION → gasto, renda, débito automático · STATUS → progresso · OPTION_DETAIL → resultado
   OPTIONS_COMPARISON → cards · TEXT → explicação, resposta, sem opção, escalonamento · TERMS_REVIEW → termos
   CONFIRMATION_REQUEST → CTA explícito · SUCCESS → resultado + próximos passos · ERROR → recuperação
   Todo número vem do motor determinístico; o LLM só aparece em TEXT (marcado com `llm`). */

import { ArrowUp, Calendar, CalendarDays, Check, ChevronLeft, ChevronRight, CircleDollarSign, History, Info, Landmark, Layers, Lightbulb, ListChecks, Lock, MessageCircleQuestion, Mic, Percent, ShieldCheck, UserRound, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Faisca, dataLonga } from '../components/ui'
import type { Acao, DividaIncluida, Opcao, QuickReply, Resposta, SituacaoHoje, Termos } from '../types'

const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })
const brl2 = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const pctBR = (v: number) => `${v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 2 })}%`
const acaoLabel = (d: { acao: string; entrada?: number }) => d.acao === 'quitar' ? 'Quitar com a entrada' : d.acao === 'manter' ? 'Mantida como está'
  : `${d.entrada && d.entrada > 0 ? `Abater ${brl(d.entrada)} e renegociar` : 'Renegociar'} em ${d.acao.replace('renegociar_', '')}`
type OnAcao = (a: Acao, p?: Record<string, unknown>) => void

/* ---------- peças ---------- */
function Logo({ inst }: { inst: string }) {
  const outro = /outra|open finance|nubank/i.test(inst)
  return <span className={`h-7 w-7 shrink-0 rounded-md grid place-items-center text-[9px] font-black ${outro ? 'bg-[#8A05BE] text-white' : 'bg-itau-blue text-white'}`} title={inst}>{outro ? 'OF' : 'itaú'}</span>
}
const Titulo = ({ children }: { children: React.ReactNode }) => <h1 className="text-[26px] leading-[1.15] font-extrabold tracking-tight text-ink">{children}</h1>
const Sub = ({ children }: { children: React.ReactNode }) => <p className="mt-2 text-[15px] leading-snug text-ink-soft">{children}</p>
const Topo = () => <Faisca className="h-7 w-7 mb-3" />
const Cta = ({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) => (
  <button disabled={disabled} onClick={onClick} className="btn-primary w-full py-4 text-[15px] justify-between px-6 rounded-full">{children}<ChevronRight className="h-5 w-5" /></button>
)
const Linha = ({ icon, k, v }: { icon: React.ReactNode; k: string; v: string }) => (
  <div className="flex items-center justify-between py-2.5 text-[14px] border-b border-line/70 last:border-0"><span className="flex items-center gap-2 text-ink-soft">{icon}{k}</span><span className="font-semibold text-right">{v}</span></div>
)
const Aviso = ({ children, tom = 'blue' }: { children: React.ReactNode; tom?: 'blue' | 'orange' | 'ok' }) => (
  <div className={`mt-2 flex items-start gap-2 rounded-2xl p-3 text-[13px] text-ink-soft ${tom === 'orange' ? 'bg-itau-orange-soft' : tom === 'ok' ? 'bg-ok-soft/70' : 'bg-itau-blue-soft/60'}`}><Info className="h-4 w-4 shrink-0 mt-0.5" /> <span>{children}</span></div>
)
function Fonte({ f }: { f?: string }) {
  if (!f || f === 'cadastro') return null
  return <span className="chip bg-mist text-ink-soft ml-1">{f === 'derivada_extrato' ? 'estimado do extrato' : f === 'open_finance_simulado' ? 'Open Finance (simulado)' : f}</span>
}
function Dividas({ lista, campo = 'saldo' }: { lista: Array<{ nome: string; instituicao: string; saldo: number; pagamento_mensal?: number; fonte?: string; taxa_mensal_pct?: number; acao?: string; entrada?: number }>; campo?: 'saldo' | 'pagamento_mensal' }) {
  return <div className="mt-2 space-y-2">{lista.map((d) => (
    <div key={d.nome + d.instituicao} className="flex items-center justify-between text-[14px] gap-2">
      <span className="flex items-center gap-2 min-w-0"><Logo inst={d.instituicao} /><span className="truncate">{d.nome}</span>{d.taxa_mensal_pct != null && <span className="text-[11px] text-ink-soft shrink-0">{pctBR(d.taxa_mensal_pct)} a.m.</span>}<Fonte f={d.fonte} /></span>
      <span className="font-semibold shrink-0">{brl(campo === 'saldo' ? d.saldo : (d.pagamento_mensal ?? 0))}</span>
    </div>
  ))}</div>
}
function Orbe({ titulo, steps, feitos }: { titulo: string; steps: string[]; feitos: number }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-2">
      <div className="relative h-44 w-44 mb-8"><div className="absolute inset-0 rounded-full bg-gradient-to-br from-[#FFD7B5] via-[#FF9A4D] to-[#EC7000] blur-[2px] opacity-90 animate-pulse" /><div className="absolute inset-6 rounded-full bg-gradient-to-tl from-white/70 to-transparent" /></div>
      <h2 className="text-[24px] leading-tight font-extrabold">{titulo}</h2>
      <div className="mt-6 w-full space-y-3 text-left">{steps.map((s, i) => (
        <div key={s} className="flex items-center gap-3 text-[15px]">{i < feitos ? <span className="h-6 w-6 rounded-full bg-itau-orange text-white grid place-items-center"><Check className="h-4 w-4" /></span> : <span className="h-6 w-6 rounded-full border-2 border-dashed border-itau-orange animate-spin" />}<span className={i < feitos ? '' : 'text-ink-soft'}>{s}</span></div>
      ))}</div>
    </div>
  )
}

/** Hoje × nova opção — comparação honesta: hoje não tem "total": tem saldo devedor e juros que correm, sem prazo. */
function Comparativo({ hoje, opcao }: { hoje: SituacaoHoje; opcao: Opcao }) {
  const linhas: Array<[string, string, string]> = [
    ['Pagamentos', String(hoje.qtd_pagamentos), String(opcao.payments_count)],
    ['Prazo', hoje.prazo_indefinido ? 'sem prazo definido' : `${hoje.prazo_meses} meses`, `${opcao.term_months} meses`],
    ['Taxa', `até ${pctBR(hoje.taxa_maxima_pct)} a.m.`, `${pctBR(opcao.rate_monthly_pct)} a.m.`],
    ['Juros', `${brl(hoje.juros_mensais)} por mês`, `${brl(opcao.interest_total)} no total`],
    ['Saldo devedor', brl(hoje.saldo_devedor), opcao.down_payment > 0 ? `${brl(opcao.consolidated_balance)} após entrada` : brl(opcao.principal)],
    ['Total a pagar', `${brl(hoje.saldo_devedor)} + juros`, brl(opcao.total_cost)],
  ]
  return (
    <div className="card overflow-hidden text-[13px]">
      <div className="grid grid-cols-[0.9fr_1fr_1fr] bg-mist/60"><div className="p-3" /><div className="p-3 text-ink-soft">Hoje<div className="text-[20px] font-extrabold text-ink">{brl(hoje.pagamento_mensal)}</div><div className="text-[11px]">por mês</div></div><div className="p-3 bg-itau-orange-soft text-itau-orange">Nova opção<div className="text-[20px] font-extrabold">{brl(opcao.monthly_payment)}</div><div className="text-[11px]">por mês</div></div></div>
      {linhas.map(([k, a, b]) => (
        <div key={k} className="grid grid-cols-[0.9fr_1fr_1fr] border-t border-line/70"><div className="p-3 text-ink-soft">{k}</div><div className="p-3">{a}</div><div className="p-3 bg-itau-orange-soft/40 font-semibold">{b}</div></div>
      ))}
    </div>
  )
}

/** Respostas rápidas do contrato: ação com payload, texto (vira ASK_QUESTION) ou entrada de valor. */
function QuickReplies({ itens, onAcao, onTexto }: { itens: QuickReply[]; onAcao: OnAcao; onTexto: (t: string) => void }) {
  const [aberto, setAberto] = useState<string | null>(null)
  const [valor, setValor] = useState('')
  if (!itens?.length) return null
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-2">{itens.map((q) => (
        <button key={q.id} onClick={() => q.input ? setAberto(aberto === q.id ? null : q.id) : q.acao ? onAcao(q.acao, q.payload) : onTexto(q.text ?? q.label)}
          className={`chip border text-[13px] py-2 px-3 ${aberto === q.id ? 'border-itau-orange bg-itau-orange-soft text-itau-orange' : 'border-line bg-white text-ink'}`}>{q.label}</button>
      ))}</div>
      {itens.filter((q) => q.input && aberto === q.id).map((q) => (
        <form key={q.id} className="flex gap-2 rise" onSubmit={(e) => { e.preventDefault(); const v = Number(valor.replace(/\./g, '').replace(',', '.')); if (v > 0) { onAcao(q.acao ?? 'ADJUST', { ...(q.payload ?? {}), [q.input!.campo]: v }); setValor(''); setAberto(null) } }}>
          <input autoFocus inputMode="decimal" value={valor} onChange={(e) => setValor(e.target.value)} placeholder={q.input!.placeholder ?? 'Valor (R$)'} className="flex-1 rounded-full border border-line bg-white px-4 py-3 outline-none focus:border-itau-orange" />
          <button type="submit" className="btn-primary px-5">Aplicar</button>
        </form>
      ))}
    </div>
  )
}

/* ---------- telas por response_type ---------- */
function Summary({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const s = r.summary!
  const t = r.final_terms
  if (r.agreement) {   // design: "Sua nova opção" — acompanhamento do acordo
    const a = r.agreement
    return (
      <>
        <Topo /><Titulo>{r.content.title}</Titulo><Sub>Suas dívidas foram reunidas em uma única parcela.</Sub>
        <div className="mt-5 rounded-3xl bg-ok-soft/60 p-4">
          <div className="flex items-center justify-between"><span className="chip bg-ok-soft text-ok">{r.autopay ? 'Com débito automático' : 'Pagamento manual'}</span><span className="text-[22px] font-extrabold">{brl(a.parcela)}<span className="text-xs font-medium text-ink-soft">/mês</span></span></div>
          <div className="text-[13px] text-ink-soft mt-1">{a.prazo} meses · {t ? `${brl(t.total_a_pagar)} no total` : `${a.pagas} de ${a.prazo} pagas`}</div>
          {t?.reducao_mensal ? <div className="mt-2 chip bg-white text-ok"><Check className="h-3 w-3" /> {brl(t.reducao_mensal)} a mais no seu bolso</div> : null}
        </div>
        <div className="card mt-3 p-4">
          <Linha icon={<CircleDollarSign className="h-4 w-4" />} k="Parcela mensal" v={brl(a.parcela)} />
          <Linha icon={<Calendar className="h-4 w-4" />} k="Prazo" v={`${a.prazo} meses · ${a.pagas} pagas`} />
          {t && <Linha icon={<Layers className="h-4 w-4" />} k="Total a pagar" v={brl(t.total_a_pagar)} />}
          {t && <Linha icon={<Percent className="h-4 w-4" />} k="Custo efetivo total (CET)" v={`${pctBR(t.cet_mensal_pct)} ao mês`} />}
          <Linha icon={<CalendarDays className="h-4 w-4" />} k="Próximo vencimento" v={dataLonga(a.proximo_vencimento)} />
          <Linha icon={<Landmark className="h-4 w-4" />} k="Saldo devedor do acordo" v={brl(a.saldo_devedor)} />
        </div>
        {r.autopay && <div className="mt-3 flex items-start gap-3 rounded-2xl bg-itau-blue-soft/60 p-3 text-[13px] text-ink-soft"><ShieldCheck className="h-5 w-5 shrink-0 text-itau-blue" /> O débito automático está ativo. Você pode cancelar quando quiser.</div>}
        {r.allowed_actions.includes('CANCEL_AUTOPAY') && <button onClick={() => onAcao('CANCEL_AUTOPAY')} className="card w-full mt-3 p-4 flex items-center justify-between text-[15px] font-semibold">Cancelar débito automático <ChevronRight className="h-5 w-5 text-ink-soft" /></button>}
        <div className="mt-4"><Cta onClick={() => onAcao('HOME')}>Voltar para o início</Cta></div>
      </>
    )
  }
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="card mt-5 p-4">
        <div className="flex items-baseline justify-between"><div className="text-[13px] font-semibold">Seus pagamentos hoje</div><div className="text-[12px] text-ink-soft">{brl(s.juros_mensais)}/mês só de juros</div></div>
        <div className="text-[28px] font-extrabold leading-tight">{brl(s.pagamento_mensal)}<span className="text-sm font-medium text-ink-soft">/mês</span></div>
        <div className="text-[12px] text-ink-soft">saldo devedor {brl(s.saldo_devedor)}{s.prazo_indefinido ? ' · sem prazo para terminar' : ''}</div>
        <Dividas lista={s.dividas} campo="pagamento_mensal" />
      </div>
      <div className="mt-2 text-[11px] text-ink-soft">{r.context?.persona ? 'Fixture de teste (não é dado da aplicação).' : `Dados reais da base do evento (fonte: ${r.context?.fonte ?? '—'}); dívidas marcadas “estimado do extrato” vêm de regras explícitas.`}</div>
      {r.allowed_actions.includes('START') && <div className="mt-5"><Cta onClick={() => onAcao('START')}>{r.cta}</Cta></div>}
    </>
  )
}

function Question({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const [valor, setValor] = useState('')
  const [escolha, setEscolha] = useState<string | null>(r.question === 'renda' ? 'YES' : null)
  const [incluido, setIncluido] = useState<number | null>(null)
  const num = () => Number(valor.replace(/\./g, '').replace(',', '.'))
  if (r.benefit?.benefit_type === 'AUTOPAY_DISCOUNT') {
    const b = r.benefit
    const sel = (id: string) => escolha === id || (escolha === null && id === 'AUTOPAY_YES')
    return (
      <>
        <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
        <div className="mt-5 rounded-3xl bg-gradient-to-br from-[#FFE3C9] to-[#FFB877] p-5 flex items-center justify-between"><div><div className="text-[30px] font-extrabold leading-none">{brl2(b.monthly_discount ?? 0)}</div><div className="text-[15px] font-semibold mt-1">a menos por mês</div><div className="text-[13px] text-ink-soft mt-1">Mais tranquilidade e menos custo.</div></div><CalendarDays className="h-14 w-14 text-itau-orange/80" /></div>
        <div className="mt-4 space-y-3">{r.quick_replies.map((q) => (
          <button key={q.id} onClick={() => setEscolha(q.id)} className={`w-full text-left rounded-2xl border p-4 transition ${sel(q.id) ? 'border-itau-orange bg-itau-orange-soft/50' : 'border-line bg-white'}`}>
            <div className="flex items-start gap-3"><span className={`mt-1 h-5 w-5 rounded-full border-2 grid place-items-center ${sel(q.id) ? 'border-itau-orange' : 'border-line'}`}>{sel(q.id) && <span className="h-2.5 w-2.5 rounded-full bg-itau-orange" />}</span>
              <div><div className="font-bold text-[15px]">{q.label}</div>{q.hint && <div className="text-[13px] text-ink-soft mt-0.5">{q.id === 'AUTOPAY_YES' ? <span className="chip bg-ok-soft text-ok">{q.hint}</span> : q.hint}</div>}
                {q.id === 'AUTOPAY_YES' && <ul className="mt-2 text-[13px] text-ink-soft space-y-1"><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Suas parcelas são pagas automaticamente</li><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Você não precisa se preocupar com o vencimento</li><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Pode cancelar quando quiser</li></ul>}</div></div>
          </button>))}</div>
        <Aviso>O desconto é válido enquanto o débito automático estiver ativo.</Aviso>
        <div className="mt-4"><Cta onClick={() => onAcao('SET_AUTOPAY', { id: escolha ?? 'AUTOPAY_YES' })}>{(escolha ?? 'AUTOPAY_YES') === 'AUTOPAY_YES' ? 'Continuar com débito automático' : 'Continuar sem débito automático'}</Cta></div>
      </>
    )
  }
  const renda = r.question === 'renda'
  if (escolha === 'YES') {   // design: "Vamos considerar esse gasto." — valor mensal + Incluir gasto + Buscar minhas opções
    const q = r.quick_replies.find((x) => x.id === 'YES')
    return (
      <>
        <Topo /><Titulo>{renda ? 'Quanto entra por mês, mais ou menos?' : 'Vamos considerar esse gasto.'}</Titulo>
        <Sub>{renda ? r.content.description : 'Informe quanto você paga por mês. Assim você mantém esse compromisso em vista ao comparar as opções.'}</Sub>
        <label className="mt-5 block text-[13px] font-semibold">{q?.input?.placeholder ?? 'Valor mensal (R$)'}</label>
        <form className="mt-2 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (num() > 0) setIncluido(num()) }}>
          <input autoFocus inputMode="decimal" value={valor} onChange={(e) => { setValor(e.target.value); setIncluido(null) }} placeholder="0,00" className="w-full rounded-2xl border border-line bg-white px-4 py-4 text-[17px] outline-none focus:border-itau-orange" />
          <button type="submit" disabled={!(num() > 0)} className="btn-primary w-full py-4 rounded-full">{renda ? 'Usar esta renda' : 'Incluir gasto'}</button>
        </form>
        {incluido != null && <Aviso tom="orange">{renda ? `Renda considerada: ${brl2(incluido)} por mês.` : `Gasto incluído: ${brl2(incluido)} por mês. Ele entra no cálculo do que cabe no seu bolso.`}</Aviso>}
        <div className="mt-4"><Cta disabled={incluido == null} onClick={() => onAcao('ANSWER', { id: 'YES', valor_mensal: incluido, descricao: renda ? 'renda informada' : 'gasto informado' })}>Buscar minhas opções</Cta></div>
        {!renda && <button onClick={() => setEscolha(null)} className="w-full mt-2 py-2 text-itau-orange font-bold">Voltar</button>}
      </>
    )
  }
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5 space-y-3">{r.quick_replies.map((q) => (
        <button key={q.id} onClick={() => (q.input ? setEscolha(q.id) : onAcao('ANSWER', { id: q.id }))} className="w-full text-left rounded-2xl border border-line bg-white p-4 flex items-center justify-between transition active:bg-itau-orange-soft/40">
          <div><div className="font-bold text-[16px]">{q.label}</div>{q.hint && <div className="text-[13px] text-ink-soft mt-0.5">{q.hint}</div>}</div><ChevronRight className="h-5 w-5 text-itau-orange" />
        </button>))}</div>
      {r.compromissos && r.compromissos.length > 0 && <Aviso>Já considerado: {r.compromissos.map((c) => `${c.descricao} ${brl2(c.valor_mensal)}/mês`).join(' · ')}</Aviso>}
    </>
  )
}

function Detail({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const o = r.option!; const h = r.current!
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5"><Comparativo hoje={h} opcao={o} /></div>
      {r.benefit?.benefit_type === 'LOWER_MONTHLY_PAYMENT' && <div className="mt-3 flex items-center gap-2 rounded-2xl bg-itau-orange-soft p-3 text-[14px] font-semibold text-itau-orange"><CircleDollarSign className="h-5 w-5" /> {brl(r.benefit.monthly_difference ?? 0)} a mais livres por mês</div>}
      {o.claims.filter((c) => !/a menos por mês/.test(c)).slice(0, 2).map((c) => <div key={c} className="mt-2 chip bg-ok-soft text-ok"><Check className="h-3 w-3" /> {c}</div>)}
      {r.tradeoffs?.slice(0, 1).map((t) => <Aviso key={t}>{t}</Aviso>)}
      <div className="mt-2 rounded-2xl bg-white border border-line p-3 text-[12px] text-ink-soft"><span className="font-semibold text-ink">Como fica para os dois:</span> saldo devedor de {brl(o.principal)} entra integral (sem desconto){o.down_payment > 0 ? `, ${brl(o.down_payment)} de entrada` : ''} + {brl(o.interest_total)} de juros a {pctBR(o.rate_monthly_pct)} a.m. em {o.term_months} meses = {brl(o.total_cost)}. Sua parcela cai de {brl(h.pagamento_mensal)} para {brl(o.monthly_payment)}.</div>
      <div className="mt-3 space-y-2">
        <button onClick={() => onAcao('VIEW_OPTIONS')} className="card w-full p-4 flex items-center justify-between text-[15px] font-semibold"><span className="flex items-center gap-3"><ListChecks className="h-5 w-5 text-ink-soft" /> Ver outras opções</span><ChevronRight className="h-5 w-5 text-ink-soft" /></button>
        <button onClick={() => onAcao('ASK_WHY', { option_id: o.id })} className="card w-full p-4 flex items-center justify-between text-[15px] font-semibold"><span className="flex items-center gap-3"><MessageCircleQuestion className="h-5 w-5 text-ink-soft" /> Por que essa opção?</span><ChevronRight className="h-5 w-5 text-ink-soft" /></button>
      </div>
      <div className="mt-4"><Cta onClick={() => onAcao('SELECT_OPTION', { option_id: o.id })}>{r.cta ?? 'Continuar com esta opção'}</Cta></div>
    </>
  )
}

function Comparison({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const destaque = r.options.filter((o) => o.highlight)
  const outras = r.options.filter((o) => !o.highlight)
  const ctx = r.context
  const Cartao = ({ o, compacto = false }: { o: Opcao; compacto?: boolean }) => (
    <button onClick={() => onAcao('SELECT_OPTION', { option_id: o.id })} className={`text-left rounded-3xl border p-4 transition active:scale-[0.99] ${compacto ? 'w-full flex items-center justify-between bg-white border-line' : `snap-start shrink-0 w-[260px] ${o.recommended ? 'border-itau-orange bg-itau-orange-soft/40' : 'border-line bg-white'}`}`}>
      {compacto ? (<><span><span className="font-semibold">{o.label}</span><span className="text-[13px] text-ink-soft"> · {brl(o.total_cost)} no total</span></span><span className="font-extrabold">{brl(o.monthly_payment)}<span className="text-xs font-medium text-ink-soft">/mês</span></span></>) : (<>
        <div className="flex items-center justify-between gap-2"><span className={`chip ${o.recommended ? 'bg-itau-orange-soft text-itau-orange' : 'bg-mist text-ink-soft'}`}>{o.label}</span>{o.recommended && <span className="chip bg-itau-orange text-white">Recomendada</span>}</div>
        <div className="mt-2 flex items-baseline gap-1"><span className="text-[28px] font-extrabold">{brl(o.monthly_payment)}</span><span className="text-sm text-ink-soft">/mês</span><ChevronRight className="h-5 w-5 ml-auto text-ink-soft" /></div>
        <div className="text-[13px] text-ink-soft min-h-[2.5rem]">{o.description}</div>
        <div className="mt-3 space-y-1 text-[13px] text-ink-soft"><div className="flex items-center gap-1"><Calendar className="h-4 w-4" /> {o.term_months} meses</div><div className="flex items-center gap-1"><Layers className="h-4 w-4" /> {brl(o.total_cost)} no total</div>{o.down_payment > 0 && <div className="flex items-center gap-1"><CircleDollarSign className="h-4 w-4" /> entrada {brl(o.down_payment)}</div>}</div>
      </>)}
    </button>
  )
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5 -mx-5 px-5 flex gap-3 overflow-x-auto snap-x snap-mandatory no-scrollbar pb-1">{destaque.map((o) => <Cartao key={o.id} o={o} />)}</div>
      {outras.length > 0 && <div className="mt-3 space-y-2"><div className="text-[12px] text-ink-soft">Outros prazos que cabem</div>{outras.map((o) => <Cartao key={o.id} o={o} compacto />)}</div>}
      {r.quick_replies.length > 0 && <div className="mt-3 rounded-2xl bg-white border border-line p-3 text-[13px] text-ink-soft flex items-start gap-2"><Lightbulb className="h-4 w-4 shrink-0 mt-0.5 text-itau-orange" /><span className="flex-1">{r.quick_replies[0].label}</span></div>}
      <QuickReplies itens={r.quick_replies.map((q) => ({ ...q, label: 'Ajustar o valor considerado' }))} onAcao={onAcao} onTexto={(t) => onAcao('ASK_QUESTION', { text: t })} />
      {ctx && (ctx.compromissos.length > 0 || ctx.valor_extra > 0) && <Aviso>{ctx.compromissos.length > 0 && `Gasto mensal considerado: ${brl2(ctx.compromissos.reduce((s, c) => s + c.valor_mensal, 0))}. `}{ctx.valor_extra > 0 && `Dinheiro extra considerado: ${brl2(ctx.valor_extra)}. `}Valores calculados pelo motor sobre o seu extrato.</Aviso>}
    </>
  )
}

function Texto({ r, onAcao, onTexto }: { r: Resposta; onAcao: OnAcao; onTexto: (t: string) => void }) {
  const d = r.diagnosis
  return (
    <>
      {r.guardrail && <div className="mb-3 flex items-center gap-2 rounded-xl bg-itau-blue-soft px-3 py-2 text-xs text-itau-blue"><ShieldCheck className="h-4 w-4" /> Guardrail de {r.guardrail.camada}: <b>{r.guardrail.tipo.replace(/_/g, ' ')}</b>{r.guardrail.camada === 'entrada' && ' · modelo não foi chamado'}</div>}
      {r.content.title && <><Topo /><Titulo>{r.content.title}</Titulo></>}
      <div className="mt-3 rounded-3xl bg-white border border-line p-4 text-[15px] leading-relaxed">{r.content.description}{r.llm && <span className="block mt-2 text-[11px] text-ink-soft">resposta do agente (Gemini) validada pelos guardrails — números conferidos com o motor</span>}</div>
      {r.criteria && <ul className="mt-3 space-y-2">{r.criteria.map((c) => <li key={c} className="flex gap-2 text-[14px]"><Check className="h-4 w-4 mt-0.5 text-ok shrink-0" /> {c}</li>)}</ul>}
      {r.tradeoffs?.map((t) => <Aviso key={t}>{t}</Aviso>)}
      {d && d.parcela_minima_possivel != null && (
        <div className="card mt-3 p-4 text-[13px]">
          <div className="font-semibold mb-1">Por que não coube</div>
          <Linha icon={<CircleDollarSign className="h-4 w-4" />} k={`Menor parcela possível (${d.prazo_da_parcela_minima}x)`} v={brl2(d.parcela_minima_possivel)} />
          <Linha icon={<Lock className="h-4 w-4" />} k="Parcela máxima do seu mês" v={brl2(d.parcela_maxima ?? 0)} />
          {d.meses_em_que_nao_cabe && d.meses_em_que_nao_cabe.length > 0 && <Linha icon={<Calendar className="h-4 w-4" />} k="Meses em que não caberia" v={`${d.meses_em_que_nao_cabe.length} (respiros: ${d.respiros})`} />}
        </div>
      )}
      {r.paths && <div className="mt-3 space-y-2">{r.paths.map((p) => <div key={p} className="flex gap-2 text-[13px] text-ink-soft"><ChevronRight className="h-4 w-4 mt-0.5 shrink-0 text-itau-orange" /> {p}</div>)}</div>}
      {r.escalation && <div className="mt-3 flex items-start gap-3 rounded-2xl bg-ok-soft/70 p-3 text-[13px]"><UserRound className="h-5 w-5 shrink-0 text-ok" /><div><div className="font-bold">Protocolo {r.escalation.protocolo}</div><div className="text-ink-soft">Contato {r.escalation.previsao_contato}. Nenhuma ação é executada até lá.</div></div></div>}
      <QuickReplies itens={r.quick_replies} onAcao={onAcao} onTexto={onTexto} />
      {r.option && r.allowed_actions.includes('SELECT_OPTION') && <div className="mt-4"><Cta onClick={() => onAcao('SELECT_OPTION', { option_id: r.option!.id })}>Continuar com “{r.option.label}”</Cta></div>}
    </>
  )
}

function TermosCard({ t, o, titulo }: { t: Termos; o?: Opcao; titulo?: string }) {
  return (
    <div className="card p-4">
      {titulo && <div className="flex items-center justify-between"><span className="chip bg-itau-orange-soft text-itau-orange">{titulo}</span><span className="text-[20px] font-extrabold">{brl2(t.parcela_mensal)}<span className="text-xs font-medium text-ink-soft"> /mês</span></span></div>}
      {o && <div className="text-[13px] text-ink-soft mt-1">{t.prazo_meses} meses · {brl(t.total_a_pagar)} no total</div>}
      <div className="mt-2">
        <Linha icon={<CircleDollarSign className="h-4 w-4" />} k="Parcela mensal" v={brl2(t.parcela_mensal)} />
        <Linha icon={<Calendar className="h-4 w-4" />} k="Prazo" v={`${t.prazo_meses} meses`} />
        {t.entrada > 0 && <Linha icon={<Landmark className="h-4 w-4" />} k="Entrada (dinheiro extra)" v={brl2(t.entrada)} />}
        <Linha icon={<Layers className="h-4 w-4" />} k="Saldo devedor incluído" v={brl2(t.saldo_original)} />
        <Linha icon={<Percent className="h-4 w-4" />} k="Juros do acordo" v={`${brl2(t.juros_acordo)} (${pctBR(t.taxa_mensal_pct)} a.m.)`} />
        <Linha icon={<Layers className="h-4 w-4" />} k="Total a pagar" v={brl2(t.total_a_pagar)} />
        <Linha icon={<Percent className="h-4 w-4" />} k="Custo efetivo total (CET)" v={`${pctBR(t.cet_mensal_pct)} a.m. · ${pctBR(t.cet_anual_pct)} a.a.`} />
        <Linha icon={<CalendarDays className="h-4 w-4" />} k="Primeiro vencimento" v={dataLonga(t.primeiro_vencimento)} />
        <Linha icon={<CalendarDays className="h-4 w-4" />} k="Último vencimento" v={dataLonga(t.ultimo_vencimento)} />
      </div>
    </div>
  )
}
function DividasIncluidas({ lista }: { lista: DividaIncluida[] }) {
  return (
    <div className="card mt-3 p-4"><div className="text-[13px] font-semibold">Dívidas incluídas</div>
      <div className="mt-2 space-y-2">{lista.map((d) => (
        <div key={d.divida_id} className="text-[13px]"><div className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 min-w-0"><Logo inst={d.instituicao} /><span className="truncate">{d.nome}</span><Fonte f={d.fonte} /></span><span className="font-semibold shrink-0">{brl(d.saldo)}</span></div>
          <div className="text-[12px] text-ink-soft ml-9">{acaoLabel(d)}{d.parcela > 0 ? ` · ${brl2(d.parcela)}/mês` : ''} · hoje {pctBR(d.taxa_hoje_pct)} a.m.</div></div>
      ))}</div></div>
  )
}
function Terms({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const t = r.terms!; const o = r.option!
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5"><TermosCard t={t} o={o} titulo={o.label} /></div>
      <DividasIncluidas lista={t.dividas_incluidas} />
      {r.tradeoffs?.slice(0, 1).map((x) => <Aviso key={x}>{x}</Aviso>)}
      <div className="mt-3 flex items-start gap-3 rounded-2xl bg-white border border-line p-3"><Lock className="h-5 w-5 text-ink-soft shrink-0" /><div><div className="font-bold text-[14px]">Você sempre decide</div><div className="text-[13px] text-ink-soft">{r.notice}</div></div></div>
      <div className="mt-4"><Cta onClick={() => onAcao('CONTINUE')}>{r.cta ?? 'Continuar'}</Cta></div>
      <button onClick={() => onAcao('VIEW_OPTIONS')} className="w-full mt-2 py-2 text-itau-orange font-bold">Voltar às opções</button>
    </>
  )
}
function Confirmation({ r, onAcao }: { r: Resposta; onAcao: OnAcao }) {
  const t = r.final_terms!
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5 rounded-3xl bg-ok-soft/70 p-4">
        <div className="flex items-center justify-between"><span className="chip bg-white text-ok">{t.debito_automatico ? 'Com débito automático' : 'Pagamento manual'}</span><span className="text-[22px] font-extrabold">{brl2(t.parcela_mensal)}<span className="text-xs font-medium text-ink-soft"> /mês</span></span></div>
        <div className="text-[13px] text-ink-soft mt-1">{t.prazo_meses} meses · {brl(t.total_a_pagar)} no total</div>
        {r.claims?.[0] && <div className="mt-2 chip bg-white text-ok"><Check className="h-3 w-3" /> {r.claims[0]}</div>}
      </div>
      <div className="mt-3"><TermosCard t={t} /></div>
      {r.account && <div className="card mt-3 p-4"><div className="text-[13px] font-semibold">Conta para débito automático</div><div className="mt-2 flex items-center justify-between text-[14px]"><span className="flex items-center gap-2"><Landmark className="h-5 w-5 text-itau-orange" /> Conta {r.account.banco}</span><span className="text-ink-soft">Ag {r.account.agencia} · CC {r.account.conta}</span></div></div>}
      <DividasIncluidas lista={t.dividas_incluidas} />
      <Aviso>{r.notice}</Aviso>
      <div className="mt-4"><Cta onClick={() => onAcao('CONFIRM', { frase: r.cta })}>{r.cta}</Cta></div>
      <button onClick={() => onAcao('CANCEL')} className="w-full mt-2 py-2 text-itau-orange font-bold">Revisar</button>
      <div className="mt-1 text-center text-[11px] text-ink-soft">Só o botão acima autoriza a contratação. Ver, selecionar, perguntar ou digitar “sim” não contrata nada.</div>
    </>
  )
}
function Success({ r, onAcao, onSair }: { r: Resposta; onAcao: OnAcao; onSair: () => void }) {
  const t = r.final_terms!; const res = r.result!
  return (
    <>
      <div className="relative h-32 w-32 mx-auto mb-2"><div className="absolute inset-0 rounded-full bg-gradient-to-br from-[#FFD7B5] to-[#FF9A4D] opacity-80" /><div className="absolute inset-8 rounded-full bg-itau-orange grid place-items-center text-white"><Check className="h-8 w-8" /></div></div>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="card mt-5 p-4"><div className="flex items-center gap-3"><span className="h-10 w-10 rounded-xl bg-itau-orange-soft text-itau-orange grid place-items-center"><CircleDollarSign className="h-5 w-5" /></span><div><div className="text-[13px] text-ink-soft">Sua nova parcela</div><div className="text-[24px] font-extrabold leading-tight">{brl2(res.new_monthly_payment)}<span className="text-sm font-medium text-ink-soft">/mês</span></div></div></div><div className="mt-2 text-[13px] text-ink-soft">Primeiro vencimento em {dataLonga(t.primeiro_vencimento)} · termina em {dataLonga(t.ultimo_vencimento)}</div>
        {res.monthly_reduction > 0 && <div className="mt-3 rounded-2xl bg-ok-soft p-3 text-[13px]"><div className="font-bold text-ok flex items-center gap-1"><Check className="h-4 w-4" /> {brl(res.monthly_reduction)} a mais no seu bolso todo mês</div><div className="text-ink-soft">Em comparação com seus pagamentos anteriores.</div></div>}
      </div>
      <div className="mt-4 text-[15px] font-bold">O que acontece agora?</div>
      <div className="mt-2 space-y-2">{r.next_steps?.map((s) => <div key={s} className="card p-3 text-[13px] flex gap-3"><Check className="h-4 w-4 text-ok shrink-0 mt-0.5" /> {s}</div>)}</div>
      <div className="mt-4"><Cta onClick={() => onAcao('FOLLOW')}>{r.cta ?? 'Acompanhar'}</Cta></div>
      <button onClick={onSair} className="w-full mt-2 py-2 text-itau-orange font-bold">Voltar para o início</button>
    </>
  )
}
function Erro({ r, onAcao, onSair }: { r: Resposta; onAcao: OnAcao; onSair: () => void }) {
  return (
    <>
      <Topo /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      {r.error && <div className="mt-3 rounded-2xl bg-mist p-3 text-[11px] text-ink-soft break-words">detalhe técnico: {r.error}</div>}
      <QuickReplies itens={r.quick_replies} onAcao={onAcao} onTexto={(t) => onAcao('ASK_QUESTION', { text: t })} />
      <button onClick={onSair} className="w-full mt-3 py-2 text-itau-orange font-bold">Voltar para o início</button>
    </>
  )
}

/* ---------- shell ---------- */
type Bolha = { de: 'cliente' | 'zera'; texto: string }

export function Experiencia({ onSair, inicial, onConversar }: { onSair: () => void; inicial?: Resposta; onConversar?: () => void }) {
  const [resp, setResp] = useState<Resposta | null>(inicial ?? null)
  const [carregando, setCarregando] = useState(false)
  const [status, setStatus] = useState<{ title: string; steps: string[]; feitos: number } | null>(null)
  const [texto, setTexto] = useState('')
  const [conversa, setConversa] = useState<Bolha[]>([])
  const topo = useRef<HTMLDivElement>(null)

  useEffect(() => { if (!inicial) api.experiencia().then(setResp) }, [inicial])
  useEffect(() => { topo.current?.scrollTo({ top: 0 }) }, [resp?.response_type, resp?.state])

  async function acao(a: Acao, payload: Record<string, unknown> = {}) {
    if (carregando) return
    setCarregando(true)
    try {
      if (a === 'ASK_QUESTION' && typeof payload.text === 'string') setConversa((c) => [...c, { de: 'cliente', texto: payload.text as string }])
      const r = await api.evento(a, payload)
      if (r.status) {  // STATUS: mostra o progresso antes do resultado (spec §13)
        const steps = r.status.steps
        for (let i = 0; i <= steps.length; i++) { setStatus({ title: r.status.title, steps, feitos: i }); await new Promise((res) => setTimeout(res, i === steps.length ? 350 : 650)) }
        setStatus(null)
      }
      if (a === 'ASK_QUESTION') setConversa((c) => [...c, { de: 'zera' as const, texto: r.response_type === 'TEXT' ? r.content.description : `${r.content.title || 'Pronto'} — veja acima.` }].slice(-6))
      else setConversa([])
      if (a === 'HOME' || (a === 'FOLLOW' && r.response_type !== 'SUMMARY')) { onSair(); return }
      setResp(r)
    } finally { setCarregando(false) }
  }

  const voltar = resp && ['REVIEWING', 'AWAITING_CONFIRMATION', 'EXPLAINING'].includes(resp.state) && resp.response_type !== 'SUCCESS'
  const esperando = carregando && !status
  const podePerguntar = !!resp && resp.response_type !== 'SUCCESS' && !status
  const finops = resp?.finops

  return (
    <div className="h-full flex flex-col bg-[#FBF6F1] relative overflow-hidden">
      <div className="pointer-events-none absolute -top-24 -right-24 h-72 w-72 rounded-full bg-[radial-gradient(circle,_rgba(255,170,90,0.45),_transparent_65%)]" />
      <div className="relative flex items-center justify-between px-4 pt-4 pb-2">
        {voltar ? <button onClick={() => acao('CANCEL')} aria-label="Voltar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-black/5"><ChevronLeft /></button>
          : <button onClick={onSair} aria-label="Fechar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-black/5"><X /></button>}
        <span className="flex items-center gap-2 text-[15px] font-semibold text-ink-soft"><History className="h-4 w-4" /> zera.ai{onConversar && <button onClick={onConversar} className="ml-2 text-[12px] font-bold text-itau-orange">Conversar</button>}</span>
      </div>
      {esperando && (
        <div className="absolute inset-x-0 top-14 z-20 flex justify-center pointer-events-none" aria-live="polite">
          <div className="flex items-center gap-2 rounded-full bg-white/90 border border-line px-3 py-1.5 text-xs text-ink-soft shadow"><span className="h-3.5 w-3.5 rounded-full border-2 border-itau-orange border-t-transparent animate-spin" /> zera.ai está pensando…</div>
        </div>
      )}
      <div ref={topo} className={`relative flex-1 overflow-y-auto px-5 pb-6 flex flex-col transition ${esperando ? 'opacity-60 pointer-events-none' : ''}`} aria-busy={carregando}>
        {status ? <Orbe titulo={status.title} steps={status.steps} feitos={status.feitos} /> : !resp ? (
          <div className="animate-pulse mt-4" aria-label="Carregando"><div className="h-6 w-6 rounded bg-itau-orange-soft" /><div className="mt-4 h-7 w-5/6 rounded bg-white" /><div className="mt-2 h-7 w-2/3 rounded bg-white" /><div className="mt-4 h-4 w-full rounded bg-white" /><div className="mt-6 h-40 w-full rounded-3xl bg-white" /></div>
        ) : (
          <div className="rise" key={resp.response_type + resp.state + (resp.content.title ?? '')}>
            {resp.response_type === 'SUMMARY' && <Summary r={resp} onAcao={acao} />}
            {resp.response_type === 'QUESTION' && <Question r={resp} onAcao={acao} />}
            {resp.response_type === 'OPTION_DETAIL' && <Detail r={resp} onAcao={acao} />}
            {resp.response_type === 'OPTIONS_COMPARISON' && <Comparison r={resp} onAcao={acao} />}
            {resp.response_type === 'TEXT' && <Texto r={resp} onAcao={acao} onTexto={(t) => acao('ASK_QUESTION', { text: t })} />}
            {resp.response_type === 'TERMS_REVIEW' && <Terms r={resp} onAcao={acao} />}
            {resp.response_type === 'CONFIRMATION_REQUEST' && <Confirmation r={resp} onAcao={acao} />}
            {resp.response_type === 'SUCCESS' && <Success r={resp} onAcao={acao} onSair={onSair} />}
            {resp.response_type === 'ERROR' && <Erro r={resp} onAcao={acao} onSair={onSair} />}
            {resp.response_type === 'PROACTIVE_MESSAGE' && <Summary r={{ ...resp, summary: resp.summary ?? { pagamento_mensal: 0, qtd_pagamentos: 0, prazo_meses: null, prazo_indefinido: true, saldo_devedor: 0, juros_mensais: 0, taxa_maxima_pct: 0, taxa_media_pct: 0, amortiza_por_mes: 0, projecoes: {}, dividas: [], maior_atraso: 0 } }} onAcao={acao} />}
            {conversa.length > 0 && resp.response_type !== 'TEXT' && (
              <div className="mt-5 space-y-2">{conversa.map((b, i) => (
                <div key={i} className={`max-w-[85%] rounded-2xl px-3 py-2 text-[13px] ${b.de === 'cliente' ? 'ml-auto bg-itau-orange-soft' : 'bg-white border border-line'}`}>{b.texto}</div>
              ))}</div>
            )}
          </div>
        )}
      </div>
      {podePerguntar && (
        <div className="relative px-4 pb-4 pt-1">
          <form className="flex items-center gap-2 rounded-full bg-white border border-line px-4 py-2 shadow-sm" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) { acao('ASK_QUESTION', { text: texto.trim() }); setTexto('') } }}>
            <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Digite aqui" className="flex-1 bg-transparent outline-none text-[15px] py-1" aria-label="Pergunte à zera.ai" />
            {texto.trim() ? <button type="submit" aria-label="Enviar" className="h-9 w-9 grid place-items-center rounded-full bg-itau-orange text-white"><ArrowUp className="h-5 w-5" /></button> : <Mic className="h-5 w-5 text-ink-soft" />}
          </form>
          <div className="mt-2 flex items-center justify-center gap-2 text-center text-[11px] text-ink-soft"><span>{resp?.disclaimer}</span>{finops && finops.chamadas > 0 && <span className="chip bg-mist text-ink-soft" title="FinOps: custo estimado desta jornada">LLM {finops.chamadas}× · {finops.tokens_entrada + finops.tokens_saida} tokens · US$ {finops.custo_usd.toFixed(4)}</span>}</div>
        </div>
      )}
    </div>
  )
}
