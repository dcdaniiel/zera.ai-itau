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
        before_model_callback=guardrails.antes_do_modelo,
        before_tool_callback=guardrails.exigir_consentimento,
        after_tool_callback=guardrails.registrar_numeros,
        after_model_callback=guardrails.checar_numeros,
    )
    return InMemoryRunner(agent=agente, app_name="zera"), llm


async def _conversar(runner: InMemoryRunner, mensagens: list[str]) -> tuple[list[str], dict]:
    sessao = await runner.session_service.create_session(app_name="zera", user_id=CLIENTE, state={"cliente_id": CLIENTE})
    respostas = []
    for msg in mensagens:
        conteudo = types.Content(role="user", parts=[types.Part(text=msg)])
        async for ev in runner.run_async(user_id=CLIENTE, session_id=sessao.id, new_message=conteudo):
            if ev.is_final_response() and ev.content and ev.content.parts:
                respostas.append("".join(p.text or "" for p in ev.content.parts if p.text))
    sessao = await runner.session_service.get_session(app_name="zera", user_id=CLIENTE, session_id=sessao.id)
    return respostas, dict(sessao.state)


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
    assert "6.800,00" in respostas[-1]
    assert estado["alucinacao_numerica"] == 1          # só o 999,99 é estranho
    assert 6800.0 in estado["ultimos_numeros"] and 14.0 in estado["ultimos_numeros"]
    assert [b["tipo"] for b in estado["ui"]] == ["raio_x", "prioridades"]


def test_consentimento_bloqueia_e_libera():
    roteiro = {
        "quero o plano C": [
            ("call", "simular_planos", {}),
            ("call", "fechar_acordo", {"plano_id": "C"}),          # bloqueado: sem consentimento
            ("text", "Você confirma que quer fechar o plano C?"),
        ],
        "sim, confirmo o plano C": [
            ("call", "registrar_consentimento", {"acao": "fechar_acordo", "frase_cliente": "sim, confirmo o plano C"}),
            ("call", "fechar_acordo", {"plano_id": "C"}),
            ("text", "Fechado: 25x de R$ 301,94, primeira parcela em 10/10."),
        ],
    }
    runner, llm = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["quero o plano C", "sim, confirmo o plano C"]))
    assert estado["bloqueios_consentimento"] == 1
    ctx = Contexto.para(CLIENTE)
    assert ctx.acordo is not None and ctx.acordo.status == "ativo" and ctx.acordo.parcela == 301.94
    assert ctx.estado["consentimentos"][0]["frase_cliente"] == "sim, confirmo o plano C"
    assert estado["consentimento"] == {}             # consentimento é de uso único
    assert estado["alucinacao_numerica"] == 0 if "alucinacao_numerica" in estado else True


def test_gatilho_de_respiro_apos_avancar_tempo():
    # fecha acordo direto pelo motor e avança o relógio até D-3 de janeiro
    ctx = Contexto.para(CLIENTE)
    from motor import criar_acordo, simular_planos
    sim = simular_planos(ctx.perfil, ctx.capacidade, ctx.politica)
    ctx.salvar(criar_acordo(ctx.perfil, next(p for p in sim["planos"] if p["id"] == "C"), ctx.hoje))
    res = ctx.avancar_tempo(date(2027, 1, 7))
    assert [g["tipo"] for g in res["gatilhos"]] == ["risco_parcela"]

    roteiro = {
        "oi": [
            ("call", "status_acordo", {}),
            ("text", "Cleide, janeiro está apertado (sobra prevista R$ 200,00) e a parcela de R$ 301,94 vence dia 10. "
                     "Quer usar 1 dos seus 2 respiros?"),
        ],
        "quero sim": [
            ("call", "registrar_consentimento", {"acao": "acionar_respiro", "frase_cliente": "quero sim"}),
            ("call", "acionar_respiro", {}),
            ("text", "Feito: a parcela de janeiro foi para o fim. Próximo vencimento 10/02."),
        ],
    }
    runner, llm = _runner(roteiro)
    respostas, estado = asyncio.run(_conversar(runner, ["oi", "quero sim"]))
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
    assert "[valor a confirmar]" in respostas[-1] and "6.800,00" in respostas[-1]
