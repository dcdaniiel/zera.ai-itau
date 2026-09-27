"""Fluxo ponta a ponta do agente com um modelo falso: valida tools, consentimento, gatilhos e guardrail de números."""

from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from tests.fake_llm import FakeLlm
from zera_agent import guardrails, prompts, tools
from zera_agent.contexto import Contexto

CLIENTE = "cli_001"


@pytest.fixture(autouse=True)
def estado_limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))
    Contexto.limpar_cache()
    yield
    Contexto.limpar_cache()


def _runner(roteiro: dict) -> tuple[InMemoryRunner, FakeLlm]:
    llm = FakeLlm(roteiro=roteiro, chamadas=[])
    agente = LlmAgent(
        name="zera", model=llm, instruction=prompts.ROOT, tools=tools.TODAS,
        before_model_callback=guardrails.guardrail_entrada,
        before_tool_callback=guardrails.exigir_consentimento,
        after_tool_callback=guardrails.registrar_numeros,
        after_model_callback=guardrails.guardrail_saida,
    )
    return InMemoryRunner(agent=agente, app_name="zera"), llm


async def _conversar(runner: InMemoryRunner, mensagens: list[str], confirmar: bool | None = None) -> tuple[list[str], dict]:
    """Conversa com o agente. Se uma tool com efeito pausar (HITL: adk_request_confirmation), responde como o app faria
    (confirmar=True/False); confirmar=None deixa pausado — nada executa."""
    sessao = await runner.session_service.create_session(app_name="zera", user_id=CLIENTE, state={"cliente_id": CLIENTE})
    respostas, pendentes = [], []

    async def rodar(conteudo):
        async for ev in runner.run_async(user_id=CLIENTE, session_id=sessao.id, new_message=conteudo):
            for fc in ev.get_function_calls():
                if fc.name == "adk_request_confirmation":
                    pendentes.append(fc.id)
            if ev.is_final_response() and ev.content and ev.content.parts:
                t = "".join(p.text or "" for p in ev.content.parts if p.text)
                if t:
                    respostas.append(t)

    for msg in mensagens:
        await rodar(types.Content(role="user", parts=[types.Part(text=msg)]))
        while pendentes and confirmar is not None:
            rid = pendentes.pop(0)
            await rodar(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                id=rid, name="adk_request_confirmation", response={"confirmed": confirmar, "payload": {"frase_cliente": "Confirmo" if confirmar else "não"}}))]))
    sessao = await runner.session_service.get_session(app_name="zera", user_id=CLIENTE, session_id=sessao.id)
    estado = dict(sessao.state)
    estado["_hitl_pendentes"] = pendentes
    return respostas, estado


def test_raio_x_e_guardrail_de_numeros():
    roteiro = {
        "quanto eu devo?": [
            ("call", "get_perfil_financeiro", {}),
            ("call", "priorizar_dividas", {}),
            ("text", "Cleide, você deve R$ 6.800,00 e a dívida cresce R$ 641,50 por mês. Primeiro o cartão (14% a.m.). "
                     "Aliás inventei que você tem R$ 999,99 de bônus."),
        ],
    }
    runner, llm = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quanto eu devo?"]))
    assert "999,99" not in respostas[-1] and "pessoa do time" in respostas[-1]   # número inventado nunca chega: acolhe e oferece uma pessoa
    assert estado["alucinacao_numerica"] == 1 and estado["escalar_sugerido"] is True   # só o 999,99 é estranho
    assert 6800.0 in estado["ultimos_numeros"] and 14.0 in estado["ultimos_numeros"]
    assert [b["tipo"] for b in estado["ui"]] == ["raio_x", "prioridades"]


