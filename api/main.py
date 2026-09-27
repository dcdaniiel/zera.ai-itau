"""API do Zera para a UI (FastAPI + ADK Runner).

    uvicorn api.main:app --reload --port 8080

POST /chat           {cliente_id, sessao_id, mensagem}        -> {texto, ui, estado}
POST /simular_tempo  {cliente_id, ate: "2027-01-07"}          -> gatilhos, pagamentos processados
GET  /gatilhos/{cliente_id}
POST /reset/{cliente_id}
GET  /health

Cards: cada tool deixa blocos em state["ui"]; a resposta devolve os blocos novos desde a última mensagem.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from motor import criar_acordo_de_cenario, montar_cenarios, resumo_cenario, situacao_hoje, termos  # noqa: E402
from zera_agent.agent import root_agent  # noqa: E402
from zera_agent.contexto import Contexto  # noqa: E402
from zera_agent.experiencia import PREFERENCIAS_PADRAO, Experiencia  # noqa: E402

APP_NAME = "zera"
app = FastAPI(title="Zera API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ZERA_CORS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

sessoes = InMemorySessionService()  # P1: VertexAiSessionService (Agent Engine Sessions)
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessoes)


class ChatIn(BaseModel):
    cliente_id: str = "cli_001"
    sessao_id: str = "demo"
    mensagem: str


class TempoIn(BaseModel):
    cliente_id: str = "cli_001"
    ate: str  # YYYY-MM-DD


async def _sessao(cliente_id: str, sessao_id: str):
    s = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id)
    if s is None:
        s = await sessoes.create_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id,
                                         state={"cliente_id": cliente_id, "ui": []})
    return s


@app.get("/health")
async def health():
    return {"ok": True, "modelo": str(root_agent.model)}


@app.post("/chat")
async def chat(body: ChatIn):
    s = await _sessao(body.cliente_id, body.sessao_id)
    ja_vistos = len(s.state.get("ui", []))
    conteudo = types.Content(role="user", parts=[types.Part(text=body.mensagem)])
    texto = ""
    async for ev in runner.run_async(user_id=body.cliente_id, session_id=s.id, new_message=conteudo):
        if ev.is_final_response() and ev.content and ev.content.parts:
            texto = "".join(p.text or "" for p in ev.content.parts if p.text)
    s = await sessoes.get_session(app_name=APP_NAME, user_id=body.cliente_id, session_id=s.id)
    ui = s.state.get("ui", [])
    return {
        "texto": texto,
        "ui": ui[ja_vistos:] if len(ui) >= ja_vistos else ui,
        "estado": {k: s.state.get(k) for k in ("alucinacao_numerica", "bloqueios_consentimento", "vulneravel", "gatilho")},
    }


@app.post("/simular_tempo")
async def simular_tempo(body: TempoIn):
    try:
        return Contexto.para(body.cliente_id).avancar_tempo(date.fromisoformat(body.ate))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/gatilhos/{cliente_id}")
async def gatilhos(cliente_id: str):
    c = Contexto.para(cliente_id)
    return {"hoje": c.estado["hoje"], "gatilhos": c.estado.get("gatilhos_pendentes", []), "acordo": c.estado.get("acordo")}


@app.post("/reset/{cliente_id}")
async def reset(cliente_id: str):
    Contexto.para(cliente_id).resetar()
    Contexto.limpar_cache()
    return {"ok": True}


# ======================================================================
# Fluxo guiado do app (wizard) — 100% núcleo determinístico, sem LLM.
# O LLM só entra em /explicar (texto) e em /chat (conversa livre), sempre atrás dos guardrails.
# ======================================================================

class CompromissoIn(BaseModel):
    descricao: str = "gasto importante"
    valor_mensal: float


class CenariosIn(BaseModel):
    valor_extra: float = 0.0


class ContratarIn(BaseModel):
    cenario_id: str
    debito_automatico: bool = True
    frase_confirmacao: str = "Confirmo a contratação"


class ExplicarIn(BaseModel):
    cenario_id: str
    sessao_id: str = "wizard"


def _ctx(cliente_id: str) -> Contexto:
    return Contexto.para(cliente_id)


@app.get("/v1/clientes/{cliente_id}/resumo")
async def resumo(cliente_id: str):
    """Tela 1 (Entrada): quanto o cliente paga hoje, por dívida/instituição, e o gatilho pendente."""
    c = _ctx(cliente_id)
    hoje = situacao_hoje(c.perfil, c.politica)
    return {"cliente": c.perfil.nome, "hoje_simulado": c.estado["hoje"], "situacao_hoje": hoje,
            "capacidade": c.capacidade.to_dict(), "gatilhos": c.estado.get("gatilhos_pendentes", []),
            "compromissos_extras": c.estado.get("compromissos_extras", []), "acordo": c.estado.get("acordo")}


@app.post("/v1/clientes/{cliente_id}/compromissos")
async def compromissos(cliente_id: str, body: CompromissoIn):
    """Tela 2 (Confirmação): gasto importante que não aparece no extrato -> reduz a sobra e recalcula a capacidade."""
    c = _ctx(cliente_id)
    item = c.adicionar_compromisso(body.descricao, body.valor_mensal)
    return {"ok": True, "compromisso": item, "capacidade": c.capacidade.to_dict()}


@app.post("/v1/clientes/{cliente_id}/cenarios")
async def cenarios(cliente_id: str, body: CenariosIn):
    """Telas 3-5 (Processamento/Resultado/Outras opções): hoje vs nova opção + alternativas, tudo do motor."""
    c = _ctx(cliente_id)
    valor_extra = body.valor_extra
    if not valor_extra:
        g = next((g for g in c.estado.get("gatilhos_pendentes", []) if g.get("tipo") == "dinheiro_extra"), None)
        if g:
            valor_extra = float(g.get("valor", 0.0))
    hoje = situacao_hoje(c.perfil, c.politica)
    r = montar_cenarios(c.perfil, c.capacidade, valor_extra=valor_extra, politica=c.politica)
    opcoes = [resumo_cenario(cen, hoje, c.politica) for cen in r.get("cenarios", [])]
    c.estado["cenarios_wizard"] = {cen["id"]: cen for cen in r.get("cenarios", [])}
    c.salvar()
    c.registrar_evento("cenarios_propostos", {"origem": "wizard", "valor_extra": valor_extra, "recomendado": r.get("recomendado")})
    return {"valor_extra": valor_extra, "situacao_hoje": hoje, "recomendado": r.get("recomendado"), "opcoes": opcoes,
            "nenhum_cenario_cabe": r.get("nenhum_cenario_cabe", False), "motivo": r.get("motivo"),
            "parcela_conforto": r.get("parcela_conforto"), "perfil_risco": r.get("perfil_risco"),
            "total_combinacoes_avaliadas": r.get("total_combinacoes_avaliadas")}


@app.get("/v1/clientes/{cliente_id}/cenarios/{cenario_id}/termos")
async def termos_cenario(cliente_id: str, cenario_id: str, debito_automatico: bool = True):
    """Telas 6-8 (Termos / Débito automático / Confirmação): parcela, prazo, total, CET, 1º vencimento, dívidas incluídas."""
    c = _ctx(cliente_id)
    cen = (c.estado.get("cenarios_wizard") or {}).get(cenario_id.upper())
    if not cen:
        raise HTTPException(404, "cenário não encontrado; chame /cenarios antes")
    return termos(cen, c.perfil, c.hoje, debito_automatico, c.politica)


@app.post("/v1/clientes/{cliente_id}/contratar")
async def contratar(cliente_id: str, body: ContratarIn):
    """Telas 8-10: consentimento explícito registrado -> acordo criado pelo motor (nunca pelo LLM)."""
    c = _ctx(cliente_id)
    cen = (c.estado.get("cenarios_wizard") or {}).get(body.cenario_id.upper())
    if not cen:
        raise HTTPException(404, "cenário não encontrado; chame /cenarios antes")
    t = termos(cen, c.perfil, c.hoje, body.debito_automatico, c.politica)
    consentimento = {"acao": "fechar_acordo", "frase_cliente": body.frase_confirmacao, "versao_termo": "demo-v1",
                     "timestamp": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "data_simulada": c.estado["hoje"],
                     "debito_automatico": body.debito_automatico}
    c.estado.setdefault("consentimentos", []).append(consentimento)
    acordo = criar_acordo_de_cenario(c.perfil, cen, c.hoje, c.politica)
    if body.debito_automatico and t["desconto_debito_automatico"] > 0:
        for comp in acordo.componentes:  # desconto proporcional em cada componente
            comp["parcela"] = round(comp["parcela"] * (1 - c.politica["desconto_debito_automatico_pct"]), 2)
        acordo.parcela = t["parcela_mensal"]
        acordo.historico.append({"data": c.estado["hoje"], "evento": "debito_automatico_ativado", "desconto_mensal": t["desconto_debito_automatico"]})
    c.estado["gatilhos_pendentes"] = []
    c.salvar(acordo)
    c.registrar_evento("acordo_fechado", {"origem": "wizard", "cenario": body.cenario_id.upper(), "parcela": acordo.parcela,
                                          "prazo": acordo.prazo, "debito_automatico": body.debito_automatico})
    return {"ok": True, "acordo": acordo.to_dict(), "termos": t, "consentimento": consentimento}


@app.post("/v1/clientes/{cliente_id}/explicar")
async def explicar(cliente_id: str, body: ExplicarIn):
    """'Por que essa opção?' — o LLM explica em linguagem simples usando SÓ os números do cenário (guardrails de saída ativos)."""
    c = _ctx(cliente_id)
    cen = (c.estado.get("cenarios_wizard") or {}).get(body.cenario_id.upper())
    if not cen:
        raise HTTPException(404, "cenário não encontrado; chame /cenarios antes")
    hoje = situacao_hoje(c.perfil, c.politica)
    rc = resumo_cenario(cen, hoje, c.politica)
    pergunta = ("Explique em até 5 frases, em português simples e sem pressão, por que a opção abaixo foi recomendada para mim, "
                "citando apenas estes números (não invente outros): "
                f"parcela {rc['parcela_mensal']:.2f} por mês, prazo {rc['prazo_meses']} meses, total {rc['total_a_pagar']:.2f}, "
                f"hoje pago {hoje['pagamento_mensal']:.2f} por mês em {hoje['qtd_pagamentos']} pagamentos, "
                f"libera {rc['liberado_por_mes']:.2f} por mês, reserva {rc['reserva']:.2f}; ações: "
                + "; ".join(a["descricao"] for a in cen["acoes"]))
    s = await _sessao(cliente_id, body.sessao_id)
    conteudo = types.Content(role="user", parts=[types.Part(text=pergunta)])
    texto = ""
    async for ev in runner.run_async(user_id=cliente_id, session_id=s.id, new_message=conteudo,
                                     state_delta={"ultimos_numeros": rc["numeros_permitidos"] + hoje["numeros_permitidos"]}):
        if ev.is_final_response() and ev.content and ev.content.parts:
            texto = "".join(p.text or "" for p in ev.content.parts if p.text)
    return {"texto": texto}


# ======================================================================
# Experiência zera.ai (spec v1): máquina de estados determinística + contrato estruturado.
# O front reage a `response_type`; o LLM só explica / responde perguntas livres (atrás dos guardrails).
# ======================================================================

class PreferenciasIn(BaseModel):
    analisar: bool = True
    momentos: bool = True
    recomendar: bool = True
    avisar: bool = True
    open_finance: bool = False


class EventoIn(BaseModel):
    acao: str                      # START | ANSWER | VIEW_OPTIONS | ASK_WHY | ASK_QUESTION | SELECT_OPTION | CONTINUE | SET_AUTOPAY | CONFIRM | CANCEL | DISMISS | RESET | GET
    payload: dict = {}
    sessao_id: str = "experiencia"


def _explicador(cliente_id: str, sessao_id: str):
    """LLM (ADK + Gemini) com os guardrails de entrada/saída; os números permitidos vêm do orquestrador."""
    async def explicar(pergunta: str, numeros_permitidos: list[float]) -> str:
        s = await _sessao(cliente_id, sessao_id)
        conteudo = types.Content(role="user", parts=[types.Part(text=pergunta)])
        texto = ""
        async for ev in runner.run_async(user_id=cliente_id, session_id=s.id, new_message=conteudo,
                                         state_delta={"ultimos_numeros": sorted(set(numeros_permitidos))}):
            if ev.is_final_response() and ev.content and ev.content.parts:
                texto = "".join(p.text or "" for p in ev.content.parts if p.text)
        return texto
    return explicar


@app.get("/v1/clientes/{cliente_id}/preferencias")
async def get_preferencias(cliente_id: str):
    c = _ctx(cliente_id)
    return c.estado.get("preferencias", dict(PREFERENCIAS_PADRAO))


@app.post("/v1/clientes/{cliente_id}/preferencias")
async def set_preferencias(cliente_id: str, body: PreferenciasIn):
    """Tela de preferências: `avisar` é a proactive_permission da spec; tudo fica registrado como consentimento de uso."""
    c = _ctx(cliente_id)
    c.estado["preferencias"] = body.model_dump()
    c.salvar()
    c.registrar_evento("preferencias_salvas", body.model_dump())
    return {"ok": True, "preferencias": c.estado["preferencias"]}


@app.get("/v1/clientes/{cliente_id}/proativa")
async def proativa(cliente_id: str):
    """PROACTIVE_MESSAGE ou silêncio ({silent: true, checks}). Nunca gera conteúdo só a partir do gatilho."""
    c = _ctx(cliente_id)
    return Experiencia(c).avaliar_proatividade()


@app.get("/v1/clientes/{cliente_id}/experiencia")
async def experiencia_atual(cliente_id: str):
    c = _ctx(cliente_id)
    return Experiencia(c).resposta_atual()


@app.post("/v1/clientes/{cliente_id}/experiencia/evento")
async def experiencia_evento(cliente_id: str, body: EventoIn):
    c = _ctx(cliente_id)
    exp = Experiencia(c, explicador=_explicador(cliente_id, body.sessao_id))
    antes = 0
    if body.acao.upper() in ("ASK_QUESTION", "ASK_WHY"):
        s = await _sessao(cliente_id, body.sessao_id)
        antes = len(s.state.get("bloqueios_guardrail") or [])
    resposta = await exp.evento(body.acao.upper(), body.payload)
    if body.acao.upper() in ("ASK_QUESTION", "ASK_WHY"):
        s = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=body.sessao_id)
        bloqueios = (s.state.get("bloqueios_guardrail") or []) if s else []
        if len(bloqueios) > antes:
            resposta["guardrail"] = bloqueios[-1]
    return resposta


# ---------- UI (produção): a API serve o build do Vite em / (mesmo serviço no Cloud Run) ----------
_UI_DIST = RAIZ / "ui" / "dist"
if _UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
