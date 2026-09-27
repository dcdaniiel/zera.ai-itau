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
Conversa livre com o agente ADK (tools determinísticas + guardrails + HITL nativo do ADK)
    GET  /chat/inicio?cliente_id=      abertura determinística (0 tokens), proteções e sugestões
    POST /chat {cliente_id, sessao_id, mensagem}         -> {texto, ui[], hitl?, guardrail?, sugestoes[], finops}
    POST /chat/confirmar {request_id, confirmed, frase}  -> retoma a tool pausada com a decisão humana
Demo / operação do relógio simulado
    POST /simular_tempo | GET /gatilhos/{id} | POST /reset/{id}

Toda etapa é medida (spans OTel + métricas + logs estruturados) — ver zera_agent/observabilidade.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
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
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.adk.events import Event, EventActions  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from dados.loader import fonte_efetiva as fonte_dados, listar_clientes, perfil_clusters  # noqa: E402
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


class ConfirmarIn(BaseModel):
    cliente_id: str = "cli_001"
    sessao_id: str = "demo"
    request_id: str                      # id do adk_request_confirmation devolvido em `hitl` (ou btn_… do botão Contratar)
    confirmed: bool = True
    frase: str = "Confirmo"


class ContratarIn(BaseModel):
    cliente_id: str = "cli_001"
    sessao_id: str = "demo"
    cenario_id: str                      # C1, C2… (do card de cenários desta sessão)


class TempoIn(BaseModel):
    cliente_id: str = "cli_001"
    ate: str  # YYYY-MM-DD


async def _sessao(cliente_id: str, sessao_id: str):
    s = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id)
    if s is None:
        s = await sessoes.create_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id,
                                         state={"cliente_id": cliente_id, "ui": []})
    return s


async def _rodar_agente(cliente_id: str, sessao_id: str, texto: str, onde: str, state_delta: dict | None = None,
                        conteudo: types.Content | None = None) -> dict:
    """Um turno do agente ADK com contabilidade FinOps e detecção de HITL (adk_request_confirmation).

    Devolve {texto, hitl}. `hitl` aparece quando uma tool com efeito (fechar_acordo, acionar_respiro, amortizar) pausou
    esperando a confirmação humana: o app mostra o card e responde em POST /chat/confirmar.
    """
    s = await _sessao(cliente_id, sessao_id)
    conteudo = conteudo or types.Content(role="user", parts=[types.Part(text=texto)])
    resposta, hitl = "", None
    inicio = time.perf_counter()
    jornada = (Contexto.para(cliente_id).estado.get("experiencia") or {}).get("jornada_id")
    with obs.medir("agente.turno", {"onde": onde, "cliente": cliente_id}):
        async for ev in runner.run_async(user_id=cliente_id, session_id=s.id, new_message=conteudo, state_delta=state_delta):
            if ev.usage_metadata:
                obs.registrar_llm(ev.usage_metadata, MODEL, jornada, onde, (time.perf_counter() - inicio) * 1000)
            for fc in ev.get_function_calls():
                if fc.name == "adk_request_confirmation" and fc.args:
                    original = fc.args.get("originalFunctionCall") or {}
                    hitl = {"request_id": fc.id, "tool": original.get("name"), "args": original.get("args") or {},
                            "hint": (fc.args.get("toolConfirmation") or {}).get("hint", "")}
            if ev.is_final_response() and ev.content and ev.content.parts:
                texto_ev = "".join(p.text or "" for p in ev.content.parts if p.text)
                if texto_ev:
                    resposta = texto_ev
    if hitl:
        hitl = _enriquecer_hitl(cliente_id, sessao_id, hitl)
        obs.registrar_metrica("zera.hitl_pedido", 1, {"tool": str(hitl.get("tool"))})
    return {"texto": resposta, "hitl": hitl}


