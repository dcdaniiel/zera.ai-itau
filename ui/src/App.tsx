import { CalendarClock, FlaskConical, RotateCcw, Users, WifiOff, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, getCliente, setCliente } from './api'
import { Chat } from './screens/Chat'
import { Experiencia } from './screens/Experiencia'
import { Home } from './screens/Home'
import { Onboarding, Preferencias } from './screens/Onboarding'
import { Perfis } from './screens/Perfis'
import type { PerfilResumo, Resposta } from './types'

type Tela = 'perfis' | 'onboarding' | 'preferencias' | 'home' | 'experiencia' | 'chat'

export default function App() {
  const [tela, setTela] = useState<Tela>(getCliente() ? 'onboarding' : 'perfis')
  const [perfil, setPerfil] = useState<PerfilResumo | null>(null)
  const [proativa, setProativa] = useState<Resposta | null | undefined>(undefined)  // undefined = carregando
  const [acordo, setAcordo] = useState<any | null>(null)
  const [hoje, setHoje] = useState<string>('')
  const [erroApi, setErroApi] = useState<string | null>(null)
  const [dev, setDev] = useState(false)
  const [acordos, setAcordos] = useState<any[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [inicial, setInicial] = useState<Resposta | undefined>()

  async function atualizarHome() {
    setProativa(undefined); setErroApi(null)
    try {
      // ordem da spec: trigger -> contexto -> oportunidade -> benefício -> permissão -> conteúdo; senão, silêncio
      const [p, e] = await Promise.all([api.proativa(), api.estado()])
      setProativa(p); setAcordo(e.acordo); setAcordos(e.acordos ?? []); setHoje(e.hoje)
    } catch (e) {
      setProativa(null); setErroApi(e instanceof Error ? e.message : 'API indisponível')
    }
  }
  useEffect(() => { api.health().catch((e) => setErroApi(e.message)) }, [])
  useEffect(() => { if (getCliente() && !perfil) api.perfil().then((p) => setPerfil({ cliente_id: p.cliente_id, nome: p.nome, persona: p.persona, cluster: null, distancia: null, renda_mediana: p.renda_mediana, renda_conhecida: !p.renda_desconhecida, total_dividas: p.total_dividas, qtd_dividas: p.dividas.length, meses_no_vermelho: null, sinais: '', fonte_dividas: '', fonte: p.fonte })).catch(() => setTela('perfis')) }, [])

  function escolherPerfil(p: PerfilResumo) { setCliente(p.cliente_id); setPerfil(p); setProativa(undefined); setAcordo(null); setTela('onboarding') }

  async function salvarPreferencias(prefs: Record<string, boolean>) {
    setOcupado(true)
    try {
      await api.preferencias({ analisar: !!prefs.analisar, momentos: !!prefs.momentos, recomendar: !!prefs.recomendar, avisar: !!prefs.avisar, open_finance: !!prefs.open_finance })
      setTela('home'); await atualizarHome()
    } catch (e) { setErroApi(e instanceof Error ? e.message : 'falha ao salvar preferências') } finally { setOcupado(false) }
  }
  const abrir = () => { setInicial(undefined); setTela('experiencia') }
  /* Botão flutuante: com indicador proativo -> fluxo guiado (10 telas); sem indicador -> conversa com o agente ADK
     (guardrails + HITL + direcionamento do produto). Recusar a proatividade nunca impede pedir ajuda. */
  const [chatInicial, setChatInicial] = useState<string | undefined>()
  const abrirChat = (texto?: string) => { setChatInicial(texto); setInicial(undefined); setTela('chat') }
  /* Indicador NOVO (gatilho) -> fluxo guiado; só o acompanhamento do acordo (ou nenhum indicador) -> conversa com o agente */
  const abrirPeloBotao = () => { const temBalaoNovo = !!proativa && !proativa.silent && proativa.response_type === 'PROACTIVE_MESSAGE' && proativa.trigger !== 'acordo_ativo'; if (temBalaoNovo) abrir(); else abrirChat() }
  const sair = async () => { setTela('home'); await atualizarHome() }
  async function dispensar() { setOcupado(true); try { await api.evento('DISMISS'); await atualizarHome() } finally { setOcupado(false) } }

  async function avancar(ate: string) { setDev(false); setOcupado(true); try { await api.simularTempo(ate); setTela('home'); await atualizarHome() } catch (e) { setErroApi(String(e)) } finally { setOcupado(false) } }
  async function reset() { setDev(false); setOcupado(true); try { await api.reset(); setProativa(undefined); setAcordo(null); setTela('onboarding') } catch (e) { setErroApi(String(e)) } finally { setOcupado(false) } }

  const nome = perfil?.nome ?? 'Cliente'
  return (
    <div className="min-h-full flex items-center justify-center p-0 sm:p-6">
      {/* moldura de celular no desktop; tela cheia (100dvh) no celular */}
      <div className="relative w-full sm:w-[400px] h-[100dvh] sm:h-[840px] sm:rounded-[2.5rem] sm:border-[10px] sm:border-[#1B1B1F] bg-mist overflow-hidden shadow-2xl">
        {tela === 'perfis' && <Perfis onEscolher={escolherPerfil} />}
        {tela === 'onboarding' && <Onboarding nome={nome} onAtivar={() => setTela('preferencias')} onDepois={() => { setTela('home'); atualizarHome() }} />}
        {tela === 'preferencias' && <Preferencias nome={nome} onVoltar={() => setTela('onboarding')} onSalvar={salvarPreferencias} />}
        {tela === 'home' && <Home nome={nome} proativa={proativa} acordo={acordo} acordos={acordos} erro={erroApi} onAbrir={abrir} onAbrirBotao={abrirPeloBotao} onConversar={() => abrirChat()} onDispensar={dispensar} onRecarregar={atualizarHome} />}
        {tela === 'experiencia' && <Experiencia onSair={sair} inicial={inicial} onConversar={abrirChat} />}
        {tela === 'chat' && <Chat nome={nome} onSair={sair} onAbrirExperiencia={abrir} mensagemInicial={chatInicial} />}

        {erroApi && tela !== 'home' && (
          <div className="absolute inset-x-3 top-3 z-40 flex items-center gap-2 rounded-2xl bg-danger-soft px-3 py-2 text-xs text-danger shadow"><WifiOff className="h-4 w-4 shrink-0" /> {erroApi}<button className="ml-auto font-bold" onClick={() => setErroApi(null)}>ok</button></div>
        )}
        {ocupado && <div className="absolute inset-0 z-40 bg-white/40 backdrop-blur-[1px] grid place-items-center"><div className="h-9 w-9 rounded-full border-4 border-itau-orange border-t-transparent animate-spin" /></div>}

        {tela !== 'perfis' && tela !== 'chat' && (
          <button onClick={() => setDev((v) => !v)} aria-label="Controles da demo"
            className="absolute top-[4.25rem] right-3 z-30 h-9 w-9 rounded-full bg-itau-blue text-white grid place-items-center shadow-lg opacity-60 active:scale-95">
            {dev ? <X className="h-4 w-4" /> : <FlaskConical className="h-4 w-4" />}
          </button>
        )}
        {dev && (
          <div className="absolute top-28 right-3 z-30 w-80 card p-3 rise max-h-[70%] overflow-y-auto">
            <div className="text-xs font-bold text-ink-soft uppercase tracking-wide mb-1">Controles da demonstração</div>
            <div className="text-[11px] text-ink-soft mb-3">Tudo aqui chama a API real (motor + BigQuery); nada é simulado no front. Perfil: <b>{nome}</b>{perfil?.persona ? ' (fixture de teste)' : perfil?.medoide ? ' (mais típico do segmento)' : ' (cliente real)'} · fonte {perfil?.fonte ?? '—'} · data simulada {hoje || '—'}.</div>
            <div className="space-y-2">
              {[
                { icon: <Users className="h-4 w-4" />, titulo: 'Trocar de perfil', desc: 'Volta à lista de clientes reais do segmento-alvo (BigQuery ML k-means ou regras na amostra).', onClick: () => { setDev(false); setTela('perfis') } },
                { icon: <CalendarClock className="h-4 w-4" />, titulo: 'Avançar o relógio para 6 dez/2026', desc: 'Entra o 13º (R$ 2.800). Se ainda não há acordo, a zera.ai propõe usar parte como entrada; com acordo, oferece amortizar.', onClick: () => avancar('2026-12-06') },
                { icon: <CalendarClock className="h-4 w-4" />, titulo: 'Avançar o relógio para 7 jan/2027', desc: 'Mês fraco (renda cai). Com acordo ativo, a parcela vence em 3 dias e a zera.ai oferece um respiro.', onClick: () => avancar('2027-01-07') },
                { icon: <RotateCcw className="h-4 w-4" />, titulo: 'Reiniciar a demonstração', desc: 'Apaga o estado deste perfil (acordo, consentimentos, gastos informados) e volta ao início da jornada.', onClick: reset },
              ].map((b) => (
                <button key={b.titulo} className="w-full text-left rounded-2xl border border-line bg-white p-3 active:bg-itau-orange-soft/40 transition" onClick={b.onClick}>
                  <div className="flex items-center gap-2 text-[13px] font-bold">{b.icon} {b.titulo}</div>
                  <div className="mt-0.5 text-[11px] text-ink-soft leading-snug">{b.desc}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
