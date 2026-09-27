import { ArrowRight, Barcode, ChevronRight, CreditCard, PiggyBank, QrCode, RefreshCw, ShoppingBag, Sparkles, WifiOff } from 'lucide-react'
import type { Resposta } from '../types'
import { Card, HeaderItau, Tile } from '../components/ui'

const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })

/* Home do banco com a MENSAGEM PROATIVA da zera.ai (só aparece se a API não devolveu `silent`) e o acordo, se houver. */
export function Home({ proativa, acordo, erro, onAbrir, onRecarregar }: { proativa: Resposta | null | undefined; acordo: any | null; erro: string | null; onAbrir: () => void; onRecarregar: () => void }) {
  const carregando = proativa === undefined
  const mostrar = !!proativa && !proativa.silent && proativa.response_type === 'PROACTIVE_MESSAGE'
  return (
    <div className="h-full bg-mist flex flex-col">
      <HeaderItau />
      <div className="flex-1 overflow-y-auto px-4 pb-8">
        <div className="mt-5 flex items-center justify-between"><div className="font-bold">Meu Itaú</div><span className="text-ink-soft">👁</span></div>
        <div className="mt-4 grid grid-cols-5 gap-2">
          <Tile icon={<QrCode className="h-5 w-5" />}>Pix e transferir</Tile>
          <Tile icon={<Barcode className="h-5 w-5" />}>Pagar</Tile>
          <Tile icon={<CreditCard className="h-5 w-5" />}>Cartão virtual</Tile>
          <Tile icon={<PiggyBank className="h-5 w-5" />}>Cofrinhos</Tile>
          <Tile icon={<ShoppingBag className="h-5 w-5" />}>Shop</Tile>
        </div>

        {carregando && (
          <div className="mt-4 rounded-3xl bg-white border border-line p-4 animate-pulse" aria-busy="true" aria-label="Carregando">
            <div className="h-3 w-24 rounded bg-mist" /><div className="mt-3 h-5 w-3/4 rounded bg-mist" /><div className="mt-2 h-4 w-full rounded bg-mist" /><div className="mt-4 h-8 w-32 rounded-full bg-mist" />
          </div>
        )}
        {erro && !carregando && (
          <div className="mt-4 rounded-2xl bg-danger-soft p-3 text-xs text-danger flex items-center gap-2"><WifiOff className="h-4 w-4 shrink-0" /> {erro}<button onClick={onRecarregar} className="ml-auto inline-flex items-center gap-1 font-bold"><RefreshCw className="h-3 w-3" /> tentar de novo</button></div>
        )}
        {mostrar && (
          <button onClick={onAbrir} className="mt-4 w-full text-left rounded-3xl bg-gradient-to-br from-[#FF8A2A] to-itau-orange p-4 text-white shadow-[0_10px_30px_rgba(236,112,0,0.35)] active:scale-[0.99] transition rise">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide opacity-90"><Sparkles className="h-4 w-4" /> zera.ai</div>
            <div className="mt-1 text-xl font-extrabold leading-tight">{proativa!.content.title}</div>
            <div className="mt-1 text-sm opacity-90">{proativa!.content.description}</div>
            {proativa!.benefit?.monthly_difference && <div className="mt-2 text-sm font-semibold">Até {brl(proativa!.benefit.monthly_difference)} a menos por mês</div>}
            <div className="mt-3 inline-flex items-center gap-1 rounded-full bg-white/20 px-3 py-1.5 text-sm font-bold">{proativa!.cta} <ArrowRight className="h-4 w-4" /></div>
          </button>
        )}
        {proativa?.silent && !acordo && (
          <div className="mt-4 rounded-2xl border border-dashed border-line p-3 text-xs text-ink-soft">zera.ai em silêncio: {proativa.reason} <span className="block mt-1">{Object.entries(proativa.checks ?? {}).filter(([, v]) => !v).map(([k]) => k).join(', ') || 'todas as pré-condições ok'}</span></div>
        )}

        <Card className="mt-4">
          <div className="flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><span className="h-6 w-6 rounded bg-itau-blue text-white text-[9px] grid place-items-center font-bold">cc</span> Conta corrente</div><ChevronRight className="h-4 w-4 text-ink-soft" /></div>
          <div className="mt-3 text-sm text-ink-soft">Saldo</div><div className="font-bold tracking-widest">••••</div>
          {acordo && <div className="mt-3 border-t border-line pt-3"><div className="text-sm text-ink-soft">zera.ai · sua nova parcela</div><div className="font-bold">{brl(acordo.parcela)}/mês · {acordo.pagas} de {acordo.prazo} pagas · próximo {acordo.proximo_vencimento}</div>
            <button onClick={onAbrir} className="mt-2 text-itau-orange font-bold text-sm">Acompanhar</button></div>}
        </Card>
        {!carregando && !mostrar && !acordo && <button onClick={onAbrir} className="mt-4 card w-full p-4 text-left flex items-center justify-between"><div><div className="font-bold">zera.ai</div><div className="text-xs text-ink-soft">Ver formas de pagar menos por mês</div></div><ChevronRight className="h-5 w-5 text-ink-soft" /></button>}
      </div>
    </div>
  )
}
