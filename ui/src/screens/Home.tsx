import { Barcode, ChevronRight, CreditCard, PiggyBank, QrCode, RefreshCw, ShoppingBag, WifiOff } from 'lucide-react'
import type { Resposta } from '../types'
import { BottomNav, FabZera, HeaderItau, Tile } from '../components/ui'

/* Tela do trigger — home do banco (design de referência) com o balão proativo da zera.ai ancorado no botão flutuante.
   O balão só aparece se a API devolveu PROACTIVE_MESSAGE (permissão ∧ gatilho ∧ oportunidade ∧ benefício validado);
   o botão flutuante fica sempre disponível: recusar a proatividade não impede pedir ajuda (quadro item 18). */
export function Home({ nome, proativa, acordo, acordos = [], erro, onAbrir, onAbrirBotao, onConversar, onDispensar, onRecarregar }: {
  nome: string; proativa: Resposta | null | undefined; acordo: any | null; acordos?: any[]; erro: string | null
  onAbrir: () => void; onAbrirBotao: () => void; onConversar: () => void; onDispensar: () => void; onRecarregar: () => void
}) {
  const carregando = proativa === undefined
  const mostrar = !!proativa && !proativa.silent && proativa.response_type === 'PROACTIVE_MESSAGE'
  return (
    <div className="h-full bg-mist flex flex-col relative">
      <HeaderItau nome={nome} />
      <div className="flex-1 overflow-y-auto px-4 pb-6">
        <div className="mt-5 flex items-center justify-between"><div className="font-bold text-[17px]">Meu Itaú</div><span className="text-ink-soft" aria-hidden="true">﹀﹀</span></div>
        <div className="mt-4 grid grid-cols-5 gap-2">
          <Tile quadrado icon={<QrCode className="h-6 w-6" />}>Pix e transferir</Tile>
          <Tile quadrado icon={<Barcode className="h-6 w-6" />}>Pagar</Tile>
          <Tile quadrado icon={<CreditCard className="h-6 w-6" />}>Cartão virtual</Tile>
          <Tile quadrado icon={<PiggyBank className="h-6 w-6" />}>Cofrinhos</Tile>
          <Tile quadrado icon={<ShoppingBag className="h-6 w-6" />}>Itaú Shop</Tile>
        </div>

        {erro && !carregando && (
          <div className="mt-4 rounded-2xl bg-danger-soft p-3 text-xs text-danger flex items-center gap-2"><WifiOff className="h-4 w-4 shrink-0" /> {erro}<button onClick={onRecarregar} className="ml-auto inline-flex items-center gap-1 font-bold"><RefreshCw className="h-3 w-3" /> tentar de novo</button></div>
        )}

        <div className="card mt-5 p-4">
          <div className="flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><span className="h-7 w-7 rounded-lg bg-itau-blue text-white text-[9px] grid place-items-center font-bold">itaú</span> Conta corrente</div><ChevronRight className="h-5 w-5 text-ink-soft" /></div>
          <div className="mt-4 text-[15px]">Saldo</div><div className="mt-1 text-ink-soft tracking-[0.2em]">••••</div>
          {acordo && (acordos.length > 1
            ? <div className="mt-3 rounded-2xl bg-itau-orange-soft/70 p-3 text-[13px]"><span className="font-semibold text-itau-orange">zera.ai</span> · {acordos.length} acordos · {acordos.reduce((t: number, a: any) => t + a.parcela, 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}/mês no total</div>
            : <div className="mt-3 rounded-2xl bg-itau-orange-soft/70 p-3 text-[13px]"><span className="font-semibold text-itau-orange">zera.ai</span> · nova parcela {acordo.parcela.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}/mês · {acordo.pagas} de {acordo.prazo} pagas</div>)}
          <div className="mt-4 border-t border-line pt-3 flex items-center justify-between text-[15px]"><span>Limite disponível</span><span className="flex items-center gap-2 text-ink-soft tracking-[0.2em]">•••• <ChevronRight className="h-4 w-4" /></span></div>
        </div>

        <div className="card mt-4 p-4">
          <div className="flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><span className="h-6 w-6 rounded-full bg-gradient-to-br from-[#FFB347] to-itau-orange" /> Cartão de crédito final ••••</div><ChevronRight className="h-4 w-4 text-ink-soft" /></div>
          <div className="mt-4 text-[15px]">Fatura aberta</div><div className="mt-1 text-ink-soft tracking-[0.2em]">••••</div>
          <div className="mt-2 font-semibold text-[15px]">Melhor data de compras: 03 out</div>
          <div className="mt-4 border-t border-line pt-3 flex items-center justify-between text-[15px]"><span>Limite disponível</span><span className="flex items-center gap-2 text-ink-soft tracking-[0.2em]">•••• <ChevronRight className="h-4 w-4" /></span></div>
        </div>

        {carregando && <div className="mt-4 text-center text-[11px] text-ink-soft" aria-busy="true">zera.ai avaliando se há algo útil para te dizer…</div>}
        {proativa?.silent && !acordo && !carregando && (
          proativa.checks?.required_context_available === false && /renda/i.test(proativa.reason ?? '')
            ? <button onClick={onAbrirBotao} className="mt-4 w-full text-left rounded-2xl border border-itau-orange/40 bg-itau-orange-soft/40 p-3 text-[12px]">
                <b className="text-itau-orange">zera.ai</b> ainda não te procurou: a sua renda não aparece no extrato e, sem ela, não calcula nada — nem promete.
                <span className="block mt-1 font-semibold">Toque aqui (ou na faísca) e me diga quanto entra por mês. A partir daí eu te aviso quando houver algo útil.</span>
              </button>
            : <div className="mt-4 rounded-2xl border border-dashed border-line p-3 text-[11px] text-ink-soft">zera.ai em silêncio: {proativa.reason}<span className="block mt-1">{Object.entries(proativa.checks ?? {}).filter(([, v]) => !v).map(([k]) => k).join(', ') || 'todas as pré-condições ok'}</span></div>
        )}
        <div className="h-16" />
      </div>
      <FabZera onClick={onAbrirBotao} balao={mostrar ? { titulo: proativa!.content.title, descricao: proativa!.content.description, cta: proativa!.cta ?? 'Ver', onCta: onAbrir, onFechar: onDispensar, onConversar } : undefined} />
      <BottomNav />
    </div>
  )
}
