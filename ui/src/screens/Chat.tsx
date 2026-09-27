/* Conversa com o agente ADK — mostra a interação com a persona conforme os eventos do ADK chegam (NDJSON):
   cada tool chamada vira um chip, cada resultado vira um card do motor (raio-x, capacidade, prioridades, cenários,
   acordo, amortização), o texto do agente vem por último e as ações com efeito param no card de confirmação (HITL nativo:
   adk_request_confirmation) — a cliente decide no botão. Guardrails aparecem como selo quando bloqueiam. */

import { ArrowUp, Check, ChevronRight, ShieldCheck, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, getCliente } from '../api'
import { Faisca, dataBR } from '../components/ui'
import type { CardChat, EventoChat, Hitl } from '../types'

const brl = (v: number) => Number(v ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const brl0 = (v: number) => Number(v ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })
const pct = (v: number) => `${(Number(v ?? 0) * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`
const ROTULO_TOOL: Record<string, string> = {
  get_perfil_financeiro: 'lendo seu extrato', priorizar_dividas: 'priorizando dívidas', calcular_capacidade: 'calculando o que cabe',
  montar_cenarios: 'montando cenários', simular_planos: 'simulando planos', comparar_com_padrao: 'comparando com o padrão',
  fechar_acordo: 'contratando o acordo', status_acordo: 'consultando o acordo', acionar_respiro: 'acionando o respiro',
  amortizar: 'simulando amortização', listar_gatilhos: 'verificando avisos', escalar_humano: 'chamando uma pessoa',
  registrar_consentimento: 'registrando consentimento', revogar_consentimento: 'apagando seus dados',
  informar_renda: 'anotando sua renda', informar_gasto_fixo: 'anotando o gasto fixo',
}

/* Markdown leve para o texto do agente: **negrito**, itens "- " / "1) " / "1." e parágrafos. Sem biblioteca. */
function Inline({ t }: { t: string }) {
  const partes = t.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)
  return <>{partes.map((x, i) => x.startsWith('**') && x.endsWith('**') ? <b key={i}>{x.slice(2, -2)}</b> : <span key={i}>{x.replace(/\*/g, '')}</span>)}</>
}
function Texto({ texto }: { texto: string }) {
  const blocos = texto.replace(/\r/g, '').split(/\n{2,}/).map((b) => b.trim()).filter(Boolean)
  return (
    <div className="space-y-2">
      {blocos.map((b, i) => {
        const linhas = b.split('\n').map((l) => l.trim()).filter(Boolean)
        const lista = linhas.length > 0 && linhas.every((l) => /^([-•*]|\d+[).])\s+/.test(l))
        if (lista) {
          const numerada = /^\d+[).]/.test(linhas[0])
          return (
            <ol key={i} className={`space-y-1 pl-1 ${numerada ? '' : 'list-none'}`}>
              {linhas.map((l, j) => { const m = l.match(/^(?:[-•*]|(\d+)[).])\s+(.*)$/); return (
                <li key={j} className="flex gap-2"><span className={`shrink-0 ${numerada ? 'h-5 w-5 rounded-full bg-itau-orange-soft text-itau-orange grid place-items-center text-[11px] font-bold' : 'text-itau-orange'}`}>{numerada ? (m?.[1] ?? j + 1) : '•'}</span><span><Inline t={m?.[2] ?? l} /></span></li>) })}
            </ol>)
        }
        return <p key={i}>{linhas.map((l, j) => <span key={j}><Inline t={l} />{j < linhas.length - 1 && <br />}</span>)}</p>
      })}
    </div>
  )
}

const ETAPAS = [
  { id: 'entender', label: 'Entender' }, { id: 'opcoes', label: 'Opções' }, { id: 'escolher', label: 'Escolher' },
  { id: 'confirmar', label: 'Confirmar no app' }, { id: 'acompanhar', label: 'Acompanhar' },
] as const
type Etapa = typeof ETAPAS[number]['id']
/* Sequência do fluxo — só aparece depois que a cliente pede algo que a inicia; o passo humano (confirmar) fica evidente. */
function Trilha({ etapa }: { etapa: Etapa }) {
  const i = ETAPAS.findIndex((e) => e.id === etapa)
  return (
    <div className="sticky top-0 z-10 -mx-4 px-4 py-2 bg-[#FBF6F1]/95 backdrop-blur">
      <ol className="flex items-center gap-1 text-[10px] font-semibold">
        {ETAPAS.map((e, j) => (
          <li key={e.id} className="flex items-center gap-1">
            <span className={`rounded-full px-2 py-1 ${j < i ? 'bg-ok-soft text-ok' : j === i ? (e.id === 'confirmar' ? 'bg-itau-orange text-white' : 'bg-itau-orange-soft text-itau-orange') : 'bg-mist text-ink-soft'}`}>{j < i ? '✓ ' : ''}{e.label}</span>
            {j < ETAPAS.length - 1 && <span className="text-ink-soft/50">›</span>}
          </li>
        ))}
      </ol>
    </div>
  )
}

