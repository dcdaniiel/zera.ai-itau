import { BarChart3, Building2, CalendarDays, Bell, Lightbulb, Lock, ChevronRight, CreditCard, Landmark, PiggyBank, QrCode, ShoppingBag, Barcode } from 'lucide-react'
import { useState } from 'react'
import { Card, HeaderItau, Tile, Toggle } from '../components/ui'

/* Tela 1 — home do banco (fundo) + bottom sheet "Conheça a zera.ai" */
export function Onboarding({ onAtivar, onDepois }: { onAtivar: () => void; onDepois: () => void }) {
  return (
    <div className="relative h-full bg-mist">
      <HeaderItau />
      <div className="px-4 pt-6 opacity-60 pointer-events-none select-none">
        <div className="flex items-center justify-between"><div className="font-bold">Meu Itaú</div><span className="text-ink-soft">👁</span></div>
        <div className="mt-4 grid grid-cols-5 gap-2">
          <Tile icon={<QrCode className="h-5 w-5" />}>Pix e transferir</Tile>
          <Tile icon={<Barcode className="h-5 w-5" />}>Pagar</Tile>
          <Tile icon={<CreditCard className="h-5 w-5" />}>Cartão virtual</Tile>
          <Tile icon={<PiggyBank className="h-5 w-5" />}>Cofrinhos</Tile>
          <Tile icon={<ShoppingBag className="h-5 w-5" />}>Shop</Tile>
        </div>
        <Card className="mt-4">
          <div className="flex items-center justify-between"><div className="flex items-center gap-2 font-semibold"><span className="h-6 w-6 rounded bg-itau-blue text-white text-[9px] grid place-items-center font-bold">cc</span> Conta corrente</div><ChevronRight className="h-4 w-4 text-ink-soft" /></div>
          <div className="mt-3 text-sm text-ink-soft">Saldo</div><div className="font-bold tracking-widest">••••</div>
          <div className="mt-3 border-t border-line pt-3 flex items-center justify-between text-sm"><span>Limite disponível</span><span className="tracking-widest">••••</span></div>
        </Card>
      </div>
      <div className="absolute inset-0 bg-black/30" />
      <div className="absolute inset-x-0 bottom-0 rounded-t-3xl bg-[#FBF7F3] px-5 pt-3 pb-6 rise shadow-[0_-10px_40px_rgba(0,0,0,0.2)]">
        <div className="mx-auto h-1.5 w-12 rounded-full bg-line" />
        <div className="mt-4 chip bg-itau-orange-soft text-itau-orange">Conheça a zera.ai</div>
        <div className="mt-3 flex items-start gap-3">
          <div className="flex-1">
            <h1 className="text-[26px] leading-tight font-extrabold">Uma aliada para organizar suas dívidas</h1>
            <p className="mt-2 text-[15px] text-ink-soft leading-snug">A zera.ai analisa sua vida financeira, identifica oportunidades e recomenda caminhos que cabem no seu orçamento.</p>
          </div>
          <div className="h-24 w-20 shrink-0 rounded-2xl bg-itau-orange-soft grid place-items-center"><BarChart3 className="h-9 w-9 text-itau-orange" /></div>
        </div>
        <div className="mt-4 card bg-[#F6F1EC] border-transparent p-4 grid grid-cols-3 divide-x divide-line">
          <div className="pr-2"><Tile icon={<BarChart3 className="h-5 w-5" />}>Entende seu momento financeiro</Tile></div>
          <div className="px-2"><Tile icon={<CalendarDays className="h-5 w-5" />}>Identifica boas oportunidades</Tile></div>
          <div className="pl-2"><Tile icon={<Lightbulb className="h-5 w-5" />}>Sugere caminhos para organizar suas dívidas</Tile></div>
        </div>
        <button className="btn-primary w-full mt-5 rounded-2xl py-4 text-base" onClick={onAtivar}>Quero ativar agora</button>
        <button className="w-full mt-3 py-2 text-itau-orange font-bold" onClick={onDepois}>Agora não</button>
      </div>
    </div>
  )
}

