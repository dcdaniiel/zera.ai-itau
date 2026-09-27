"""API do zera.ai para a UI (FastAPI + ADK Runner) — pronta para Cloud Run.

    uvicorn api.main:app --reload --port 8080

Operação
    GET  /health                       liveness (modelo, fonte, versão)
    GET  /ready                        readiness (fonte de dados responde; perfis disponíveis)
    GET  /metrics                      métricas em memória: latência p50/p95 por etapa, funil, LLM tokens/custo (FinOps)
Perfis (dados direto do BigQuery — sem mock)
    GET  /v1/clientes                  perfis disponíveis: persona + clientes reais do mesmo cluster (BigQuery ML)
    GET  /v1/clientes/{id}/perfil      perfil financeiro (renda, essenciais, sobra, dívidas com fonte, capacidade, segmento)
Experiência zera.ai (spec v1 — máquina de estados determinística; o LLM só explica/responde atrás dos guardrails)
    GET  /v1/clientes/{id}/preferencias | POST
    GET  /v1/clientes/{id}/proativa    PROACTIVE_MESSAGE ou {silent, checks}
    GET  /v1/clientes/{id}/experiencia  resposta atual (contrato estruturado)
    POST /v1/clientes/{id}/experiencia/evento {acao, payload, sessao_id}
Conversa livre com o agente ADK (tools determinísticas + consentimento)
    POST /chat {cliente_id, sessao_id, mensagem}
Demo / operação do relógio simulado
    POST /simular_tempo | GET /gatilhos/{id} | POST /reset/{id}

Toda etapa é medida (spans OTel + métricas + logs estruturados) — ver zera_agent/observabilidade.py.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from zera_agent import observabilidade as obs  # noqa: E402

obs.configurar_logs()
OTEL = obs.configurar_otel()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from dados.loader import fonte as fonte_dados, listar_clientes, perfil_clusters  # noqa: E402
from motor import criar_acordo_de_cenario, montar_cenarios, resumo_cenario, situacao_hoje, termos  # noqa: E402
from zera_agent.agent import MODEL, root_agent  # noqa: E402
from zera_agent.contexto import Contexto  # noqa: E402
from zera_agent.experiencia import PREFERENCIAS_PADRAO, Experiencia  # noqa: E402

log = logging.getLogger("zera.api")
APP_NAME = "zera"
app = FastAPI(title="zera.ai API", version=os.getenv("ZERA_VERSAO", "1.0.0"), docs_url="/docs" if os.getenv("ZERA_DOCS", "1") == "1" else None)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.getenv("ZERA_CORS", "*").split(",")],
                   allow_methods=["*"], allow_headers=["*"])


def _sessoes():
    """InMemory por padrão; ZERA_SESSOES=vertex usa o Agent Engine Sessions (Vertex AI) — estado de conversa gerenciado."""
    if os.getenv("ZERA_SESSOES") == "vertex" and os.getenv("ZERA_AGENT_ENGINE_ID"):
        from google.adk.sessions import VertexAiSessionService

        return VertexAiSessionService(project=os.getenv("GOOGLE_CLOUD_PROJECT"), location=os.getenv("ZERA_AGENT_ENGINE_LOCATION", "us-central1"),
                                      agent_engine_id=os.getenv("ZERA_AGENT_ENGINE_ID"))
    return InMemorySessionService()


sessoes = _sessoes()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessoes)


# ---------- observabilidade HTTP: request id, latência, status ----------

@app.middleware("http")
async def observar(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid4().hex[:12]
    inicio = time.perf_counter()
    rota = request.url.path
    try:
        with obs.medir("http", {"metodo": request.method, "rota": _rota_generica(rota)}):
            resposta = await call_next(request)
    except Exception as e:  # noqa: BLE001
        log.exception("erro não tratado", extra={"zera": {"request_id": rid, "rota": rota}})
        obs.registrar_metrica("zera.http_erro", 1, {"rota": _rota_generica(rota)})
        return JSONResponse({"erro": "falha interna", "request_id": rid, "detalhe": str(e)[:200]}, status_code=500)
    dur = (time.perf_counter() - inicio) * 1000
    resposta.headers["x-request-id"] = rid
    if not rota.startswith(("/assets", "/metrics", "/health")):
        log.info("http", extra={"zera": {"request_id": rid, "metodo": request.method, "rota": rota, "status": resposta.status_code, "latencia_ms": round(dur, 1)}})
    obs.registrar_metrica("zera.http_status", 1, {"rota": _rota_generica(rota), "status": str(resposta.status_code)})
    return resposta


def _rota_generica(rota: str) -> str:
    partes = rota.split("/")
    if len(partes) >= 4 and partes[1] == "v1" and partes[2] == "clientes":
        partes[3] = "{id}"
    return "/".join(partes)[:80]


@app.exception_handler(LookupError)
async def nao_encontrado(_: Request, e: LookupError):
    return JSONResponse({"erro": str(e)}, status_code=404)


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


async def _rodar_agente(cliente_id: str, sessao_id: str, texto: str, onde: str, state_delta: dict | None = None) -> str:
    """Um turno do agente ADK com contabilidade FinOps (tokens/custo por chamada, por jornada) e span próprio."""
    s = await _sessao(cliente_id, sessao_id)
    conteudo = types.Content(role="user", parts=[types.Part(text=texto)])
    resposta = ""
    inicio = time.perf_counter()
    jornada = (Contexto.para(cliente_id).estado.get("experiencia") or {}).get("jornada_id")
    with obs.medir("agente.turno", {"onde": onde, "cliente": cliente_id}):
        async for ev in runner.run_async(user_id=cliente_id, session_id=s.id, new_message=conteudo, state_delta=state_delta):
            if ev.usage_metadata:
                obs.registrar_llm(ev.usage_metadata, MODEL, jornada, onde, (time.perf_counter() - inicio) * 1000)
            if ev.is_final_response() and ev.content and ev.content.parts:
                resposta = "".join(p.text or "" for p in ev.content.parts if p.text)
    return resposta


# ======================================================================
# Operação
# ======================================================================

@app.get("/health")
async def health():
    return {"ok": True, "modelo": str(root_agent.model), "fonte": fonte_dados(), "estado": os.getenv("ZERA_ESTADO", "json"),
            "versao": app.version, "otel": OTEL, "location": os.getenv("GOOGLE_CLOUD_LOCATION")}


@app.get("/ready")
async def ready():
    try:
        with obs.medir("dados.listar_clientes", {}):
            perfis = listar_clientes()
        return {"ok": True, "fonte": fonte_dados(), "perfis": len(perfis)}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "fonte": fonte_dados(), "erro": str(e)[:300]}, status_code=503)


@app.get("/metrics")
async def metrics():
    return obs.resumo()


@app.post("/chat")
async def chat(body: ChatIn):
    s = await _sessao(body.cliente_id, body.sessao_id)
    ja_vistos = len(s.state.get("ui", []))
    texto = await _rodar_agente(body.cliente_id, body.sessao_id, body.mensagem, "chat")
    s = await sessoes.get_session(app_name=APP_NAME, user_id=body.cliente_id, session_id=s.id)
    ui = s.state.get("ui", [])
    return {"texto": texto, "ui": ui[ja_vistos:] if len(ui) >= ja_vistos else ui,
            "estado": {k: s.state.get(k) for k in ("alucinacao_numerica", "bloqueios_consentimento", "vulneravel", "gatilho")}}


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
# Perfis — dados direto do BigQuery (persona rotulada + clientes reais do cluster)
# ======================================================================

@app.get("/v1/clientes")
async def clientes():
    with obs.medir("dados.listar_clientes", {}):
        perfis = listar_clientes()
    return {"fonte": fonte_dados(), "perfis": perfis, "clusters": perfil_clusters() if fonte_dados() == "bigquery" else []}


@app.get("/v1/clientes/{cliente_id}/perfil")
async def perfil(cliente_id: str):
    c = _ctx(cliente_id)
    p = c.perfil
    return {"cliente_id": p.cliente_id, "nome": p.nome, "persona": p.persona, "fonte": p.fonte, "renda_desconhecida": p.renda_desconhecida,
            "renda_informada": p.renda_informada, "meses": p.meses, "renda_mensal": p.renda_mensal, "essenciais_mensal": p.essenciais_mensal,
            "compromissos_mensal": p.compromissos_mensal, "sobra_mensal": p.sobra_mensal, "renda_mediana": p.renda_mediana,
            "essenciais_mediana": p.essenciais_mediana, "dividas": [d.to_dict() for d in p.dividas], "total_dividas": p.total_dividas,
            "custo_total_mensal": p.custo_total_mensal, "capacidade": c.capacidade.to_dict(), "hoje_simulado": c.estado["hoje"],
            "gatilhos": c.estado.get("gatilhos_pendentes", []), "acordo": c.estado.get("acordo"),
            "compromissos_extras": c.estado.get("compromissos_extras", [])}


# ======================================================================
# Fluxo guiado (wizard) — 100% núcleo determinístico, sem LLM (mantido para integração direta / QA)
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
    c = _ctx(cliente_id)
    hoje = situacao_hoje(c.perfil, c.politica)
    return {"cliente": c.perfil.nome, "hoje_simulado": c.estado["hoje"], "situacao_hoje": hoje,
            "capacidade": c.capacidade.to_dict(), "gatilhos": c.estado.get("gatilhos_pendentes", []),
            "compromissos_extras": c.estado.get("compromissos_extras", []), "acordo": c.estado.get("acordo")}


@app.post("/v1/clientes/{cliente_id}/compromissos")
async def compromissos(cliente_id: str, body: CompromissoIn):
    c = _ctx(cliente_id)
    item = c.adicionar_compromisso(body.descricao, body.valor_mensal)
    return {"ok": True, "compromisso": item, "capacidade": c.capacidade.to_dict()}


@app.post("/v1/clientes/{cliente_id}/cenarios")
async def cenarios(cliente_id: str, body: CenariosIn):
    c = _ctx(cliente_id)
    valor_extra = body.valor_extra
    if not valor_extra:
        g = next((g for g in c.estado.get("gatilhos_pendentes", []) if g.get("tipo") == "dinheiro_extra"), None)
        if g:
            valor_extra = float(g.get("valor", 0.0))
    hoje = situacao_hoje(c.perfil, c.politica)
    with obs.medir("motor.montar_cenarios", {"cliente": cliente_id, "origem": "wizard"}):
        r = montar_cenarios(c.perfil, c.capacidade, valor_extra=valor_extra, politica=c.politica)
    opcoes = [resumo_cenario(cen, hoje, c.politica) for cen in r.get("cenarios", [])]
    c.estado["cenarios_wizard"] = {cen["id"]: cen for cen in r.get("cenarios", [])}
    c.salvar()
    c.registrar_evento("cenarios_propostos", {"origem": "wizard", "valor_extra": valor_extra, "recomendado": r.get("recomendado")})
    return {"valor_extra": valor_extra, "situacao_hoje": hoje, "recomendado": r.get("recomendado"), "opcoes": opcoes,
            "nenhum_cenario_cabe": r.get("nenhum_cenario_cabe", False), "motivo": r.get("motivo"), "diagnostico": r.get("diagnostico"),
            "parcela_conforto": r.get("parcela_conforto"), "perfil_risco": r.get("perfil_risco")}


@app.get("/v1/clientes/{cliente_id}/cenarios/{cenario_id}/termos")
async def termos_cenario(cliente_id: str, cenario_id: str, debito_automatico: bool = True):
    c = _ctx(cliente_id)
    cen = (c.estado.get("cenarios_wizard") or {}).get(cenario_id.upper())
    if not cen:
        raise HTTPException(404, "cenário não encontrado; chame /cenarios antes")
    return termos(cen, c.perfil, c.hoje, debito_automatico, c.politica)


@app.post("/v1/clientes/{cliente_id}/contratar")
async def contratar(cliente_id: str, body: ContratarIn):
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
        for comp in acordo.componentes:
            comp["parcela"] = round(comp["parcela"] * (1 - c.politica["desconto_debito_automatico_pct"]), 2)
        acordo.parcela = t["parcela_acordo"]
        acordo.historico.append({"data": c.estado["hoje"], "evento": "debito_automatico_ativado", "desconto_mensal": t["desconto_debito_automatico"]})
    c.estado["gatilhos_pendentes"] = []
    c.salvar(acordo)
    c.registrar_evento("acordo_fechado", {"origem": "wizard", "cenario": body.cenario_id.upper(), "parcela": acordo.parcela,
                                          "prazo": acordo.prazo, "debito_automatico": body.debito_automatico})
    obs.registrar_metrica("zera.acordo_fechado", 1, {"opcao": body.cenario_id.upper(), "autopay": str(body.debito_automatico)})
    return {"ok": True, "acordo": acordo.to_dict(), "termos": t, "consentimento": consentimento}


@app.post("/v1/clientes/{cliente_id}/explicar")
async def explicar(cliente_id: str, body: ExplicarIn):
    c = _ctx(cliente_id)
    cen = (c.estado.get("cenarios_wizard") or {}).get(body.cenario_id.upper())
    if not cen:
        raise HTTPException(404, "cenário não encontrado; chame /cenarios antes")
    hoje = situacao_hoje(c.perfil, c.politica)
    rc = resumo_cenario(cen, hoje, c.politica)
    pergunta = ("Explique em até 5 frases, em português simples e sem pressão, por que a opção abaixo foi recomendada para mim, "
                "citando apenas estes números (não invente outros): "
                f"parcela {rc['parcela_mensal']:.2f} por mês, prazo {rc['prazo_meses']} meses, total {rc['total_a_pagar']:.2f} "
                f"(saldo {rc['saldo_original']:.2f} + juros {rc['juros_acordo']:.2f}), hoje pago {hoje['pagamento_mensal']:.2f} por mês em "
                f"{hoje['qtd_pagamentos']} pagamentos, libera {rc['liberado_por_mes']:.2f} por mês; ações: " + "; ".join(a["descricao"] for a in cen["acoes"]))
    texto = await _rodar_agente(cliente_id, body.sessao_id, pergunta, "explicar",
                                state_delta={"ultimos_numeros": rc["numeros_permitidos"] + hoje["numeros_permitidos"]})
    return {"texto": texto}


# ======================================================================
# Experiência zera.ai (spec v1)
# ======================================================================

class PreferenciasIn(BaseModel):
    analisar: bool = True
    momentos: bool = True
    recomendar: bool = True
    avisar: bool = True
    open_finance: bool = False


class EventoIn(BaseModel):
    acao: str
    payload: dict = {}
    sessao_id: str = "experiencia"


def _explicador(cliente_id: str, sessao_id: str):
    """LLM (ADK + Gemini) com os guardrails de entrada/saída; os números permitidos vêm do orquestrador."""
    async def explicar(pergunta: str, numeros_permitidos: list[float]) -> str:
        return await _rodar_agente(cliente_id, sessao_id, pergunta, "experiencia", state_delta={"ultimos_numeros": sorted(set(numeros_permitidos))})
    return explicar


@app.get("/v1/clientes/{cliente_id}/preferencias")
async def get_preferencias(cliente_id: str):
    return _ctx(cliente_id).estado.get("preferencias", dict(PREFERENCIAS_PADRAO))


@app.post("/v1/clientes/{cliente_id}/preferencias")
async def set_preferencias(cliente_id: str, body: PreferenciasIn):
    c = _ctx(cliente_id)
    c.estado["preferencias"] = body.model_dump()
    c.salvar()
    c.registrar_evento("preferencias_salvas", body.model_dump())
    obs.registrar_metrica("zera.preferencias", 1, {"avisar": str(body.avisar)})
    return {"ok": True, "preferencias": c.estado["preferencias"]}


@app.get("/v1/clientes/{cliente_id}/proativa")
async def proativa(cliente_id: str):
    with obs.medir("experiencia.proatividade", {"cliente": cliente_id}):
        return Experiencia(_ctx(cliente_id)).avaliar_proatividade()


@app.get("/v1/clientes/{cliente_id}/experiencia")
async def experiencia_atual(cliente_id: str):
    return Experiencia(_ctx(cliente_id)).resposta_atual()


@app.post("/v1/clientes/{cliente_id}/experiencia/evento")
async def experiencia_evento(cliente_id: str, body: EventoIn):
    c = _ctx(cliente_id)
    exp = Experiencia(c, explicador=_explicador(cliente_id, body.sessao_id))
    acao = body.acao.upper()
    antes = 0
    if acao in ("ASK_QUESTION", "ASK_WHY"):
        s = await _sessao(cliente_id, body.sessao_id)
        antes = len(s.state.get("bloqueios_guardrail") or [])
    with obs.medir("experiencia.evento", {"acao": acao, "cliente": cliente_id}):
        resposta = await exp.evento(acao, body.payload)
    if acao in ("ASK_QUESTION", "ASK_WHY"):
        s = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=body.sessao_id)
        bloqueios = (s.state.get("bloqueios_guardrail") or []) if s else []
        if len(bloqueios) > antes:
            resposta["guardrail"] = bloqueios[-1]
            obs.registrar_metrica("zera.guardrail_bloqueio", 1, {"camada": bloqueios[-1].get("camada", ""), "tipo": bloqueios[-1].get("tipo", "")})
    resposta["finops"] = obs.custo_da_jornada(resposta.get("jornada_id"))
    return resposta


# ---------- UI (produção): a API serve o build do Vite em / (mesmo serviço no Cloud Run) ----------
_UI_DIST = RAIZ / "ui" / "dist"
if _UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