type Item =
  | { k: 'cliente'; texto: string }
  | { k: 'zera'; texto: string; llm?: boolean }
  | { k: 'tools'; chips: Array<{ nome: string; ok?: boolean; erro?: string | null }> }
  | { k: 'card'; bloco: CardChat }
  | { k: 'hitl'; hitl: Hitl; resolvido?: 'sim' | 'nao' }
  | { k: 'sistema'; texto: string }

/* ---------- cards do motor ---------- */
function Card({ bloco, onContratar }: { bloco: CardChat; onContratar: (id: string) => void }) {
  const d = bloco.dados ?? {}
  const Linha = ({ k, v }: { k: string; v: string }) => <div className="flex items-center justify-between py-1.5 text-[13px] border-b border-line/60 last:border-0"><span className="text-ink-soft">{k}</span><span className="font-semibold text-right">{v}</span></div>
  const Titulo = ({ t }: { t: string }) => <div className="text-[12px] font-bold uppercase tracking-wide text-itau-orange mb-1">{t}</div>
  switch (bloco.tipo) {
    case 'raio_x':
      return (
        <div className="card p-3"><Titulo t="Raio-X das dívidas" />
          {(d.dividas ?? []).map((x: any) => <Linha key={x.divida_id} k={`${x.produto?.replace('_', ' ')} · ${x.taxa_mensal > 0 ? `${pct(x.taxa_mensal)} a.m.` : 'sem juros'}${x.fonte === 'derivada_extrato' ? ' · estimado do extrato' : ''}`} v={x.taxa_mensal > 0 ? `${brl0(x.saldo)} (${brl0(x.custo_mensal)}/mês de juros)` : x.parcela_atual > 0 ? `${brl0(x.saldo)} (${x.parcelas_restantes}x ${brl(x.parcela_atual)})` : brl0(x.saldo)} />)}
          <Linha k="Total devido" v={brl0(d.total_dividas)} /><Linha k="Cresce por mês" v={d.custo_total_mensal > 0 ? `${brl0(d.custo_total_mensal)} só de juros` : 'nada — sem juros correndo'} />
          {d.renda_conhecida === false
            ? <div className="mt-2 rounded-xl bg-itau-orange-soft/60 px-3 py-2 text-[12px]"><b>Renda não identificada no extrato.</b> Sem ela a zera.ai não calcula sobra nem parcela: me diga quanto entra por mês.</div>
            : d.renda_media > 0 && <Linha k={d.renda_informada_pela_cliente ? 'Renda (informada por você)' : `Renda média mensal (entradas do extrato, ${d.meses_com_renda} meses)`} v={`${brl0(d.renda_media)}/mês`} />}
        </div>)
    case 'capacidade':
      return (
        <div className="card p-3"><Titulo t="O que cabe no seu mês" />
          <div className="text-[24px] font-extrabold leading-tight">{brl0(d.parcela_maxima)}<span className="text-sm font-medium text-ink-soft">/mês no máximo</span></div>
          {d.renda_considerada > 0 && <Linha k={d.renda_informada_pela_cliente ? 'Renda informada por você' : 'Renda média mensal (entradas do extrato)'} v={`${brl0(d.renda_considerada)}/mês`} />}
          {d.essenciais_mediana > 0 && <Linha k="Contas essenciais (extrato)" v={`${brl0(d.essenciais_mediana)}/mês`} />}
          {d.compromissos_informados > 0 && <Linha k="Gastos fixos informados" v={`${brl0(d.compromissos_informados)}/mês`} />}
          <Linha k="Sobra num mês apertado (P25)" v={brl0(d.sobra_p25)} /><Linha k="Colchão para imprevistos" v={brl0(d.colchao)} />
          <Linha k="Meses fracos" v={(d.meses_fracos ?? []).join(', ') || '—'} /><Linha k="Respiros por ano" v={String(d.respiros_ano ?? 0)} />
        </div>)
    case 'prioridades':
      return (
        <div className="card p-3"><Titulo t="Ordem de ataque" />
          {(d.ordem ?? []).map((o: any) => <div key={o.divida_id} className="flex gap-2 py-1.5 text-[13px] border-b border-line/60 last:border-0"><span className="h-5 w-5 shrink-0 rounded-full bg-itau-orange-soft text-itau-orange grid place-items-center text-[11px] font-bold">{o.prioridade}</span><span><b>{o.nome}</b> — {o.motivo}</span></div>)}
        </div>)
    case 'cenarios': {
      if (d.nenhum_cenario_cabe) return <div className="card p-3 text-[13px]"><Titulo t="Nenhum cenário cabe" />{d.motivo}</div>
      const melhorId: string | null = d.recomendado_para_alvo ?? d.recomendado ?? null
      const lista: any[] = [...(d.cenarios ?? [])].sort((a, b) => (a.id === melhorId ? -1 : b.id === melhorId ? 1 : 0))
      const ROT: Record<string, string> = { recomendado: 'recomendada', mais_barato: 'menor custo total', mais_rapido: 'termina antes', mais_folga: 'menor parcela', guardar_extra: 'guarda o extra', atende_alvo: `até ${brl0(d.parcela_alvo ?? 0)}` }
      const diag = d.diagnostico_alvo
      return (
        <div className="card p-3"><Titulo t={d.parcela_alvo ? `Opções para parcela até ${brl0(d.parcela_alvo)}` : 'Opções que cabem no seu mês'} />
          {diag && <div className="mb-2 rounded-xl bg-itau-orange-soft/60 px-3 py-2 text-[12px]">Nenhuma opção chega a {brl0(diag.parcela_alvo)}. A menor parcela possível é <b>{brl(diag.menor_parcela_possivel)}</b> em {diag.prazo}x{diag.entrada_necessaria ? <> — para chegar a {brl0(diag.parcela_alvo)} em {diag.prazo_max}x seria preciso uma entrada de <b>{brl0(diag.entrada_necessaria)}</b></> : null}.</div>}
          <div className="space-y-2">{lista.map((c: any) => { const melhor = c.id === melhorId; return (
            <div key={c.id} className={`rounded-2xl border p-3 ${melhor ? 'border-itau-orange bg-itau-orange-soft/40' : 'border-line'}`}>
              {melhor && <div className="text-[10px] font-bold uppercase tracking-wide text-itau-orange mb-1">{d.parcela_alvo ? 'Melhor para o que você pediu' : 'Melhor para você'}</div>}
              <div className="flex items-center justify-between"><span className="text-[12px] font-bold">{c.id} · {(c.rotulos ?? []).map((r: string) => ROT[r] ?? r.replace(/_/g, ' ')).join(' · ')}</span><span className="text-[18px] font-extrabold">{brl(c.comprometimento_mensal)}<span className="text-[11px] font-medium text-ink-soft">/mês</span></span></div>
              <div className="text-[12px] text-ink-soft">{c.prazo_meses} meses · total {brl0(c.custo_total)} = saldo {brl0(c.saldo_original)} + juros {brl0(c.juros_acordo)}{c.entrada > 0 ? ` · entrada ${brl0(c.entrada)}` : ''}</div>
              <button onClick={() => onContratar(c.id)} className={`mt-2 inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[13px] font-bold ${melhor ? 'bg-itau-orange text-white' : 'border border-itau-orange text-itau-orange'}`}>Contratar {c.id} <ChevronRight className="h-4 w-4" /></button>
              <span className="ml-2 text-[10px] text-ink-soft">você confirma no próximo passo</span>
            </div>) })}</div>
        </div>)
    }
    case 'planos':
      return (
        <div className="card p-3"><Titulo t="Planos" />
          {(d.planos ?? []).map((p: any) => <Linha key={p.id} k={`${p.id} · ${p.nome}${p.cabe ? '' : ' (não cabe)'}`} v={p.prazo > 1 ? `${p.prazo}x ${brl(p.parcela)}` : brl0(p.total_pago)} />)}
        </div>)
    case 'acordo':
      return (
        <div className="card p-3 border-ok"><Titulo t="Seu acordo" />
          <div className="text-[24px] font-extrabold leading-tight">{brl(d.parcela)}<span className="text-sm font-medium text-ink-soft">/mês</span></div>
          <Linha k="Status" v={String(d.status)} /><Linha k="Parcelas" v={`${d.pagas ?? 0} pagas de ${d.prazo}`} />
          {d.proximo_vencimento && <Linha k="Próximo vencimento" v={dataBR(d.proximo_vencimento)} />}<Linha k="Saldo devedor" v={brl0(d.saldo_devedor)} />
          <Linha k="Respiros" v={`${d.respiros_usados ?? 0} de ${d.respiros_max ?? 0} usados`} />
        </div>)
    case 'amortizacao':
      return (
        <div className="card p-3"><Titulo t="Amortização" />
          <Linha k="Valor recebido" v={brl0(d.valor_recebido)} /><Linha k="Reserva sugerida" v={brl0(d.reserva_sugerida)} /><Linha k="Abate do saldo" v={brl0(d.abatimento_no_saldo)} />
          <Linha k="Parcelas a menos" v={String(d.parcelas_a_menos ?? 0)} />
        </div>)
    default:
      return <div className="card p-3 text-[13px]"><Titulo t={bloco.tipo} />{d.explicacao ?? JSON.stringify(d).slice(0, 200)}</div>
  }
}

