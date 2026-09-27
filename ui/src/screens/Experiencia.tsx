/* Experiência zera.ai — o front reage ao `response_type` do contrato (spec §12–§13), nunca ao texto livre.
   SUMMARY → entrada · QUESTION → pergunta/quick replies (gasto extra, débito automático) · STATUS → progresso
   OPTION_DETAIL → resultado · OPTIONS_COMPARISON → cards · TEXT → explicação/resposta · TERMS_REVIEW → termos
   CONFIRMATION_REQUEST → CTA explícito · SUCCESS → resultado + próximos passos · ERROR → recuperação */

import { ArrowUp, Calendar, CalendarDays, Check, ChevronLeft, ChevronRight, CircleDollarSign, Info, Landmark, Layers, ListChecks, Lock, MessageCircleQuestion, Mic, Percent, ShieldCheck, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Acao, Opcao, Resposta, SituacaoHoje, Termos } from '../types'

const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })
const brl2 = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const dataLonga = (iso: string) => { const [y, m, d] = iso.split('-'); return `${Number(d)} de ${['jan.', 'fev.', 'mar.', 'abr.', 'mai.', 'jun.', 'jul.', 'ago.', 'set.', 'out.', 'nov.', 'dez.'][Number(m) - 1]} de ${y}` }
const acaoLabel = (a: string) => a === 'quitar' ? 'Quitar à vista' : a === 'manter' ? 'Manter como está' : `Renegociar em ${a.replace('renegociar_', '')}`