def _enriquecer_hitl(cliente_id: str, sessao_id: str, hitl: dict) -> dict:
    """Card de confirmação com os números do motor (nunca do texto do modelo)."""
    from zera_agent.tools import ROTULOS_HITL

    c = Contexto.para(cliente_id)
    tool, args = hitl.get("tool"), hitl.get("args") or {}
    hitl["titulo"] = ROTULOS_HITL.get(tool, tool)
    hitl["detalhes"] = []
    hitl["frase_sugerida"] = {"fechar_acordo": "Confirmo a contratação", "acionar_respiro": "Confirmo o respiro", "amortizar": "Confirmo a amortização"}.get(tool, "Confirmo")
    return hitl


def _hitl_com_sessao(hitl: dict, estado_sessao: dict, cliente_id: str) -> dict:
    """Completa o card com o cenário/plano guardado na sessão (state['cenarios'] / state['planos'])."""
    from motor.modelos import brl

    c = Contexto.para(cliente_id)
    tool, args = hitl.get("tool"), hitl.get("args") or {}
    if tool == "fechar_acordo":
        pid = str(args.get("plano_id", "")).upper()
        cen = (estado_sessao.get("cenarios") or {}).get(pid)
        plano = (estado_sessao.get("planos") or {}).get(pid)
        if cen:
            hitl["detalhes"] = [("Opção", f"{pid} · {', '.join(cen.get('rotulos', []))}"), ("Parcela", f"{brl(cen['comprometimento_mensal'])}/mês"),
                                ("Prazo", f"{cen['prazo_meses']} meses"), ("Total", brl(cen["custo_total"])),
                                ("Saldo devedor", brl(cen["saldo_original"])), ("Juros do acordo", brl(cen["juros_acordo"]))]
            hitl["resumo"] = cen.get("resumo")
        elif plano:
            hitl["detalhes"] = [("Plano", f"{pid} · {plano['nome']}"), ("Parcela", f"{brl(plano['parcela'])}/mês"), ("Prazo", f"{plano['prazo']} meses"), ("Total", brl(plano["total_pago"]))]
    elif tool == "acionar_respiro" and c.acordo:
        hitl["detalhes"] = [("Parcela adiada", brl(c.acordo.parcela)), ("Próximo vencimento", c.acordo.proximo_vencimento),
                            ("Respiros restantes", str(c.acordo.respiros_max - c.acordo.respiros_usados))]
    elif tool == "amortizar":
        hitl["detalhes"] = [("Valor", brl(float(args.get("valor", 0)))), ("Reserva", "sim" if args.get("preservar_reserva", True) else "não")]
    hitl["detalhes"] = [{"k": k, "v": v} for k, v in hitl["detalhes"]]
    return hitl


_G = r"(oi+|ol[aá]|e a[ií]|eai|opa|hey|hello|bom dia|boa tarde|boa noite|tudo bem|tudo bom|como vai|td bem|zera)"
RE_SAUDACAO = re.compile(rf"^\W*{_G}(\W+{_G})*(\W+(zera|zera\.ai))?\W*$", re.IGNORECASE)          # só cumprimento, nada mais
_A = r"(obrigad[ao]|valeu|brigad[ao]|show|perfeito|ok(ay)?|beleza|entendi|certo|tchau|at[eé] (mais|logo)|bom descanso|boa noite)"
RE_AGRADECIMENTO = re.compile(rf"^\W*{_A}(\W+{_A})*(\W+(zera|zera\.ai|por (agora|hoje|enquanto)))?\W*$", re.IGNORECASE)