def test_hitl_pausa_sem_confirmacao_e_executa_com_confirmacao():
    roteiro = {
        "quero o plano C": [
            ("call", "montar_cenarios", {"valor_extra": 0}),
            ("call", "fechar_acordo", {"plano_id": "C1"}),         # pausa: confirmação humana no app (HITL nativo do ADK)
            ("text", "Fechado: 36x de R$ 258,30, primeira parcela em 10/10."),
        ],
    }
    runner, _ = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quero o plano C"], confirmar=None))
    assert len(estado["_hitl_pendentes"]) == 1 and Contexto.para(CLIENTE).acordo is None       # pausado: nada executado
    Contexto.limpar_cache()
    runner, _ = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quero o plano C"], confirmar=False))
    assert Contexto.para(CLIENTE).acordo is None and estado["bloqueios_consentimento"] == 1    # recusou no app: não executa
    Contexto.limpar_cache()
    runner, _ = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quero o plano C"], confirmar=True))
    ctx = Contexto.para(CLIENTE)
    assert ctx.acordo is not None and ctx.acordo.status == "ativo" and ctx.acordo.plano_id == "C1" and ctx.acordo.parcela > 0
    assert ctx.estado["consentimentos"][-1]["canal"] == "hitl_app" and ctx.estado["consentimentos"][-1]["frase_cliente"] == "Confirmo"
    assert "258,30" in respostas[-1] and estado.get("alucinacao_numerica", 0) == 0   # número do acordo veio da tool


def test_gatilho_de_respiro_apos_avancar_tempo():
    # fecha acordo direto pelo motor e avança o relógio até D-3 de janeiro
    ctx = Contexto.para(CLIENTE)
    from motor import criar_acordo, simular_planos
    sim = simular_planos(ctx.perfil, ctx.capacidade, ctx.politica)
    ctx.salvar(criar_acordo(ctx.perfil, next(p for p in sim["planos"] if p["id"] == "C"), ctx.hoje))
    res = ctx.avancar_tempo(date(2027, 1, 7))
    assert [g["tipo"] for g in res["gatilhos"]] == ["risco_parcela", "dinheiro_extra"]   # 13º entrou em dezembro (roteiro da demo)

    roteiro = {
        "oi": [
            ("call", "status_acordo", {}),
            ("text", "Cleide, janeiro está apertado (sobra prevista R$ 200,00) e a parcela de R$ 303,04 vence dia 10. "
                     "Quer usar 1 dos seus 2 respiros?"),
        ],
        "quero sim": [
            ("call", "acionar_respiro", {}),                        # pausa -> confirmação no app -> executa
            ("text", "Feito: a parcela de janeiro foi para o fim. Próximo vencimento 10/02."),
        ],
    }
    runner, llm = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["oi", "quero sim"], confirmar=True))
    assert estado["gatilho"] == []                                     # gatilho consumido pela ação
    assert Contexto.para(CLIENTE).acordo.respiros_usados == 1
    assert Contexto.para(CLIENTE).estado["gatilhos_pendentes"] == []


def test_pii_redigida_e_vulnerabilidade():
    roteiro = {"meu cpf é 123.456.789-09 e não aguento mais": [("text", "Entendo. Quer falar com uma pessoa?")]}
    runner, llm = _runner(roteiro)
    # o FakeLlm recebe o texto já redigido, então o roteiro precisa casar com a versão redigida
    llm.roteiro = {"meu cpf é [CPF removido] e não aguento mais": [("text", "Entendo. Quer falar com uma pessoa?")]}
    respostas, estado = asyncio.run(_conversar(runner, ["meu cpf é 123.456.789-09 e não aguento mais"]))
    assert estado["pii_redigida"] == 1 and estado["vulneravel"] is True
    assert "pessoa" in respostas[-1]


def test_modo_estrito_substitui_numero_inventado(monkeypatch):
    monkeypatch.setenv("ZERA_STRICT_NUMEROS", "1")
    roteiro = {"quanto eu devo?": [("call", "get_perfil_financeiro", {}), ("text", "Você deve R$ 6.800,00 e ganhou R$ 123,45.")]}
    runner, llm = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quanto eu devo?"]))
    assert "123,45" not in respostas[-1] and "pessoa do time" in respostas[-1]
