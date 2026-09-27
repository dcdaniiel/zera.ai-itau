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

from zera_agent.agent import root_agent  # noqa: E402
from zera_agent.contexto import Contexto  # noqa: E402

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


# ---------- UI (produção): a API serve o build do Vite em / (mesmo serviço no Cloud Run) ----------
_UI_DIST = RAIZ / "ui" / "dist"
if _UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