def _roteamento_deterministico(c: Contexto, texto: str) -> str | None:
    """Compreensão de contexto antes do agente: cumprimento, agradecimento e despedida não disparam tools nem o modelo.
    A sequência (entender -> opções -> escolher -> confirmar no app) só começa quando a cliente pede algo que precisa dela."""
    t = (texto or "").strip()
    if len(t.split()) > 6:
        return None
    nome = (c.perfil.nome or "").split(" ")[0]
    voc = f"{nome}, " if nome and nome.lower() != "cliente" else ""
    if RE_SAUDACAO.search(t):
        acordo = c.estado.get("acordo")
        if acordo and acordo.get("status") == "ativo":
            return (f"Oi{', ' + voc[:-2] if voc else ''}! Tudo bem? Seu acordo está em dia. Como posso ajudar?\n\n1) Ver como está o acordo\n2) Usar um respiro este mês\n3) Falar com uma pessoa")
        if c.perfil.renda_desconhecida:
            return (f"Oi{', ' + voc[:-2] if voc else ''}! Tudo bem? Estou aqui para ajudar com as suas dívidas, sem pressa e sem pressão. Como a sua renda não aparece no extrato, "
                    "o primeiro passo é você me dizer quanto entra por mês.\n\n1) Informar minha renda\n2) Ver quanto eu devo hoje\n3) Falar com uma pessoa")
        return (f"Oi{', ' + voc[:-2] if voc else ''}! Tudo bem? Estou aqui para ajudar com as suas dívidas, sem pressa e sem pressão. Por onde quer começar?\n\n"
                "1) Ver quanto eu devo hoje e quanto cresce por mês\n2) Ver as opções que cabem no meu mês\n3) Falar com uma pessoa")
    if RE_AGRADECIMENTO.search(t):
        return f"Por nada, {voc[:-2] if voc else 'até mais'}! Quando quiser, é só me chamar por aqui. Nada é contratado sem a sua confirmação no app."
    return None


ETAPAS = {"get_perfil_financeiro": "entender", "priorizar_dividas": "entender", "calcular_capacidade": "entender", "informar_renda": "entender",
          "informar_gasto_fixo": "entender", "montar_cenarios": "opcoes", "simular_planos": "opcoes", "comparar_com_padrao": "opcoes",
          "fechar_acordo": "confirmar", "acionar_respiro": "confirmar", "amortizar": "confirmar",
          "status_acordo": "acompanhar"}


def _sugestoes_chat(c: Contexto) -> list[str]:
    """Direcionamento do produto: próximos passos sempre visíveis (a conversa nunca fica sem rumo)."""
    acordo = c.estado.get("acordo")
    if acordo and acordo.get("status") == "ativo":
        s = ["Como está meu acordo?", "Este mês está apertado, posso usar um respiro?", "Entrou um dinheiro extra, o que faço?", "Quero falar com uma pessoa"]
        if c.perfil.dividas:
            s.insert(1, "Quero renegociar o que ficou de fora do acordo")
        return s
    if c.perfil.renda_desconhecida:
        return ["Minha renda é de uns R$ 2.500 por mês", "Quanto eu devo hoje?", "Quero falar com uma pessoa"]
    return ["Quanto eu devo hoje e quanto cresce por mês?", "Quais opções cabem no meu bolso?", "Por que essa opção?", "Quero falar com uma pessoa"]


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