function CardHitl({ hitl, resolvido, onDecidir }: { hitl: Hitl; resolvido?: 'sim' | 'nao'; onDecidir: (ok: boolean) => void }) {
  return (
    <div className="rounded-3xl border-2 border-itau-orange bg-white p-4 shadow-[0_8px_24px_rgba(236,112,0,0.15)]">
      <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-wide text-itau-orange"><ShieldCheck className="h-4 w-4" /> Confirmação necessária</div>
      <div className="mt-1 text-[17px] font-extrabold">{hitl.titulo}</div>
      {hitl.resumo && <div className="mt-1 text-[12px] text-ink-soft">{hitl.resumo}</div>}
      <div className="mt-2">{hitl.detalhes.map((d) => <div key={d.k} className="flex items-center justify-between py-1.5 text-[13px] border-b border-line/60 last:border-0"><span className="text-ink-soft">{d.k}</span><span className="font-semibold">{d.v}</span></div>)}</div>
      <div className="mt-2 text-[11px] text-ink-soft">Nada é executado sem a sua confirmação aqui — este é o seu passo. Esta decisão fica registrada com data e hora.</div>
      {resolvido ? <div className={`mt-3 chip ${resolvido === 'sim' ? 'bg-ok-soft text-ok' : 'bg-mist text-ink-soft'}`}>{resolvido === 'sim' ? <><Check className="h-3 w-3" /> Confirmado</> : <><X className="h-3 w-3" /> Não confirmado</>}</div> : (
        <div className="mt-3 flex gap-2">
          <button onClick={() => onDecidir(true)} className="btn-primary flex-1 py-3 rounded-full">{hitl.frase_sugerida}</button>
          <button onClick={() => onDecidir(false)} className="btn-ghost py-3 rounded-full">Agora não</button>
        </div>)}
    </div>
  )
}

