import { ChevronRight, Database, RefreshCw, UserRound, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Faisca, brl0 } from '../components/ui'
import type { Clientes, PerfilResumo } from '../types'

/* Seleção de perfil — clientes REAIS da base do evento, escolhidos pelo segmento-alvo:
   BigQuery ML (k-means sobre `zera.features_cliente`) quando a API roda com ZERA_FONTE=bigquery, ou segmentação por
   regras sobre o export da própria base (modo local). O perfil mais típico do segmento recebe o nome da persona
   do produto ("Cleide"); os demais, pseudônimos determinísticos. Nenhum dado é sintético nem inventado no front. */
export function Perfis({ onEscolher }: { onEscolher: (p: PerfilResumo) => void }) {
  const [dados, setDados] = useState<Clientes | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  async function carregar() {
    setErro(null); setDados(null)
    try { setDados(await api.clientes()) } catch (e) { setErro(e instanceof Error ? e.message : 'API indisponível') }
  }
  useEffect(() => { carregar() }, [])

  const alvo = dados?.clusters.find((c) => c.cluster_alvo)
  const fonteTxt = dados?.fonte === 'bigquery' ? 'BigQuery · zera.perfis_demo (k-means, BigQuery ML)'
    : dados?.fonte === 'amostra' ? 'amostra real exportada do BigQuery (10 mil lançamentos) · segmentação por regras — suba a API com ZERA_FONTE=bigquery para o cluster k-means'
    : dados?.fonte === 'fixture' ? 'fixture de teste (NÃO use na demonstração)' : dados?.fonte
  return (
    <div className="h-full bg-[#FBF6F1] flex flex-col">
      <div className="px-5 pt-6 pb-3">
        <div className="flex items-center gap-2"><Faisca className="h-6 w-6" /><span className="font-bold text-ink-soft">zera.ai</span></div>
        <h1 className="mt-3 text-[24px] leading-tight font-extrabold">Escolha um perfil para a demonstração</h1>
        <p className="mt-2 text-[14px] text-ink-soft leading-snug">Clientes reais do segmento-alvo (endividamento: meses no vermelho, rotativo, parcelamentos). O mais típico do cluster aparece como “Cleide”, a persona do produto. Identidades são fictícias.</p>
      </div>
      <div className="flex-1 overflow-y-auto px-5 pb-8 space-y-3">
        {!dados && !erro && [0, 1, 2].map((i) => <div key={i} className="card p-4 animate-pulse h-24" aria-label="Carregando" />)}
        {erro && <div className="rounded-2xl bg-danger-soft p-3 text-xs text-danger flex items-center gap-2"><WifiOff className="h-4 w-4 shrink-0" /> {erro}<button onClick={carregar} className="ml-auto inline-flex items-center gap-1 font-bold"><RefreshCw className="h-3 w-3" /> tentar de novo</button></div>}
        {dados && (
          <div className="flex items-start gap-2 text-[11px] text-ink-soft"><Database className="h-3.5 w-3.5 shrink-0 mt-0.5" /><span>fonte: {fonteTxt}</span>
            {alvo && <span className="ml-auto shrink-0 chip bg-itau-blue-soft text-itau-blue">cluster-alvo {alvo.cluster} · {alvo.clientes} clientes</span>}</div>
        )}
        {dados?.perfis.map((p) => (
          <button key={p.cliente_id} onClick={() => onEscolher(p)} className={`card w-full text-left p-4 flex items-center gap-3 active:scale-[0.99] transition ${p.medoide ? 'border-itau-orange' : ''}`}>
            <div className={`h-11 w-11 shrink-0 rounded-full grid place-items-center ${p.medoide ? 'bg-itau-orange text-white' : 'bg-itau-blue-soft text-itau-blue'}`}><UserRound className="h-5 w-5" /></div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2"><span className="font-bold truncate">{p.nome}</span>
                <span className={`chip ${p.medoide ? 'bg-itau-orange-soft text-itau-orange' : 'bg-mist text-ink-soft'}`}>{p.persona ? 'fixture de teste' : p.medoide ? 'mais típico do segmento' : `cliente real${p.cluster != null ? ` · cluster ${p.cluster}` : ''}`}</span></div>
              <div className="mt-1 text-[12px] text-ink-soft truncate">{p.sinais || '—'}</div>
              <div className="mt-1 text-[12px] text-ink-soft">{p.renda_conhecida ? `renda ~${brl0(p.renda_mediana)}/mês` : 'renda não identificada (a zera.ai pergunta)'} · {p.qtd_dividas} dívida{p.qtd_dividas === 1 ? '' : 's'} · {brl0(p.total_dividas)}{p.fonte_dividas === 'derivada_extrato' ? ' (estimado do extrato)' : ''}</div>
            </div>
            <ChevronRight className="h-5 w-5 text-ink-soft shrink-0" />
          </button>
        ))}
      </div>
    </div>
  )
}