@app.get("/chat/inicio")
async def chat_inicio(cliente_id: str, sessao_id: str = "demo"):
    """Abertura determinística da conversa (0 tokens): contexto, proteções e direcionamento do produto."""
    c = _ctx(cliente_id)
    nome = (c.perfil.nome or "").split(" ")[0]
    vocativo = f"{nome}, " if nome and nome.lower() != "cliente" else ""
    gat = c.estado.get("gatilhos_pendentes", [])
    acordo = c.estado.get("acordo")
    if acordo and acordo.get("status") == "ativo":
        ativos = [a for a in c.acordos if a.status == "ativo"]
        total = sum(a.parcela for a in ativos)
        from motor.modelos import brl
        venc = "/".join(reversed(str(acordo["proximo_vencimento"]).split("-"))) if acordo.get("proximo_vencimento") else "—"
        texto = (f"{vocativo}seu acordo está em dia: {brl(acordo['parcela'])} por mês, próximo vencimento em {venc}. "
                 if len(ativos) == 1 else
                 f"{vocativo}você tem {len(ativos)} acordos ativos, {brl(total)} por mês no total; o mais recente vence em {venc}. ")
        texto += "Se um mês apertar, dá para usar um respiro; se entrar um dinheiro extra, dá para amortizar."
        if c.perfil.dividas:
            texto += f" E ainda dá para renegociar o que ficou de fora ({len(c.perfil.dividas)} dívida(s))."
    elif c.perfil.renda_desconhecida:
        texto = (f"{vocativo}sou a zera.ai, do Itaú. Vi suas dívidas no extrato, mas não a sua renda — antes de calcular qualquer coisa, "
                 "preciso que você me diga quanto entra por mês, mais ou menos.")
    elif gat:
        texto = f"{vocativo}sou a zera.ai, do Itaú. Vi que {gat[0]['mensagem'][0].lower() + gat[0]['mensagem'][1:]} Quer que eu mostre o que cabe no seu mês?"
    else:
        texto = f"{vocativo}sou a zera.ai, do Itaú. Posso te ajudar a organizar seus pagamentos: ver quanto você deve, quanto cresce por mês e quais opções cabem no seu bolso."
    s = await _sessao(cliente_id, sessao_id)
    return {"texto": texto, "sugestoes": _sugestoes_chat(c), "protecoes": [
        "Eu não peço senha, código nem dados de outras pessoas, e não faço transferências.",
        "Todo número vem da calculadora do banco — nunca do modelo de linguagem.",
        "Nada é contratado sem a sua confirmação no botão do app.",
    ], "cliente": c.perfil.nome, "hoje_simulado": c.estado["hoje"], "sessao_id": s.id}


async def _resposta_chat(cliente_id: str, sessao_id: str, resultado: dict, ja_vistos: int, bloqueios_antes: int) -> dict:
    s = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id)
    estado = dict(s.state) if s else {}
    ui = estado.get("ui", [])
    hitl = _hitl_com_sessao(resultado["hitl"], estado, cliente_id) if resultado.get("hitl") else None
    bloqueios = estado.get("bloqueios_guardrail") or []
    c = _ctx(cliente_id)
    return {"texto": resultado["texto"], "ui": ui[ja_vistos:] if len(ui) >= ja_vistos else ui, "hitl": hitl,
            "guardrail": bloqueios[-1] if len(bloqueios) > bloqueios_antes else None,
            "sugestoes": _sugestoes_chat(c),
            "estado": {k: estado.get(k) for k in ("alucinacao_numerica", "bloqueios_consentimento", "vulneravel", "gatilho", "pii_redigida")},
            "finops": obs.custo_da_jornada((c.estado.get("experiencia") or {}).get("jornada_id"))}


@app.post("/chat")
async def chat(body: ChatIn):
    """Conversa livre com o agente ADK: tools determinísticas + guardrails + HITL (confirmação humana) para ações com efeito."""
    s = await _sessao(body.cliente_id, body.sessao_id)
    ja_vistos = len(s.state.get("ui", []))
    bloqueios_antes = len(s.state.get("bloqueios_guardrail") or [])
    fixo = _roteamento_deterministico(_ctx(body.cliente_id), body.mensagem)
    if fixo:
        obs.registrar_metrica("zera.chat_roteado", 1, {"tipo": "saudacao"})
        return await _resposta_chat(body.cliente_id, body.sessao_id, {"texto": fixo, "hitl": None}, ja_vistos, bloqueios_antes)
    resultado = await _rodar_agente(body.cliente_id, body.sessao_id, body.mensagem, "chat")
    return await _resposta_chat(body.cliente_id, body.sessao_id, resultado, ja_vistos, bloqueios_antes)


@app.post("/chat/stream")
async def chat_stream(body: ChatIn):
    """Mesma conversa, em NDJSON conforme o ADK emite os eventos: a UI mostra cada tool, cada card e o texto assim que
    acontecem (interação rápida e visível com a persona). Linhas: {tipo: tool_call|card|texto|hitl|guardrail|fim}."""
    return StreamingResponse(_stream_chat(body.cliente_id, body.sessao_id, body.mensagem, None), media_type="application/x-ndjson")


