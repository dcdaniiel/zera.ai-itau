/* Peças visuais no estilo do app Itaú: header laranja, cards brancos, tiles de ícone, toggles. */

import type { ReactNode } from 'react'
import { Bell, ChevronLeft, MessageSquare, Search } from 'lucide-react'

export const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
export const pct = (v: number) => `${(v * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`
export const mesCurto = (m: string) => {
  const [y, mm] = m.split('-')
  return ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(mm) - 1] + '/' + y.slice(2)
}
export const dataBR = (iso: string) => { const [y, m, d] = iso.split('-'); return `${d}/${m}/${y}` }

export function HeaderItau({ onBack, titulo, badge }: { onBack?: () => void; titulo?: string; badge?: ReactNode }) {
  return (
    <div className="bg-itau-orange text-white px-4 pt-3 pb-3">
      <div className="flex items-center gap-3">
        {onBack ? (
          <button onClick={onBack} aria-label="Voltar" className="h-10 w-10 -ml-2 grid place-items-center rounded-full active:bg-white/20"><ChevronLeft /></button>
        ) : (
          <div className="h-10 w-10 rounded-full bg-white text-itau-orange font-bold grid place-items-center text-sm">CL</div>
        )}
        {titulo ? <div className="font-bold text-base flex-1">{titulo}</div> : (
          <div className="chip bg-white/20 text-white"><span className="h-4 w-4 rounded-full bg-white/90 text-itau-orange grid place-items-center text-[10px] font-black">$</span> Nível 5</div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {badge}
          <Search className="h-5 w-5" /><span className="relative"><Bell className="h-5 w-5" /><span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-red-500" /></span><MessageSquare className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

export function Tile({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center gap-2">
      <div className="h-12 w-12 rounded-2xl bg-itau-orange-soft text-itau-orange grid place-items-center">{icon}</div>
      <div className="text-[13px] leading-snug text-ink font-medium">{children}</div>
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