/* Tela 2 — preferências/consentimento (LGPD): o cliente escolhe o que a zera.ai pode fazer */
const ITENS = [
  { id: 'analisar', icon: <BarChart3 className="h-5 w-5" />, titulo: 'Analisar minha vida financeira', desc: 'Entender suas movimentações, contas e compromissos para ter uma visão do seu momento financeiro.' },
  { id: 'momentos', icon: <CalendarDays className="h-5 w-5" />, titulo: 'Identificar momentos importantes', desc: 'Perceber mudanças que podem afetar seu orçamento, como novos compromissos ou entradas extras.' },
  { id: 'recomendar', icon: <Lightbulb className="h-5 w-5" />, titulo: 'Recomendar caminhos', desc: 'Sugerir alternativas para organizar suas dívidas e aproveitar oportunidades quando fizer sentido para você.' },
  { id: 'avisar', icon: <Bell className="h-5 w-5" />, titulo: 'Me avisar proativamente', desc: 'Entrar em contato quando identificar algo que pode ser importante para você, mesmo que você não tenha iniciado a conversa.' },
]

export function Preferencias({ onSalvar, onVoltar }: { onSalvar: (prefs: Record<string, boolean>) => void; onVoltar: () => void }) {
  const [prefs, setPrefs] = useState<Record<string, boolean>>({ analisar: true, momentos: true, recomendar: true, avisar: true })
  return (
    <div className="h-full bg-mist flex flex-col">
      <HeaderItau />
      <div className="flex-1 overflow-y-auto px-4 pb-28">
        <button onClick={onVoltar} className="mt-3 -ml-1 h-9 w-9 grid place-items-center rounded-full active:bg-line" aria-label="Voltar"><ChevronRight className="h-5 w-5 rotate-180" /></button>
        <h1 className="text-[26px] leading-tight font-extrabold">Escolha como a zera.ai pode te ajudar</h1>
        <p className="mt-2 text-[15px] text-ink-soft leading-snug">A zera.ai ajuda você a organizar suas dívidas e encontrar caminhos que caibam no seu orçamento.</p>
        <div className="mt-4 space-y-3">
          {ITENS.map((it) => (
            <Card key={it.id} className="flex items-start gap-3">
              <div className="h-12 w-12 shrink-0 rounded-2xl bg-itau-orange-soft text-itau-orange grid place-items-center">{it.icon}</div>
              <div className="flex-1"><div className="font-bold">{it.titulo}</div><div className="text-[13px] text-ink-soft leading-snug mt-0.5">{it.desc}</div></div>
              <Toggle on={prefs[it.id]} onChange={(v) => setPrefs({ ...prefs, [it.id]: v })} label={it.titulo} />
            </Card>
          ))}
        </div>
        <div className="mt-6 font-bold">Amplie minha visão financeira</div>
        <Card className="mt-3 flex items-center gap-3">
          <div className="h-12 w-12 shrink-0 rounded-2xl bg-itau-orange-soft text-itau-orange grid place-items-center"><Building2 className="h-5 w-5" /></div>
          <div className="flex-1"><div className="font-bold">Incluir outras instituições</div><div className="text-[13px] text-ink-soft leading-snug mt-0.5">Permite que a zera.ai considere seus dados de outras instituições financeiras pelo Open Finance.</div></div>
          <ChevronRight className="h-5 w-5 text-ink-soft" />
        </Card>
        <div className="mt-3 flex items-start gap-3 px-1">
          <div className="h-10 w-10 shrink-0 rounded-full bg-mist border border-line grid place-items-center"><Lock className="h-4 w-4 text-ink-soft" /></div>
          <div><div className="font-bold text-sm">Você decide antes de qualquer ação</div><div className="text-[13px] text-ink-soft leading-snug">A zera.ai analisa e recomenda. Pagamentos, contratações e acordos só acontecem com a sua confirmação.</div></div>
        </div>
        <div className="mt-3 flex items-center gap-2 px-1 text-[12px] text-ink-soft"><Landmark className="h-3.5 w-3.5" /> Seus dados ficam no banco; a zera.ai só recebe resumos.</div>
      </div>
      <div className="absolute inset-x-0 bottom-0 bg-mist/95 backdrop-blur px-4 pt-3 pb-6">
        <button className="btn-primary w-full rounded-2xl py-4 text-base" onClick={() => onSalvar(prefs)}>Salvar preferências</button>
      </div>
    </div>
  )
}
