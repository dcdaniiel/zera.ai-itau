/* Cards ricos renderizados a partir dos blocos `ui` que as tools do agente devolvem. */

import { AlertTriangle, CheckCircle2, ShieldCheck, Sparkles, TrendingDown } from 'lucide-react'
import type { Bloco } from '../types'
import { Barra, Card, Rotulo, brl, dataBR, mesCurto, pct } from './ui'

const NOME_ACAO: Record<string, string> = { quitar: 'Quitar à vista', manter: 'Manter' }
const nomeAcao = (a: string) => NOME_ACAO[a] ?? (a.startsWith('renegociar_') ? `Renegociar em ${a.replace('renegociar_', '')}` : a)
const ROTULO: Record<string, { txt: string; tom: 'orange' | 'ok' | 'blue' | 'grey' }> = {
  recomendado: { txt: 'Recomendado', tom: 'orange' }, mais_barato: { txt: 'Mais barato', tom: 'ok' }, mais_folga: { txt: 'Mais folga', tom: 'blue' }, mais_rapido: { txt: 'Mais rápido', tom: 'grey' },
}

export function RaioX({ d }: { d: any }) {
  const dividas = [...(d.dividas ?? [])].sort((a, b) => (a.prioridade ?? 9) - (b.prioridade ?? 9))
  const maior = Math.max(...dividas.map((x: any) => x.custo_mensal ?? 0), 1)
  return (
    <Card>
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Raio-X das dívidas</div>
        <Rotulo tom="danger"><TrendingDown className="h-3 w-3" /> cresce {brl(d.custo_total_mensal)}/mês</Rotulo>
      </div>
      <div className="mt-1 text-2xl font-extrabold">{brl(d.total_dividas)}</div>
      <div className="mt-3 space-y-3">
        {dividas.map((x: any) => (
          <div key={x.divida_id}>
            <div className="flex items-center justify-between text-sm">
              <div className="font-semibold"><span className="text-itau-orange mr-1">{x.prioridade}º</span>{x.nome ?? x.produto}</div>
              <div className="text-ink-soft">{brl(x.saldo)}</div>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <Barra valor={x.custo_mensal} max={maior} />
              <span className="text-xs text-ink-soft whitespace-nowrap">{brl(x.custo_mensal)}/mês · {pct(x.taxa_mensal)} a.m.</span>
            </div>
            {x.dias_atraso >= 30 && <div className="mt-1 text-xs text-danger flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> {x.dias_atraso} dias de atraso · risco de {x.consequencia}</div>}
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-ink-soft">Ordem por custo e consequência — não por quem cobra mais alto.</div>
    </Card>
  )
}

export function Capacidade({ d }: { d: any }) {
  const meses: string[] = d.meses ?? Object.keys(d.sobra_por_mes ?? {})
  const sobras: number[] = d.sobra_mensal ?? meses.map((m) => d.sobra_por_mes?.[m] ?? 0)
  const max = Math.max(...sobras, 1)
  const fracos = new Set<string>(d.meses_fracos ?? [])
  return (
    <Card>
      <div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Quanto cabe no seu mês</div>
      <div className="mt-1 flex items-baseline gap-2"><div className="text-2xl font-extrabold">{brl(d.parcela_maxima)}</div><div className="text-sm text-ink-soft">parcela máxima</div></div>
      {d.parcela_conforto && <div className="text-sm text-ink-soft">Conforto: <b className="text-ink">{brl(d.parcela_conforto)}</b> {d.perfil_risco === 'renda_irregular' && '· sua renda varia'}</div>}
      <div className="mt-3 flex items-end gap-1 h-16">
        {sobras.map((s, i) => (
          <div key={meses[i]} className="flex-1 flex flex-col items-center gap-1">
            <div className={`w-full rounded-t-md ${fracos.has(meses[i]) ? 'bg-warn' : 'bg-itau-orange/80'}`} style={{ height: `${Math.max(6, (s / max) * 52)}px` }} title={`${mesCurto(meses[i])}: ${brl(s)}`} />
            <div className="text-[9px] text-ink-soft">{mesCurto(meses[i]).slice(0, 3)}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-xl bg-mist p-2"><div className="text-ink-soft">sobra típica</div><div className="font-bold">{brl(d.sobra_mediana)}</div></div>
        <div className="rounded-xl bg-mist p-2"><div className="text-ink-soft">colchão</div><div className="font-bold">{brl(d.colchao)}</div></div>
        <div className="rounded-xl bg-mist p-2"><div className="text-ink-soft">respiros/ano</div><div className="font-bold">{d.respiros_ano}</div></div>
      </div>
      {fracos.size > 0 && <div className="mt-2 text-xs text-warn">Meses apertados: {[...fracos].map(mesCurto).join(', ')} — cobertos pelos respiros.</div>}
    </Card>
  )
}

export function Cenarios({ d, onEscolher }: { d: any; onEscolher?: (id: string) => void }) {
  const lista: any[] = d.cenarios ?? []
  if (!lista.length) return <Card><div className="text-sm">{d.motivo ?? 'Nenhum cenário cabe agora.'}</div></Card>
  const rec = lista[0]
  const outros = lista.slice(1)
  const usaCaixa = rec.usa_caixa ?? rec.acoes.reduce((t: number, a: any) => t + (a.usa_caixa ?? 0), 0)
  return (
    <div className="space-y-2">
      <Card className="border-itau-orange/40 ring-2 ring-itau-orange/20">
        <div className="flex items-center justify-between">
          <Rotulo tom="orange"><Sparkles className="h-3 w-3" /> Recomendado</Rotulo>
          {d.valor_extra > 0 && <span className="text-xs text-ink-soft">usa {brl(usaCaixa)} dos {brl(d.valor_extra)}</span>}
        </div>
        <div className="mt-2 flex items-baseline gap-2"><div className="text-2xl font-extrabold">{brl(rec.comprometimento_mensal)}</div><div className="text-sm text-ink-soft">por mês · {rec.prazo_meses} meses</div></div>
        <div className="mt-3 space-y-2">
          {rec.acoes.map((a: any) => (
            <div key={a.divida_id} className="flex items-center justify-between rounded-xl bg-mist px-3 py-2 text-sm">
              <div><div className="font-semibold">{a.nome}</div><div className="text-xs text-ink-soft">{nomeAcao(a.acao)}{a.desconto_pct > 0 && ` · ${pct(a.desconto_pct)} de desconto`}</div></div>
              <div className="font-bold text-right">{a.acao === 'quitar' ? brl(a.usa_caixa) : a.acao === 'manter' ? `${brl(a.parcela)}/mês juros` : `${brl(a.parcela)}/mês`}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-xl bg-ok-soft p-2 text-ok"><div>reserva</div><div className="font-bold">{brl(rec.reserva)}</div></div>
          <div className="rounded-xl bg-mist p-2"><div className="text-ink-soft">custo total</div><div className="font-bold">{brl(rec.custo_total)}</div></div>
          <div className="rounded-xl bg-mist p-2"><div className="text-ink-soft">nome limpo</div><div className="font-bold flex items-center justify-center gap-1"><CheckCircle2 className="h-3 w-3 text-ok" /> sim</div></div>
        </div>
        {onEscolher && <button className="btn-primary w-full mt-3" onClick={() => onEscolher(rec.id)}>Quero esse plano</button>}
      </Card>
      {outros.length > 0 && (
        <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-1 px-1">
          {outros.map((c) => (
            <button key={c.id} onClick={() => onEscolher?.(c.id)} className="card min-w-[160px] p-3 text-left active:scale-[0.98] transition">
              {c.rotulos.map((r: string) => ROTULO[r] && <Rotulo key={r} tom={ROTULO[r].tom}>{ROTULO[r].txt}</Rotulo>)}
              <div className="mt-2 text-lg font-extrabold">{brl(c.comprometimento_mensal)}<span className="text-xs font-medium text-ink-soft">/mês</span></div>
              <div className="text-xs text-ink-soft">{c.prazo_meses} meses · total {brl(c.custo_total)}</div>
            </button>
          ))}
        </div>
      )}
      {d.plano_padrao && (
        <div className="rounded-xl border border-dashed border-line px-3 py-2 text-xs text-ink-soft">
          Renegociação padrão: {d.plano_padrao.prazo}x de <b>{brl(d.plano_padrao.parcela)}</b> — não caberia em {d.plano_padrao.meses_em_que_nao_cabe?.length} dos últimos 12 meses.
        </div>
      )}
    </div>
  )
}

export function Acordo({ d }: { d: any }) {
  const total = d.prazo || 1
  const pagas = d.pagas ?? 0
  return (
    <Card>
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Seu acordo</div>
        <Rotulo tom={d.status === 'quitado' ? 'ok' : 'blue'}>{d.status}</Rotulo>
      </div>
      <div className="mt-1 flex items-baseline gap-2"><div className="text-2xl font-extrabold">{brl(d.parcela)}</div><div className="text-sm text-ink-soft">por mês</div></div>
      <div className="mt-2"><Barra valor={pagas} max={total} tom="ok" /><div className="mt-1 flex justify-between text-xs text-ink-soft"><span>{pagas} de {total} parcelas</span><span>saldo {brl(d.saldo_devedor)}</span></div></div>
      {(d.quitacoes ?? []).map((q: any) => (
        <div key={q.nome} className="mt-2 flex items-center gap-2 text-sm text-ok"><CheckCircle2 className="h-4 w-4" /> {q.nome} quitado por {brl(q.valor_pago)}</div>
      ))}
      <div className="mt-2 space-y-1">
        {(d.componentes ?? []).map((c: any) => (
          <div key={c.nome} className="flex items-center justify-between text-sm"><span className={c.status === 'quitado' ? 'line-through text-ink-soft' : ''}>{c.nome}</span><span className="text-ink-soft">{c.prazo}x {brl(c.parcela)}</span></div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
        <span>{d.proximo_vencimento ? `próximo: ${dataBR(d.proximo_vencimento)}` : 'sem vencimentos'}</span>
        <span>respiros: {d.respiros_usados ?? 0}/{d.respiros_max ?? 0} usados</span>
      </div>
    </Card>
  )
}

export function Amortizacao({ d }: { d: any }) {
  return (
    <Card>
      <div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Usar o dinheiro extra</div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-xl bg-mist p-2"><div className="text-xs text-ink-soft">amortiza</div><div className="font-bold">{brl(d.valor_amortizado)}</div></div>
        <div className="rounded-xl bg-ok-soft p-2 text-ok"><div className="text-xs">reserva</div><div className="font-bold">{brl(d.reserva_sugerida)}</div></div>
        <div className="rounded-xl bg-mist p-2"><div className="text-xs text-ink-soft">abate do saldo</div><div className="font-bold">{brl(d.abatimento_no_saldo)}</div></div>
        <div className="rounded-xl bg-mist p-2"><div className="text-xs text-ink-soft">parcelas a menos</div><div className="font-bold">{d.parcelas_a_menos}</div></div>
      </div>
    </Card>
  )
}

export function Guardrail({ camada, tipo }: { camada: string; tipo: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-itau-blue-soft px-3 py-2 text-xs text-itau-blue">
      <ShieldCheck className="h-4 w-4" /> Guardrail de {camada}: <b>{tipo.replace(/_/g, ' ')}</b>{camada === 'entrada' && ' · modelo não foi chamado'}
    </div>
  )
}

export function BlocoCard({ bloco, onEscolher }: { bloco: Bloco; onEscolher?: (id: string) => void }) {
  switch (bloco.tipo) {
    case 'raio_x': return <RaioX d={bloco.dados} />
    case 'capacidade': return <Capacidade d={bloco.dados} />
    case 'cenarios': return <Cenarios d={bloco.dados} onEscolher={onEscolher} />
    case 'acordo': return <Acordo d={bloco.dados} />
    case 'amortizacao': return <Amortizacao d={bloco.dados} />
    default: return null // prioridades/planos consolidados: o texto do agente já cobre
  }
}
