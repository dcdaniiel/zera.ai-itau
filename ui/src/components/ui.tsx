/* Peças visuais no estilo do app Itaú (design de referência): header laranja, tiles brancos, cards, toggles,
   barra inferior, botão flutuante com a faísca da zera.ai e o balão proativo. */

import type { ReactNode } from 'react'
import { ArrowLeftRight, Bell, ChevronLeft, ChevronRight, Gift, House, LayoutGrid, List, MessageSquare, Search, X } from 'lucide-react'

export const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
export const brl0 = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })
export const pct = (v: number) => `${(v * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`
export const mesCurto = (m: string) => {
  const [y, mm] = m.split('-')
  return ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(mm) - 1] + '/' + y.slice(2)
}
export const dataBR = (iso: string) => { const [y, m, d] = iso.split('-'); return `${d}/${m}/${y}` }
export const dataLonga = (iso: string) => { const [y, m, d] = iso.split('-'); return `${Number(d)} de ${['jan.', 'fev.', 'mar.', 'abr.', 'mai.', 'jun.', 'jul.', 'ago.', 'set.', 'out.', 'nov.', 'dez.'][Number(m) - 1]} de ${y}` }
export const iniciais = (nome: string) => nome.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || 'CL'

/** Faísca de 4 pontas — o ícone da zera.ai (design de referência). */
export function Faisca({ className = 'h-6 w-6', cor = '#EC7000' }: { className?: string; cor?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path fill={cor} d="M12 1.5c.6 4.9 3.6 7.9 8.5 8.5v4c-4.9.6-7.9 3.6-8.5 8.5h-4C7.4 17.6 4.4 14.6 0 14v-4c4.9-.6 7.9-3.6 8.5-8.5h3.5z" transform="translate(1.75 0) scale(0.85)" />
    </svg>
  )
}