/* ---------- peças ---------- */
function Logo({ inst }: { inst: string }) {
  const outro = /outra|open finance|nubank/i.test(inst)
  return <span className={`h-7 w-7 shrink-0 rounded-md grid place-items-center text-[9px] font-black ${outro ? 'bg-[#8A05BE] text-white' : 'bg-itau-blue text-white'}`} title={inst}>{outro ? 'OF' : 'itaú'}</span>
}
const Titulo = ({ children }: { children: React.ReactNode }) => <h1 className="text-[26px] leading-[1.15] font-extrabold tracking-tight text-ink">{children}</h1>
const Sub = ({ children }: { children: React.ReactNode }) => <p className="mt-2 text-[15px] leading-snug text-ink-soft">{children}</p>
const Faisca = () => <Sparkles className="h-6 w-6 text-itau-orange mb-3" />
const Cta = ({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) => (
  <button disabled={disabled} onClick={onClick} className="btn-primary w-full py-4 text-[15px] justify-between px-6 rounded-full">{children}<ChevronRight className="h-5 w-5" /></button>
)
const Linha = ({ icon, k, v }: { icon: React.ReactNode; k: string; v: string }) => (
  <div className="flex items-center justify-between py-2.5 text-[14px] border-b border-line/70 last:border-0"><span className="flex items-center gap-2 text-ink-soft">{icon}{k}</span><span className="font-semibold">{v}</span></div>
)
function Dividas({ lista, campo = 'saldo' }: { lista: Array<{ nome: string; instituicao: string; saldo: number; pagamento_mensal?: number }>; campo?: 'saldo' | 'pagamento_mensal' }) {
  return <div className="mt-2 space-y-2">{lista.map((d) => (
    <div key={d.nome} className="flex items-center justify-between text-[14px]"><span className="flex items-center gap-2"><Logo inst={d.instituicao} />{d.nome}</span><span className="font-semibold">{brl(campo === 'saldo' ? d.saldo : (d.pagamento_mensal ?? 0))}</span></div>
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
function Comparativo({ hoje, opcao, parcela }: { hoje: SituacaoHoje; opcao: Opcao; parcela?: number }) {
  const nova = parcela ?? opcao.monthly_payment
  return (
    <div className="card overflow-hidden text-[13px]">
      <div className="grid grid-cols-[1fr_1fr_1fr] bg-mist/60"><div className="p-3" /><div className="p-3 text-ink-soft">Hoje<div className="text-[20px] font-extrabold text-ink">{brl(hoje.pagamento_mensal)}</div><div className="text-[11px]">por mês</div></div><div className="p-3 bg-itau-orange-soft text-itau-orange">Nova opção<div className="text-[20px] font-extrabold">{brl(nova)}</div><div className="text-[11px]">por mês</div></div></div>
      {[['Pagamentos', String(hoje.qtd_pagamentos), '1'], ['Prazo', `${hoje.prazo_meses} meses`, `${opcao.term_months} meses`], ['Total a pagar', brl(hoje.total_a_pagar), brl(opcao.total_cost)]].map(([k, a, b]) => (
        <div key={k} className="grid grid-cols-[1fr_1fr_1fr] border-t border-line/70"><div className="p-3 text-ink-soft">{k}</div><div className="p-3">{a}</div><div className="p-3 bg-itau-orange-soft/40 font-semibold">{b}</div></div>
      ))}
    </div>
  )
}

/* ---------- telas por response_type ---------- */
function Summary({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  const s = r.summary!
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="card mt-5 p-4">
        <div className="text-[13px] font-semibold">{r.agreement ? 'Sua parcela' : 'Seus pagamentos hoje'}</div>
        <div className="text-[28px] font-extrabold leading-tight">{brl(r.agreement ? r.agreement.parcela : s.pagamento_mensal)}<span className="text-sm font-medium text-ink-soft">/mês</span></div>
        {!r.agreement && <Dividas lista={s.dividas} campo="pagamento_mensal" />}
      </div>
      {r.allowed_actions.includes('START') && <div className="mt-5"><Cta onClick={() => onAcao('START')}>{r.cta}</Cta></div>}
    </>
  )
}
function Question({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  const [valor, setValor] = useState('')
  const [escolha, setEscolha] = useState<string | null>(null)
  const autopay = r.benefit?.benefit_type === 'AUTOPAY_DISCOUNT'
  if (autopay) {
    const b = r.benefit!
    return (
      <>
        <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
        <div className="mt-5 rounded-3xl bg-gradient-to-br from-[#FFE3C9] to-[#FFB877] p-5 flex items-center justify-between"><div><div className="text-[30px] font-extrabold leading-none">{brl(b.monthly_discount ?? 0)}</div><div className="text-[15px] font-semibold mt-1">a menos por mês</div><div className="text-[13px] text-ink-soft mt-1">Mais tranquilidade e menos custo.</div></div><CalendarDays className="h-14 w-14 text-itau-orange/80" /></div>
        <div className="mt-4 space-y-3">{r.quick_replies.map((q) => (
          <button key={q.id} onClick={() => setEscolha(q.id)} className={`w-full text-left rounded-2xl border p-4 transition ${escolha === q.id || (escolha === null && q.id === 'AUTOPAY_YES') ? 'border-itau-orange bg-itau-orange-soft/50' : 'border-line bg-white'}`}>
            <div className="flex items-start gap-3"><span className={`mt-1 h-5 w-5 rounded-full border-2 grid place-items-center ${escolha === q.id || (escolha === null && q.id === 'AUTOPAY_YES') ? 'border-itau-orange' : 'border-line'}`}>{(escolha === q.id || (escolha === null && q.id === 'AUTOPAY_YES')) && <span className="h-2.5 w-2.5 rounded-full bg-itau-orange" />}</span>
              <div><div className="font-bold text-[15px]">{q.label}</div>{q.hint && <div className="text-[13px] text-ink-soft mt-0.5">{q.id === 'AUTOPAY_YES' ? <span className="chip bg-ok-soft text-ok">{q.hint}</span> : q.hint}</div>}
                {q.id === 'AUTOPAY_YES' && <ul className="mt-2 text-[13px] text-ink-soft space-y-1"><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Suas parcelas são pagas automaticamente</li><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Você não precisa se preocupar com o vencimento</li><li className="flex gap-2"><Check className="h-4 w-4 text-ok" /> Pode cancelar quando quiser</li></ul>}</div></div>
          </button>))}</div>
        <div className="mt-3 flex items-start gap-2 rounded-2xl bg-itau-blue-soft/60 p-3 text-[12px] text-ink-soft"><Info className="h-4 w-4 shrink-0" /> O desconto é válido enquanto o débito automático estiver ativo.</div>
        <div className="mt-4"><Cta onClick={() => onAcao('SET_AUTOPAY', { id: escolha ?? 'AUTOPAY_YES' })}>{(escolha ?? 'AUTOPAY_YES') === 'AUTOPAY_YES' ? 'Continuar com débito automático' : 'Continuar sem débito automático'}</Cta></div>
      </>
    )
  }
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5 space-y-3">{r.quick_replies.map((q) => (
        <div key={q.id}>
          <button onClick={() => (q.input ? setEscolha(q.id) : onAcao('ANSWER', { id: q.id }))} className={`w-full text-left rounded-2xl border p-4 flex items-center justify-between transition ${escolha === q.id ? 'border-itau-orange bg-itau-orange-soft/50' : 'border-line bg-white'}`}>
            <div><div className="font-bold text-[16px]">{q.label}</div>{q.hint && <div className="text-[13px] text-ink-soft mt-0.5">{q.hint}</div>}</div><ChevronRight className="h-5 w-5 text-itau-orange" />
          </button>
          {q.input && escolha === q.id && (
            <form className="mt-2 flex gap-2 rise" onSubmit={(e) => { e.preventDefault(); onAcao('ANSWER', { id: 'YES', valor_mensal: Number(valor.replace(',', '.')), descricao: 'gasto informado' }) }}>
              <input autoFocus inputMode="decimal" value={valor} onChange={(e) => setValor(e.target.value)} placeholder="Valor por mês (R$)" className="flex-1 rounded-full border border-line bg-white px-4 py-3 outline-none focus:border-itau-orange" />
              <button type="submit" disabled={!Number(valor.replace(',', '.'))} className="btn-primary px-5">Incluir</button>
            </form>)}
        </div>))}</div>
    </>
  )
}
function Detail({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  const o = r.option!; const h = r.current!
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5"><Comparativo hoje={h} opcao={o} /></div>
      {r.benefit?.benefit_type === 'LOWER_MONTHLY_PAYMENT' && <div className="mt-3 flex items-center gap-2 rounded-2xl bg-itau-orange-soft p-3 text-[14px] font-semibold text-itau-orange"><CircleDollarSign className="h-5 w-5" /> {brl(r.benefit.monthly_difference ?? 0)} a mais livres por mês</div>}
      {r.tradeoffs?.slice(0, 1).map((t) => <div key={t} className="mt-2 flex items-start gap-2 rounded-2xl bg-itau-blue-soft/60 p-3 text-[13px] text-ink-soft"><Info className="h-4 w-4 shrink-0 mt-0.5" /> {t}</div>)}
      <div className="mt-3 space-y-2">
        <button onClick={() => onAcao('VIEW_OPTIONS')} className="card w-full p-4 flex items-center justify-between text-[15px] font-semibold"><span className="flex items-center gap-3"><ListChecks className="h-5 w-5 text-ink-soft" /> Ver outras opções</span><ChevronRight className="h-5 w-5 text-ink-soft" /></button>
        <button onClick={() => onAcao('ASK_WHY', { option_id: o.id })} className="card w-full p-4 flex items-center justify-between text-[15px] font-semibold"><span className="flex items-center gap-3"><MessageCircleQuestion className="h-5 w-5 text-ink-soft" /> Por que essa opção?</span><ChevronRight className="h-5 w-5 text-ink-soft" /></button>
      </div>
      <div className="mt-4"><Cta onClick={() => onAcao('SELECT_OPTION', { option_id: o.id })}>{r.cta ?? 'Continuar com esta opção'}</Cta></div>
    </>
  )
}
function Comparison({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  return (
    <>
      <Titulo>Veja outras opções para o seu momento</Titulo><Sub>Todas reúnem suas dívidas em um único pagamento. Escolha o que faz mais sentido para você.</Sub>
      <div className="mt-5 space-y-3">{r.options.map((o) => (
        <button key={o.id} onClick={() => onAcao('SELECT_OPTION', { option_id: o.id })} className={`w-full text-left rounded-3xl border p-4 transition active:scale-[0.99] ${o.recommended ? 'border-itau-orange bg-itau-orange-soft/40' : 'border-line bg-white'}`}>
          <div className="flex items-center justify-between"><span className={`font-bold ${o.recommended ? 'text-itau-orange' : ''}`}>{o.label}</span>{o.recommended && <span className="chip bg-itau-orange text-white">Recomendada</span>}</div>
          <div className="mt-1 flex items-baseline gap-1"><span className="text-[28px] font-extrabold">{brl(o.monthly_payment)}</span><span className="text-sm text-ink-soft">/mês</span></div>
          <div className="text-[13px] text-ink-soft">{o.description}</div>
          <div className="mt-3 flex items-center justify-between text-[13px] text-ink-soft"><span className="flex items-center gap-4"><span className="flex items-center gap-1"><Calendar className="h-4 w-4" /> {o.term_months} meses</span><span className="flex items-center gap-1"><Layers className="h-4 w-4" /> {brl(o.total_cost)} no total</span></span><ChevronRight className="h-5 w-5" /></div>
        </button>))}</div>
      {r.quick_replies[0] && <div className="mt-3 flex items-start gap-2 rounded-2xl bg-warn-soft/60 p-3 text-[13px] text-ink-soft"><Sparkles className="h-4 w-4 shrink-0 mt-0.5 text-itau-orange" /> {r.quick_replies[0].label}</div>}
    </>
  )
}
function Texto({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  return (
    <>
      {r.guardrail && <div className="mb-3 flex items-center gap-2 rounded-xl bg-itau-blue-soft px-3 py-2 text-xs text-itau-blue"><ShieldCheck className="h-4 w-4" /> Guardrail de {r.guardrail.camada}: <b>{r.guardrail.tipo.replace(/_/g, ' ')}</b>{r.guardrail.camada === 'entrada' && ' · modelo não foi chamado'}</div>}
      {r.content.title && <><Faisca /><Titulo>{r.content.title}</Titulo></>}
      <div className="mt-3 rounded-3xl bg-white border border-line p-4 text-[15px] leading-relaxed">{r.content.description}</div>
      {r.criteria && <ul className="mt-3 space-y-2">{r.criteria.map((c) => <li key={c} className="flex gap-2 text-[14px]"><Check className="h-4 w-4 mt-0.5 text-ok shrink-0" /> {c}</li>)}</ul>}
      {r.tradeoffs?.map((t) => <div key={t} className="mt-2 flex items-start gap-2 rounded-2xl bg-itau-blue-soft/60 p-3 text-[13px] text-ink-soft"><Info className="h-4 w-4 shrink-0 mt-0.5" /> {t}</div>)}
      {r.option && r.allowed_actions.includes('SELECT_OPTION') && <div className="mt-4"><Cta onClick={() => onAcao('SELECT_OPTION', { option_id: r.option!.id })}>Continuar com “{r.option.label}”</Cta></div>}
      {r.allowed_actions.includes('VIEW_OPTIONS') && <button onClick={() => onAcao('VIEW_OPTIONS')} className="w-full mt-3 py-2 text-itau-orange font-bold">Ver outras opções</button>}
      {r.allowed_actions.includes('START') && !r.option && <button onClick={() => onAcao('START')} className="w-full mt-3 py-2 text-itau-orange font-bold">Ver o que cabe no meu bolso</button>}
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
        <Linha icon={<Layers className="h-4 w-4" />} k="Total a pagar" v={brl(t.total_a_pagar)} />
        <Linha icon={<Percent className="h-4 w-4" />} k="Custo efetivo total (CET)" v={`${t.cet_mensal_pct.toLocaleString('pt-BR')}% ao mês`} />
        <Linha icon={<CalendarDays className="h-4 w-4" />} k="Primeiro vencimento" v={dataLonga(t.primeiro_vencimento)} />
      </div>
    </div>
  )
}
function Terms({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  const t = r.terms!; const o = r.option!
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5"><TermosCard t={t} o={o} titulo={o.label} /></div>
      <div className="card mt-3 p-4"><div className="text-[13px] font-semibold">Dívidas incluídas</div><Dividas lista={t.dividas_incluidas} /><div className="mt-2 text-[12px] text-ink-soft">{t.dividas_incluidas.map((d) => `${d.nome}: ${acaoLabel(d.acao)}`).join(' · ')}</div></div>
      {r.tradeoffs?.slice(0, 1).map((x) => <div key={x} className="mt-3 flex items-start gap-2 rounded-2xl bg-itau-blue-soft/60 p-3 text-[13px] text-ink-soft"><Info className="h-4 w-4 shrink-0 mt-0.5" /> {x}</div>)}
      <div className="mt-3 flex items-start gap-3 rounded-2xl bg-white border border-line p-3"><Lock className="h-5 w-5 text-ink-soft shrink-0" /><div><div className="font-bold text-[14px]">Você sempre decide</div><div className="text-[13px] text-ink-soft">{r.notice}</div></div></div>
      <div className="mt-4"><Cta onClick={() => onAcao('CONTINUE')}>{r.cta ?? 'Continuar'}</Cta></div>
      <button onClick={() => onAcao('CANCEL')} className="w-full mt-2 py-2 text-itau-orange font-bold">Voltar às opções</button>
    </>
  )
}
function Confirmation({ r, onAcao }: { r: Resposta; onAcao: (a: Acao, p?: any) => void }) {
  const t = r.final_terms!
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="mt-5 rounded-3xl bg-ok-soft/70 p-4">
        <div className="flex items-center justify-between"><span className="chip bg-white text-ok">{t.debito_automatico ? 'Com débito automático' : 'Pagamento manual'}</span><span className="text-[22px] font-extrabold">{brl2(t.parcela_mensal)}<span className="text-xs font-medium text-ink-soft"> /mês</span></span></div>
        <div className="text-[13px] text-ink-soft mt-1">{t.prazo_meses} meses · {brl(t.total_a_pagar)} no total</div>
        {r.claims?.[0] && <div className="mt-2 chip bg-white text-ok"><Check className="h-3 w-3" /> {r.claims[0]}</div>}
      </div>
      <div className="mt-3"><TermosCard t={t} /></div>
      {r.account && <div className="card mt-3 p-4"><div className="text-[13px] font-semibold">Conta para débito automático</div><div className="mt-2 flex items-center justify-between text-[14px]"><span className="flex items-center gap-2"><Landmark className="h-5 w-5 text-itau-orange" /> Conta {r.account.banco}</span><span className="text-ink-soft">Ag {r.account.agencia} · CC {r.account.conta}</span></div></div>}
      <div className="card mt-3 p-4"><div className="text-[13px] font-semibold">Dívidas incluídas</div><Dividas lista={t.dividas_incluidas} /></div>
      <div className="mt-3 flex items-start gap-2 rounded-2xl bg-itau-blue-soft/60 p-3 text-[12px] text-ink-soft"><Info className="h-4 w-4 shrink-0 mt-0.5" /> {r.notice}</div>
      <div className="mt-4"><Cta onClick={() => onAcao('CONFIRM', { frase: r.cta })}>{r.cta}</Cta></div>
      <button onClick={() => onAcao('CANCEL')} className="w-full mt-2 py-2 text-itau-orange font-bold">Revisar</button>
      <div className="mt-1 text-center text-[11px] text-ink-soft">Só o botão acima autoriza a contratação. Ver, selecionar ou perguntar não contrata nada.</div>
    </>
  )
}
function Success({ r, onSair }: { r: Resposta; onSair: () => void }) {
  const t = r.final_terms!; const res = r.result!
  return (
    <>
      <div className="relative h-32 w-32 mx-auto mb-2"><div className="absolute inset-0 rounded-full bg-gradient-to-br from-[#FFD7B5] to-[#FF9A4D] opacity-80" /><div className="absolute inset-8 rounded-full bg-itau-orange grid place-items-center text-white"><Check className="h-8 w-8" /></div></div>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      <div className="card mt-5 p-4"><div className="flex items-center gap-3"><span className="h-10 w-10 rounded-xl bg-itau-orange-soft text-itau-orange grid place-items-center"><CircleDollarSign className="h-5 w-5" /></span><div><div className="text-[13px] text-ink-soft">Sua nova parcela</div><div className="text-[24px] font-extrabold leading-tight">{brl2(res.new_monthly_payment)}<span className="text-sm font-medium text-ink-soft">/mês</span></div></div></div><div className="mt-2 text-[13px] text-ink-soft">Primeiro vencimento em {dataLonga(t.primeiro_vencimento)}</div>
        {res.monthly_reduction > 0 && <div className="mt-3 rounded-2xl bg-ok-soft p-3 text-[13px]"><div className="font-bold text-ok flex items-center gap-1"><Check className="h-4 w-4" /> {brl(res.monthly_reduction)} a mais no seu bolso todo mês</div><div className="text-ink-soft">Em comparação com seus pagamentos anteriores.</div></div>}
      </div>
      <div className="mt-4 text-[15px] font-bold">O que acontece agora?</div>
      <div className="mt-2 space-y-2">{r.next_steps?.map((s) => <div key={s} className="card p-3 text-[13px] flex gap-3"><Check className="h-4 w-4 text-ok shrink-0 mt-0.5" /> {s}</div>)}</div>
      <div className="mt-4"><Cta onClick={onSair}>{r.cta ?? 'Acompanhar'}</Cta></div>
      <button onClick={onSair} className="w-full mt-2 py-2 text-itau-orange font-bold">Voltar para o início</button>
    </>
  )
}
function Erro({ r, onAcao, onSair }: { r: Resposta; onAcao: (a: Acao, p?: any) => void; onSair: () => void }) {
  return (
    <>
      <Faisca /><Titulo>{r.content.title}</Titulo><Sub>{r.content.description}</Sub>
      {r.error && <div className="mt-3 rounded-2xl bg-mist p-3 text-[11px] text-ink-soft break-words">detalhe técnico: {r.error}</div>}
      <div className="mt-5 space-y-2">
        {r.allowed_actions.includes('RETRY') && <button onClick={() => onAcao('GET')} className="btn-primary w-full py-4 rounded-full">Tentar de novo</button>}
        {r.allowed_actions.includes('ESCALATE') && <button onClick={() => onAcao('ASK_QUESTION', { text: 'quero falar com uma pessoa' })} className="btn-ghost w-full py-4 rounded-full">Falar com uma pessoa</button>}
        {r.allowed_actions.includes('START') && <button onClick={() => onAcao('START')} className="btn-ghost w-full py-4 rounded-full">Ver opções</button>}
        <button onClick={onSair} className="w-full py-2 text-itau-orange font-bold">Voltar para o início</button>
      </div>
    </>
  )
}

/* ---------- shell ---------- */
export function Experiencia({ onSair, inicial }: { onSair: () => void; inicial?: Resposta }) {
  const [resp, setResp] = useState<Resposta | null>(inicial ?? null)
  const [carregando, setCarregando] = useState(false)
  const [status, setStatus] = useState<{ title: string; steps: string[]; feitos: number } | null>(null)
  const [texto, setTexto] = useState('')
  const topo = useRef<HTMLDivElement>(null)

  useEffect(() => { if (!inicial) api.experiencia().then(setResp) }, [inicial])
  useEffect(() => { topo.current?.scrollTo({ top: 0 }) }, [resp])

  async function acao(a: Acao, payload: Record<string, unknown> = {}) {
    if (carregando) return
    setCarregando(true)
    try {
      const r = await api.evento(a, payload)
      if (r.status) {  // STATUS: mostra o progresso antes do resultado (spec §13)
        const steps = r.status.steps
        for (let i = 0; i <= steps.length; i++) { setStatus({ title: r.status.title, steps, feitos: i }); await new Promise((res) => setTimeout(res, i === steps.length ? 350 : 650)) }
        setStatus(null)
      }
      setResp(r)
    } finally { setCarregando(false) }
  }

  const voltar = resp && ['REVIEWING', 'AWAITING_CONFIRMATION', 'EXPLAINING'].includes(resp.state) && resp.response_type !== 'SUCCESS'
  const esperando = carregando && !status
  const podePerguntar = !!resp && resp.response_type !== 'SUCCESS' && !status

  return (
    <div className="h-full flex flex-col bg-[#FBF6F1] relative overflow-hidden">
      <div className="pointer-events-none absolute -top-24 -right-24 h-72 w-72 rounded-full bg-[radial-gradient(circle,_rgba(255,170,90,0.45),_transparent_65%)]" />
      <div className="relative flex items-center justify-between px-4 pt-4 pb-2">
        {voltar ? <button onClick={() => acao('CANCEL')} aria-label="Voltar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-black/5"><ChevronLeft /></button>
          : <button onClick={onSair} aria-label="Fechar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-black/5"><X /></button>}
        <span className="text-[15px] font-semibold text-ink-soft">zera.ai</span>
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
            {resp.response_type === 'TEXT' && <Texto r={resp} onAcao={acao} />}
            {resp.response_type === 'TERMS_REVIEW' && <Terms r={resp} onAcao={acao} />}
            {resp.response_type === 'CONFIRMATION_REQUEST' && <Confirmation r={resp} onAcao={acao} />}
            {resp.response_type === 'SUCCESS' && <Success r={resp} onSair={onSair} />}
            {resp.response_type === 'ERROR' && <Erro r={resp} onAcao={acao} onSair={onSair} />}
            {resp.response_type === 'PROACTIVE_MESSAGE' && <Summary r={{ ...resp, summary: resp.summary ?? { pagamento_mensal: 0, qtd_pagamentos: 0, prazo_meses: 0, total_a_pagar: 0, dividas: [] } }} onAcao={acao} />}
          </div>
        )}
      </div>
      {podePerguntar && (
        <div className="relative px-4 pb-4 pt-1">
          <form className="flex items-center gap-2 rounded-full bg-white border border-line px-4 py-2 shadow-sm" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) { acao('ASK_QUESTION', { text: texto.trim() }); setTexto('') } }}>
            <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Digite aqui" className="flex-1 bg-transparent outline-none text-[15px] py-1" aria-label="Pergunte à zera.ai" />
            {texto.trim() ? <button type="submit" aria-label="Enviar" className="h-9 w-9 grid place-items-center rounded-full bg-itau-orange text-white"><ArrowUp className="h-5 w-5" /></button> : <Mic className="h-5 w-5 text-ink-soft" />}
          </form>
          <div className="mt-2 text-center text-[11px] text-ink-soft">{resp?.disclaimer}</div>
        </div>
      )}
    </div>
  )
}