@app.post("/chat/contratar")
async def chat_contratar(body: ContratarIn):
    """Botão "Contratar" do card de cenários: gatilho determinístico (não depende do modelo interpretar texto).
    Devolve o card HITL com os números do motor; a execução só acontece em POST /chat/confirmar(/stream) com confirmed=true."""
    s = await _sessao(body.cliente_id, body.sessao_id)
    cen = (s.state.get("cenarios") or {}).get(body.cenario_id.strip().upper())
    if not cen:
        raise HTTPException(404, "cenário não está nesta conversa — peça as opções de novo")
    if not cen.get("viavel", True):
        raise HTTPException(409, "esse cenário não cabe no mês da cliente")
    request_id = f"btn_{uuid4().hex[:10]}"
    hitl = _hitl_com_sessao(_enriquecer_hitl(body.cliente_id, body.sessao_id, {"request_id": request_id, "tool": "fechar_acordo", "args": {"plano_id": cen["id"]}, "hint": "botão do app"}),
                            dict(s.state), body.cliente_id)
    hitl["canal"] = "botao"
    await sessoes.append_event(s, Event(author="user", invocation_id=f"btn-{request_id}",
                                        actions=EventActions(state_delta={"hitl_botao": {**(s.state.get("hitl_botao") or {}), request_id: cen["id"]}})))
    obs.registrar_metrica("zera.hitl_pedido", 1, {"tool": "fechar_acordo", "canal": "botao"})
    return {"hitl": hitl, "etapa": "confirmar"}


async def _stream_contratacao_botao(cliente_id: str, sessao_id: str, request_id: str, confirmed: bool, frase: str):
    """Confirmação (ou recusa) do card HITL aberto pelo botão: executa o motor e emite a mesma sequência de eventos do agente."""
    from zera_agent.tools import fechar_por_cenario

    linha = lambda obj: json.dumps(obj, ensure_ascii=False, default=str) + "\n"  # noqa: E731
    s = await _sessao(cliente_id, sessao_id)
    c = _ctx(cliente_id)
    cen_id = (s.state.get("hitl_botao") or {}).get(request_id)
    cen = (s.state.get("cenarios") or {}).get(cen_id or "")
    obs.registrar_metrica("zera.hitl_resposta", 1, {"confirmed": str(confirmed), "canal": "botao"})
    if not confirmed or not cen:
        yield linha({"tipo": "texto", "roteado": True, "texto": "Tudo bem, nada foi contratado. Quer ver outra opção ou tirar alguma dúvida?" if not confirmed
                     else "Não encontrei mais esse cenário nesta conversa. Peça as opções de novo que eu monto na hora."})
        yield linha({"tipo": "fim", "sugestoes": _sugestoes_chat(c), "finops": obs.custo_da_jornada(None), "estado": {}, "acordo": c.estado.get("acordo")})
        return
    registro = {"consentimento_id": f"cs_{uuid4().hex[:8]}", "acao": "fechar_acordo", "frase_cliente": frase or "Confirmo a contratação",
                "versao_termo": "demo-v1", "canal": "botao_app", "timestamp": datetime.now().isoformat(timespec="seconds"), "data_simulada": c.estado["hoje"]}
    c.estado.setdefault("consentimentos", []).append(registro)
    yield linha({"tipo": "etapa", "etapa": "confirmar"})
    yield linha({"tipo": "tool_call", "nome": "fechar_acordo", "args": {"plano_id": cen["id"]}, "rotulo": "Contratar o acordo"})
    with obs.medir("motor.criar_acordo", {"onde": "botao"}):
        resposta = fechar_por_cenario(c, cen)
    yield linha({"tipo": "tool_result", "nome": "fechar_acordo", "ok": True, "erro": None, "explicacao": resposta["explicacao"][:300]})
    yield linha({"tipo": "card", "bloco": {"tipo": "acordo", "dados": resposta}})
    a = resposta
    venc = "/".join(reversed(str(a.get("proximo_vencimento", "")).split("-"))) if a.get("proximo_vencimento") else "—"
    from motor.modelos import brl
    nome = (c.perfil.nome or "").split(" ")[0]
    yield linha({"tipo": "texto", "roteado": True, "texto": (f"Pronto{', ' + nome if nome and nome.lower() != 'cliente' else ''}: acordo fechado — {a['prazo']}x de {brl(a['parcela'])}, "
                                            f"primeira parcela em {venc}, com {a['respiros_max']} respiro(s) por ano se um mês apertar.\n\n"
                                            "1) Ver como fica meu acordo\n2) Ativar o débito automático (na tela)\n3) Falar com uma pessoa")})
    yield linha({"tipo": "etapa", "etapa": "acompanhar"})
    # o agente fica sabendo (a sessão do ADK guarda o acordo no estado; o guardrail injeta ACORDO ATIVO nos próximos turnos)
    await sessoes.append_event(s, Event(author="user", invocation_id=f"btn-{request_id}",
                                        actions=EventActions(state_delta={"ui": list(s.state.get("ui", []))[-5:] + [{"tipo": "acordo", "dados": resposta}]})))
    yield linha({"tipo": "fim", "sugestoes": _sugestoes_chat(c), "finops": obs.custo_da_jornada(None), "estado": {}, "acordo": c.estado.get("acordo")})