export function HeaderItau({ onBack, titulo, badge, nome = 'Cliente' }: { onBack?: () => void; titulo?: string; badge?: ReactNode; nome?: string }) {
  return (
    <div className="bg-itau-orange text-white px-4 pt-3 pb-3">
      <div className="flex items-center gap-3">
        {onBack ? (
          <button onClick={onBack} aria-label="Voltar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-white/20"><ChevronLeft /></button>
        ) : (
          <div className="h-10 w-10 rounded-full bg-white text-itau-orange font-bold grid place-items-center text-sm">{iniciais(nome)}</div>
        )}
        {titulo ? <div className="font-bold text-base flex-1">{titulo}</div> : (
          <div className="chip bg-white/20 text-white"><span className="h-4 w-4 rounded-full bg-white/90 text-itau-orange grid place-items-center text-[10px] font-black">$</span> Nível 5</div>
        )}
        <div className="ml-auto flex items-center gap-4">
          {badge}
          <Search className="h-5 w-5" /><span className="relative"><Bell className="h-5 w-5" /><span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-red-500" /></span><MessageSquare className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

export function Tile({ icon, children, quadrado = false }: { icon: ReactNode; children: ReactNode; quadrado?: boolean }) {
  return (
    <div className="flex flex-col items-center text-center gap-2">
      <div className={quadrado ? 'h-[60px] w-[60px] rounded-2xl bg-white text-ink grid place-items-center shadow-[0_2px_10px_rgba(27,27,31,0.06)]' : 'h-12 w-12 rounded-2xl bg-itau-orange-soft text-itau-orange grid place-items-center'}>{icon}</div>
      <div className="text-[12px] leading-snug text-ink font-medium">{children}</div>
    </div>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${on ? 'bg-itau-orange' : 'bg-line'}`}>
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-6' : 'left-1'}`} />
    </button>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`card p-4 ${className}`}>{children}</div>
}

export function Rotulo({ children, tom = 'orange' }: { children: ReactNode; tom?: 'orange' | 'ok' | 'warn' | 'blue' | 'danger' | 'grey' }) {
  const cls = { orange: 'bg-itau-orange-soft text-itau-orange', ok: 'bg-ok-soft text-ok', warn: 'bg-warn-soft text-warn', blue: 'bg-itau-blue-soft text-itau-blue', danger: 'bg-danger-soft text-danger', grey: 'bg-mist text-ink-soft' }[tom]
  return <span className={`chip ${cls}`}>{children}</span>
}

export function Barra({ valor, max, tom = 'orange' }: { valor: number; max: number; tom?: 'orange' | 'ok' | 'grey' }) {
  const w = Math.max(4, Math.min(100, (valor / max) * 100))
  const cor = { orange: 'bg-itau-orange', ok: 'bg-ok', grey: 'bg-line' }[tom]
  return <div className="h-2 w-full rounded-full bg-mist overflow-hidden"><div className={`h-full rounded-full ${cor}`} style={{ width: `${w}%` }} /></div>
}

/** Barra inferior do app (Home ativo). */
export function BottomNav() {
  const item = (icon: ReactNode, label: string) => <div className="flex flex-col items-center gap-1 text-[11px] text-ink-soft">{icon}<span>{label}</span></div>
  return (
    <div className="shrink-0 bg-white border-t border-line px-4 pt-2 pb-4 grid grid-cols-5 items-end">
      <div className="flex justify-center"><div className="h-12 w-12 rounded-xl bg-itau-blue text-white grid place-items-center"><House className="h-5 w-5" /></div></div>
      {item(<List className="h-5 w-5" />, 'Extrato')}
      {item(<ArrowLeftRight className="h-5 w-5" />, 'Pagamentos')}
      {item(<Gift className="h-5 w-5" />, 'Pra você')}
      {item(<LayoutGrid className="h-5 w-5" />, 'Menu')}
    </div>
  )
}

/** Botão flutuante da zera.ai (faísca) + balão proativo ancorado nele. */
export function FabZera({ onClick, balao }: { onClick: () => void; balao?: { titulo: string; descricao: string; cta: string; onCta: () => void; onFechar: () => void; onConversar?: () => void } }) {
  return (
    <>
      {balao && (
        <div className="absolute right-4 bottom-[7.25rem] z-20 w-[268px] rounded-3xl bg-[#FBF6F1] p-4 shadow-[0_12px_40px_rgba(27,27,31,0.18)] rise" role="dialog" aria-label={balao.titulo}>
          <button onClick={balao.onFechar} aria-label="Fechar" className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full text-ink-soft active:bg-black/5"><X className="h-4 w-4" /></button>
          <div className="flex items-center gap-2 pr-6"><Faisca className="h-5 w-5" /><div className="font-bold text-[15px]">{balao.titulo}</div></div>
          <div className="mt-1 text-[13px] text-ink-soft leading-snug">{balao.descricao}</div>
          <div className="mt-3 flex items-center gap-3">
            <button onClick={balao.onCta} className="inline-flex items-center gap-1 rounded-full bg-white px-4 py-2 text-[13px] font-bold text-itau-orange shadow-sm active:scale-95 transition">{balao.cta} <ChevronRight className="h-4 w-4" /></button>
            {balao.onConversar && <button onClick={balao.onConversar} className="text-[13px] font-bold text-ink-soft underline-offset-2 hover:underline">Conversar</button>}
          </div>
          <span className="absolute -bottom-2 right-9 h-4 w-4 rotate-45 bg-[#FBF6F1]" />
        </div>
      )}
      <button onClick={onClick} aria-label="Abrir zera.ai" className="absolute right-4 bottom-[4.5rem] z-20 h-14 w-14 rounded-full bg-white border-2 border-itau-orange grid place-items-center shadow-[0_8px_24px_rgba(236,112,0,0.35)] active:scale-95 transition">
        <Faisca className="h-6 w-6" />
      </button>
    </>
  )
}
