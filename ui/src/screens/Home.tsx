import { ArrowRight, BellRing, CalendarClock, Sparkles, TrendingDown } from 'lucide-react'
import type { EstadoDemo } from '../types'
import { Card, HeaderItau, Rotulo, brl, dataBR } from '../components/ui'
import { RAIO_X } from '../mock'

/* Tela 3 — home da zera.ai: gatilho proativo (anomalia) + resumo das dívidas + acordo */
export function Home({ estado, onAbrirChat }: { estado: EstadoDemo; onAbrirChat: (mensagemInicial?: string) => void }) {
  const gat = estado.gatilhos[0]
  const raio = RAIO_X.dados
  const acordo = estado.acordo
  return (
    <div className="h-full bg-mist flex flex-col">
      <HeaderItau />
      <div className="flex-1 overflow-y-auto px-4 pb-8">
        <div className="mt-5 flex items-center justify-between">
          <div><div className="text-sm text-ink-soft">Oi, Cleide</div><h1 className="text-2xl font-extrabold">zera.ai</h1></div>
          <Rotulo tom="grey">hoje {dataBR(estado.hoje)}</Rotulo>
        </div>

        {gat && (
          <button onClick={() => onAbrirChat()} className="mt-4 w-full text-left rounded-3xl bg-itau-orange p-4 text-white shadow-[0_10px_30px_rgba(236,112,0,0.35)] active:scale-[0.99] transition rise">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide opacity-90">
              {gat.tipo === 'dinheiro_extra' ? <Sparkles className="h-4 w-4" /> : gat.tipo === 'risco_parcela' ? <CalendarClock className="h-4 w-4" /> : <BellRing className="h-4 w-4" />}
              {gat.tipo === 'dinheiro_extra' ? 'Entrou dinheiro extra' : gat.tipo === 'risco_parcela' ? 'Mês apertado à vista' : 'Antes de o nome sujar'}
            </div>
            <div className="mt-1 text-xl font-extrabold leading-tight">
              {gat.tipo === 'dinheiro_extra' && `Entrou ${brl(gat.valor ?? 0)} na sua conta`}
              {gat.tipo === 'risco_parcela' && `Sua parcela de ${brl(gat.parcela ?? 0)} vence em 3 dias`}
              {gat.tipo === 'pre_negativacao' && 'Vamos ver um plano que cabe?'}
            </div>
            <div className="mt-1 text-sm opacity-90">
              {gat.tipo === 'dinheiro_extra' && 'Antes de ele sumir no vermelho, veja o melhor jeito de usar para limpar seu nome.'}
              {gat.tipo === 'risco_parcela' && `A sobra prevista é ${brl(gat.sobra_prevista ?? 0)}. Você tem respiro no acordo.`}
            </div>
            <div className="mt-3 inline-flex items-center gap-1 rounded-full bg-white/20 px-3 py-1.5 text-sm font-bold">Falar com a zera <ArrowRight className="h-4 w-4" /></div>
          </button>
        )}

        {acordo ? (
          <Card className="mt-4">
            <div className="flex items-center justify-between"><div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Seu acordo</div><Rotulo tom="ok">{acordo.status}</Rotulo></div>
            <div className="mt-1 text-2xl font-extrabold">{brl(acordo.parcela)}<span className="text-sm font-medium text-ink-soft"> /mês</span></div>
            <div className="mt-1 text-sm text-ink-soft">{acordo.pagas} de {acordo.prazo} parcelas · próximo {acordo.proximo_vencimento ? dataBR(acordo.proximo_vencimento) : '—'} · respiros {acordo.respiros_usados}/{acordo.respiros_max}</div>
          </Card>
        ) : (
          <Card className="mt-4">
            <div className="flex items-center justify-between"><div className="text-xs font-semibold text-ink-soft uppercase tracking-wide">Suas dívidas</div><Rotulo tom="danger"><TrendingDown className="h-3 w-3" /> {brl(raio.custo_total_mensal)}/mês de juros</Rotulo></div>
            <div className="mt-1 text-2xl font-extrabold">{brl(raio.total_dividas)}</div>
            <div className="mt-2 space-y-1 text-sm">
              {raio.dividas.map((d: any) => <div key={d.divida_id} className="flex justify-between"><span>{d.nome}</span><span className="text-ink-soft">{brl(d.saldo)}</span></div>)}
            </div>
          </Card>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3">
          <button className="card p-4 text-left active:scale-[0.98] transition" onClick={() => onAbrirChat('quanto eu devo?')}><div className="font-bold">Quanto eu devo?</div><div className="text-xs text-ink-soft mt-1">Raio-X com prioridade</div></button>
          <button className="card p-4 text-left active:scale-[0.98] transition" onClick={() => onAbrirChat('quero ver os cenários que cabem no meu mês')}><div className="font-bold">O que cabe no meu mês</div><div className="text-xs text-ink-soft mt-1">Quitar, renegociar, manter</div></button>
        </div>
        <div className="mt-6 text-center text-xs text-ink-soft">Você decide antes de qualquer ação. A zera.ai analisa e recomenda.</div>
      </div>
    </div>
  )
}