@app.post("/chat/confirmar/stream")
async def chat_confirmar_stream(body: ConfirmarIn):
    if body.request_id.startswith("btn_"):   # card aberto pelo botão Contratar: confirmação determinística (motor), sem modelo
        return StreamingResponse(_stream_contratacao_botao(body.cliente_id, body.sessao_id, body.request_id, body.confirmed, body.frase), media_type="application/x-ndjson")
    conteudo = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=body.request_id, name="adk_request_confirmation",
        response={"confirmed": body.confirmed, "payload": {"frase_cliente": body.frase, "canal": "app"}}))])
    obs.registrar_metrica("zera.hitl_resposta", 1, {"confirmed": str(body.confirmed)})
    return StreamingResponse(_stream_chat(body.cliente_id, body.sessao_id, "", conteudo, recusado=not body.confirmed), media_type="application/x-ndjson")


def _dica_operador(e: Exception) -> str:
    """Tradução dos erros de infraestrutura mais comuns do LLM para quem opera a demo (a cliente vê só o texto amigável)."""
    msg = str(e)
    if "default credentials" in msg.lower() or "Reauthentication" in msg or "invalid_grant" in msg:
        return "credencial do Google ausente/expirada — rode `gcloud auth application-default login` e reinicie a API"
    if "No API key" in msg:
        return "SDK do Gemini caiu no modo API key: GOOGLE_GENAI_USE_VERTEXAI/GOOGLE_CLOUD_PROJECT não carregados — confira zera_agent/.env"
    if "404" in msg and ("model" in msg.lower() or "publisher" in msg.lower()):
        return f"modelo {MODEL} não encontrado nesta location ({os.getenv('GOOGLE_CLOUD_LOCATION')}) — gemini-3.x é servido em `global`; `unset GOOGLE_CLOUD_LOCATION`"
    if "403" in msg or "PERMISSION_DENIED" in msg:
        return "sem permissão no Vertex AI para esta conta/projeto (roles/aiplatform.user)"
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "cota do modelo esgotada — tente de novo ou use ZERA_MODEL=gemini-2.5-flash"
    return msg[:200]