/* A conversa sobrevive à navegação (home <-> experiência guiada <-> chat): estado por cliente fica em memória do app e a
   sessão do ADK continua no backend — voltar para o chat retoma de onde parou, sem nova abertura. */
const memoriaConversa = new Map<string, { sessao: string; itens: Item[]; sugestoes: string[]; protecoes: string[]; etapa: Etapa | null }>()

/* ---------- tela ---------- */
export function Chat({ nome, onSair, onAbrirExperiencia, mensagemInicial }: { nome: string; onSair: () => void; onAbrirExperiencia: () => void; mensagemInicial?: string }) {
  const chave = getCliente()
  const salva = memoriaConversa.get(chave)
  const [itens, setItens] = useState<Item[]>(salva?.itens ?? [])
  const [sugestoes, setSugestoes] = useState<string[]>(salva?.sugestoes ?? [])
  const [protecoes, setProtecoes] = useState<string[]>(salva?.protecoes ?? [])
  const [texto, setTexto] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [etapa, setEtapa] = useState<Etapa | null>(salva?.etapa ?? null)
  const sessao = useRef(salva?.sessao ?? `chat-${Math.random().toString(36).slice(2, 8)}`)
  const fim = useRef<HTMLDivElement>(null)
  const inicialEnviada = useRef(false)

  useEffect(() => {
    if (salva) return                                   // voltou para a conversa: retoma sem nova abertura
    api.chatInicio(sessao.current).then((r) => { setItens([{ k: 'zera', texto: r.texto }]); setSugestoes(r.sugestoes); setProtecoes(r.protecoes) })
      .catch((e) => setItens([{ k: 'sistema', texto: e instanceof Error ? e.message : 'API indisponível' }]))
  }, [])
  useEffect(() => { memoriaConversa.set(chave, { sessao: sessao.current, itens, sugestoes, protecoes, etapa }) }, [itens, sugestoes, protecoes, etapa])
  useEffect(() => { fim.current?.scrollIntoView({ behavior: 'smooth' }) }, [itens, ocupado])
  useEffect(() => {                                     // veio da tela guiada com um texto digitado: manda como 1ª mensagem
    if (mensagemInicial && !inicialEnviada.current && !ocupado && (salva || itens.length > 0)) { inicialEnviada.current = true; void enviar(mensagemInicial) }
  }, [itens, ocupado])

  const push = (it: Item) => setItens((l) => [...l, it])
  function tratar(e: EventoChat) {
    if (e.tipo === 'tool_call') setItens((l) => { const u = l[l.length - 1]; const chip = { nome: e.nome }; return u?.k === 'tools' ? [...l.slice(0, -1), { k: 'tools', chips: [...u.chips, chip] }] : [...l, { k: 'tools', chips: [chip] }] })
    else if (e.tipo === 'tool_result') setItens((l) => l.map((it) => it.k === 'tools' ? { ...it, chips: it.chips.map((c) => c.nome === e.nome && c.ok === undefined ? { ...c, ok: e.ok, erro: e.erro } : c) } : it))
    else if (e.tipo === 'card') { push({ k: 'card', bloco: e.bloco }); if (e.bloco.tipo === 'cenarios' && !e.bloco.dados?.nenhum_cenario_cabe) setEtapa('escolher'); if (e.bloco.tipo === 'acordo') setEtapa('acompanhar') }
    else if (e.tipo === 'etapa') setEtapa((atual) => (e.etapa === 'entender' && atual && atual !== 'entender') ? atual : e.etapa)
    else if (e.tipo === 'texto') push({ k: 'zera', texto: e.texto, llm: !e.roteado })
    else if (e.tipo === 'hitl') { push({ k: 'hitl', hitl: e.hitl }); setEtapa('confirmar') }
    else if (e.tipo === 'guardrail') { /* proteção aplicada no backend (registrada para observabilidade); a cliente vê só a resposta acolhedora */ }
    else if (e.tipo === 'erro') push({ k: 'sistema', texto: e.texto })
    else if (e.tipo === 'llm') { /* tokens/custo ficam só no backend (Cloud Trace / Logging / Monitoring) */ }
    else if (e.tipo === 'fim') setSugestoes(e.sugestoes)
  }
  async function enviar(msg: string) {
    if (ocupado || !msg.trim()) return
    push({ k: 'cliente', texto: msg }); setTexto(''); setOcupado(true)
    try { await api.chatStream(sessao.current, msg, tratar) } catch (e) { push({ k: 'sistema', texto: e instanceof Error ? e.message : 'falha' }) } finally { setOcupado(false) }
  }
  async function contratar(cenarioId: string) {
    if (ocupado) return
    setOcupado(true)
    try { const r = await api.chatContratar(sessao.current, cenarioId); push({ k: 'hitl', hitl: r.hitl }); setEtapa('confirmar') }
    catch (e) { push({ k: 'sistema', texto: e instanceof Error ? e.message : 'não consegui abrir a confirmação' }) } finally { setOcupado(false) }
  }
  async function decidir(idx: number, hitl: Hitl, ok: boolean) {
    if (ocupado) return
    setItens((l) => l.map((it, i) => i === idx && it.k === 'hitl' ? { ...it, resolvido: ok ? 'sim' : 'nao' } : it)); setOcupado(true)
    try { await api.chatConfirmar(sessao.current, hitl.request_id, ok, ok ? hitl.frase_sugerida : 'Não confirmo', tratar) } catch (e) { push({ k: 'sistema', texto: e instanceof Error ? e.message : 'falha' }) } finally { setOcupado(false) }
  }
  const temHitlPendente = itens.some((it) => it.k === 'hitl' && !it.resolvido)

  return (
    <div className="h-full flex flex-col bg-[#FBF6F1] relative">
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <button onClick={onSair} aria-label="Fechar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-black/5"><X /></button>
        <span className="flex items-center gap-2 text-[15px] font-semibold text-ink-soft"><Faisca className="h-5 w-5" /> zera.ai · conversa</span>
        <button onClick={onAbrirExperiencia} className="text-[12px] font-bold text-itau-orange">Ver na tela</button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-3">
        {etapa && <Trilha etapa={etapa} />}
        {protecoes.length > 0 && itens.length <= 1 && (
          <div className="rounded-2xl bg-itau-blue-soft/60 p-3 text-[12px] text-ink-soft"><div className="flex items-center gap-1 font-bold text-itau-blue"><ShieldCheck className="h-4 w-4" /> Como eu me protejo e te protejo</div><ul className="mt-1 space-y-0.5">{protecoes.map((p) => <li key={p}>· {p}</li>)}</ul></div>
        )}
        {itens.map((it, i) => {
          if (it.k === 'cliente') return <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-itau-orange text-white px-3 py-2 text-[14px]">{it.texto}</div>
          if (it.k === 'zera') return <div key={i} className="max-w-[92%] rounded-2xl rounded-bl-md bg-white border border-line px-3 py-2 text-[14px] leading-relaxed"><Texto texto={it.texto} />{it.llm}</div>
          if (it.k === 'tools') return <div key={i} className="flex flex-wrap gap-1.5">{it.chips.map((c, j) => c.erro === 'renda_desconhecida'
            ? <span key={j} className="chip text-[11px] bg-itau-orange-soft text-itau-orange"><Wrench className="h-3 w-3" /> {ROTULO_TOOL[c.nome] ?? c.nome}: preciso da sua renda</span>
            : <span key={j} className={`chip text-[11px] ${c.ok === false ? 'bg-danger-soft text-danger' : c.ok ? 'bg-ok-soft text-ok' : 'bg-mist text-ink-soft'}`}><Wrench className="h-3 w-3" /> {ROTULO_TOOL[c.nome] ?? c.nome}{c.ok === undefined ? '…' : c.ok ? ' ✓' : ' ✗'}</span>)}</div>
          if (it.k === 'card') return <div key={i}><Card bloco={it.bloco} onContratar={contratar} /></div>
          if (it.k === 'hitl') return <div key={i}><CardHitl hitl={it.hitl} resolvido={it.resolvido} onDecidir={(ok) => decidir(i, it.hitl, ok)} /></div>
          return <div key={i} className="text-center text-[12px] text-danger">{it.texto}</div>
        })}
        {ocupado && <div className="flex items-center gap-2 text-[12px] text-ink-soft"><span className="h-3.5 w-3.5 rounded-full border-2 border-itau-orange border-t-transparent animate-spin" /> zera.ai está trabalhando…</div>}
        <div ref={fim} />
      </div>
      <div className="px-4 pb-4 pt-1 bg-[#FBF6F1]">
        {!ocupado && !temHitlPendente && sugestoes.length > 0 && <div className="mb-2 flex gap-2 overflow-x-auto no-scrollbar">{sugestoes.map((s) => <button key={s} onClick={() => enviar(s)} className="chip shrink-0 border border-line bg-white text-[12px] py-2">{s}</button>)}</div>}
        <form className="flex items-center gap-2 rounded-full bg-white border border-line px-4 py-2 shadow-sm" onSubmit={(e) => { e.preventDefault(); enviar(texto) }}>
          <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder={temHitlPendente ? 'Responda no card acima' : `Fale com a zera.ai, ${nome.split(' ')[0]}`} disabled={ocupado || temHitlPendente} className="flex-1 bg-transparent outline-none text-[15px] py-1 disabled:opacity-50" aria-label="Mensagem" />
          <button type="submit" disabled={!texto.trim() || ocupado || temHitlPendente} aria-label="Enviar" className="h-9 w-9 grid place-items-center rounded-full bg-itau-orange text-white disabled:opacity-40"><ArrowUp className="h-5 w-5" /></button>
        </form>
      </div>
    </div>
  )
}