async def _stream_chat(cliente_id: str, sessao_id: str, texto: str, conteudo: types.Content | None, recusado: bool = False):
    from zera_agent.tools import ROTULOS_HITL

    linha = lambda obj: json.dumps(obj, ensure_ascii=False, default=str) + "\n"  # noqa: E731
    s = await _sessao(cliente_id, sessao_id)
    vistos = len(s.state.get("ui", []))
    bloqueios_antes = len(s.state.get("bloqueios_guardrail") or [])
    c0 = _ctx(cliente_id)
    if conteudo is None:
        fixo = _roteamento_deterministico(c0, texto)
        if fixo:  # compreensão de contexto: cumprimento/agradecimento -> resposta direta, sem tools, sem modelo
            obs.registrar_metrica("zera.chat_roteado", 1, {"tipo": "saudacao"})
            yield linha({"tipo": "texto", "texto": fixo, "roteado": True})
            yield linha({"tipo": "fim", "sugestoes": _sugestoes_chat(c0), "finops": obs.custo_da_jornada(None), "estado": {}, "acordo": c0.estado.get("acordo")})
            return
    conteudo = conteudo or types.Content(role="user", parts=[types.Part(text=texto)])
    jornada = (Contexto.para(cliente_id).estado.get("experiencia") or {}).get("jornada_id")
    inicio = time.perf_counter()
    final, hitl = "", None
    etapa_atual = None
    try:
        with obs.medir("agente.turno", {"onde": "chat_stream", "cliente": cliente_id}):
            async for ev in runner.run_async(user_id=cliente_id, session_id=s.id, new_message=conteudo):
                if ev.usage_metadata:
                    item = obs.registrar_llm(ev.usage_metadata, MODEL, jornada, "chat_stream", (time.perf_counter() - inicio) * 1000)
                    yield linha({"tipo": "llm", "tokens_entrada": item["tokens_entrada"], "tokens_saida": item["tokens_saida"], "custo_usd": item["custo_usd"]})
                for fc in ev.get_function_calls():
                    if fc.name == "adk_request_confirmation" and fc.args:
                        original = fc.args.get("originalFunctionCall") or {}
                        hitl = {"request_id": fc.id, "tool": original.get("name"), "args": original.get("args") or {}, "hint": (fc.args.get("toolConfirmation") or {}).get("hint", "")}
                    else:
                        etapa = ETAPAS.get(fc.name)
                        if etapa and etapa != etapa_atual:   # a sequência só avança quando a cliente pediu a ação
                            etapa_atual = etapa
                            yield linha({"tipo": "etapa", "etapa": etapa})
                        yield linha({"tipo": "tool_call", "nome": fc.name, "args": fc.args or {}, "rotulo": ROTULOS_HITL.get(fc.name, fc.name)})
                for fr in ev.get_function_responses():
                    if fr.name != "adk_request_confirmation":
                        resp = fr.response if isinstance(fr.response, dict) else {}
                        yield linha({"tipo": "tool_result", "nome": fr.name, "ok": resp.get("ok", "erro" not in resp), "erro": resp.get("erro"),
                                     "explicacao": str(resp.get("explicacao", resp.get("erro", "")))[:300]})
                delta_ui = (ev.actions.state_delta or {}).get("ui") if ev.actions else None
                if delta_ui:
                    for bloco in delta_ui[vistos:] if len(delta_ui) >= vistos else delta_ui:
                        yield linha({"tipo": "card", "bloco": bloco})
                    vistos = len(delta_ui)
                if ev.is_final_response() and ev.content and ev.content.parts:
                    t = "".join(p.text or "" for p in ev.content.parts if p.text)
                    if t:
                        final = t
                        yield linha({"tipo": "texto", "texto": t})
    except Exception as e:  # noqa: BLE001 — nunca deixa a UI sem resposta
        log.exception("chat_stream falhou")
        yield linha({"tipo": "erro", "erro": str(e)[:300], "dica": _dica_operador(e),
                     "texto": "Não consegui responder agora. Nenhum valor foi inventado — pode tentar de novo ou falar com uma pessoa do time."})
    if not final and recusado:
        yield linha({"tipo": "texto", "texto": "Tudo bem, nada foi contratado. Quer ver outra opção ou tirar alguma dúvida?"})
    s2 = await sessoes.get_session(app_name=APP_NAME, user_id=cliente_id, session_id=sessao_id)
    estado = dict(s2.state) if s2 else {}
    if hitl:
        hitl = _hitl_com_sessao(_enriquecer_hitl(cliente_id, sessao_id, hitl), estado, cliente_id)
        obs.registrar_metrica("zera.hitl_pedido", 1, {"tool": str(hitl.get("tool"))})
        yield linha({"tipo": "etapa", "etapa": "confirmar"})
        yield linha({"tipo": "hitl", "hitl": hitl})
    elif conteudo is not None and any(p.function_response is not None for p in (conteudo.parts or [])) and not recusado:
        yield linha({"tipo": "etapa", "etapa": "acompanhar"})   # confirmação humana processada: acordo/respiro/amortização executados
    bloqueios = estado.get("bloqueios_guardrail") or []
    if len(bloqueios) > bloqueios_antes:
        yield linha({"tipo": "guardrail", "guardrail": bloqueios[-1]})   # observabilidade (a UI não mostra selo à cliente)
    c = _ctx(cliente_id)
    sugestoes = _sugestoes_chat(c)
    if estado.get("escalar_sugerido") or len(bloqueios) > bloqueios_antes:
        sugestoes = ["Quero falar com uma pessoa"] + [x for x in sugestoes if x != "Quero falar com uma pessoa"]
    yield linha({"tipo": "fim", "sugestoes": sugestoes, "finops": obs.custo_da_jornada(jornada),
                 "estado": {k: estado.get(k) for k in ("alucinacao_numerica", "bloqueios_consentimento", "vulneravel", "pii_redigida")},
                 "acordo": c.estado.get("acordo")})


@app.post("/chat/confirmar")
async def chat_confirmar(body: ConfirmarIn):
    """HITL: a cliente confirmou (ou recusou) no app -> o ADK retoma a tool pausada com a decisão humana."""
    s = await _sessao(body.cliente_id, body.sessao_id)
    ja_vistos = len(s.state.get("ui", []))
    bloqueios_antes = len(s.state.get("bloqueios_guardrail") or [])
    conteudo = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=body.request_id, name="adk_request_confirmation",
        response={"confirmed": body.confirmed, "payload": {"frase_cliente": body.frase, "canal": "app"}}))])
    obs.registrar_metrica("zera.hitl_resposta", 1, {"confirmed": str(body.confirmed)})
    resultado = await _rodar_agente(body.cliente_id, body.sessao_id, "", "chat_confirmar", conteudo=conteudo)
    if not resultado["texto"] and not body.confirmed:
        resultado["texto"] = "Tudo bem, nada foi contratado. Quer ver outra opção ou tirar alguma dúvida?"
    return await _resposta_chat(body.cliente_id, body.sessao_id, resultado, ja_vistos, bloqueios_antes)


@app.post("/simular_tempo")
async def simular_tempo(body: TempoIn):
    try:
        return Contexto.para(body.cliente_id).avancar_tempo(date.fromisoformat(body.ate))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/gatilhos/{cliente_id}")
async def gatilhos(cliente_id: str):
    c = Contexto.para(cliente_id)
    return {"hoje": c.estado["hoje"], "gatilhos": c.estado.get("gatilhos_pendentes", []), "acordo": c.estado.get("acordo"),
            "acordos": [a for a in c.estado.get("acordos", []) if a and a.get("status") == "ativo"]}


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
            "renda_media": p.renda_media, "renda_fonte": p.renda_fonte, "meses_com_renda": p.meses_com_renda,
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
    r = await _rodar_agente(cliente_id, body.sessao_id, pergunta, "explicar",
                            state_delta={"ultimos_numeros": rc["numeros_permitidos"] + hoje["numeros_permitidos"]})
    return {"texto": r["texto"]}


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
        r = await _rodar_agente(cliente_id, sessao_id, pergunta, "experiencia", state_delta={"ultimos_numeros": sorted(set(numeros_permitidos))})
        return r["texto"]
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
