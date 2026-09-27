"""Acceptance tests da spec zera.ai (AT01–AT10) sobre o orquestrador determinístico da experiência."""

from __future__ import annotations

import asyncio

import pytest

from zera_agent.contexto import Contexto
from zera_agent.experiencia import Experiencia

CLIENTE = "cli_001"


@pytest.fixture(autouse=True)
def estado_limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))
    Contexto.limpar_cache()
    yield
    Contexto.limpar_cache()


def _exp(explicador=None) -> Experiencia:
    return Experiencia(Contexto.para(CLIENTE), explicador=explicador)


def ev(exp: Experiencia, acao: str, payload: dict | None = None) -> dict:
    return asyncio.run(exp.evento(acao, payload or {}))


def ate_opcoes(exp: Experiencia) -> dict:
    ev(exp, "START")
    return ev(exp, "ANSWER", {"id": "NO"})


def test_at01_nao_repete_pergunta_de_renda_e_at02_pergunta_gasto_critico():
    exp = _exp()
    r = ev(exp, "START")
    assert r["state"] == "NEEDS_INFORMATION" and r["response_type"] == "QUESTION"      # AT02: pergunta antes de recomendar
    assert "renda" not in r["content"]["description"].lower()                           # AT01: renda vem do extrato, não pergunta
    r = ev(exp, "ANSWER", {"id": "YES", "valor_mensal": 150, "descricao": "remédio"})
    assert r["state"] == "SHOWING_OPTIONS"
    assert Contexto.para(CLIENTE).estado["compromissos_extras"][0]["valor_mensal"] == 150
    # segunda rodada: não pergunta de novo
    ev(exp, "CANCEL")
    r = ev(exp, "START")
    assert r["state"] == "SHOWING_OPTIONS"


def test_contrato_estruturado_e_claims_validados_at05():
    exp = _exp()
    r = ate_opcoes(exp)
    assert r["response_type"] == "OPTION_DETAIL" and r["allowed_actions"] == ["SELECT_OPTION", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION"]
    assert r["status"]["steps"][-1] == "Calculando opções"
    opt = r["option"]
    assert opt["recommended"] is True and opt["objective"] == "BALANCED"
    tipos = {b["benefit_type"] for b in opt["benefits"]}
    assert "LOWER_MONTHLY_PAYMENT" in tipos                                              # parcela menor que hoje
    claims = " ".join(opt["claims"])
    assert "a menos por mês" in claims
    if "LOWER_TOTAL_COST" not in tipos:
        assert "Economize" not in claims                                                # AT05: sem custo menor, sem "economize"
    comp = ev(exp, "VIEW_OPTIONS")
    assert comp["response_type"] == "OPTIONS_COMPARISON" and len(comp["options"]) >= 3
    assert {o["objective"] for o in comp["options"]} >= {"BALANCED", "LOWER_MONTHLY_PAYMENT", "SHORTER_TERM"}
    assert sum(o["recommended"] for o in comp["options"]) == 1


def test_at06_tradeoffs_antes_da_decisao_e_at08_confirmacao_explicita():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "SELECT_OPTION", {"option_id": "lower_monthly_payment"})
    assert r["response_type"] == "TERMS_REVIEW" and r["state"] == "REVIEWING"
    assert any("por mais tempo" in t for t in r["tradeoffs"])                           # AT06
    assert Contexto.para(CLIENTE).estado["acordo"] is None                              # selecionar não contrata
    r = ev(exp, "CONTINUE")
    assert r["response_type"] == "QUESTION" and r["benefit"]["benefit_type"] == "AUTOPAY_DISCOUNT"
    r = ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_YES"})
    assert r["response_type"] == "CONFIRMATION_REQUEST" and r["requires_confirmation"] is True
    assert r["final_terms"]["debito_automatico"] is True and r["final_terms"]["desconto_debito_automatico"] > 0
    assert Contexto.para(CLIENTE).estado["acordo"] is None                              # ainda não contratou
    r = ev(exp, "CONFIRM", {"frase": "Confirmar contratação"})
    assert r["response_type"] == "SUCCESS" and r["state"] == "COMPLETED"                # AT08
    ctx = Contexto.para(CLIENTE)
    assert ctx.acordo is not None and ctx.acordo.status == "ativo"
    assert ctx.estado["consentimentos"][-1]["acao"] == "fechar_acordo"
    assert r["result"]["monthly_reduction"] > 0 and r["agreement"]["parcela"] == r["final_terms"]["parcela_mensal"]


def test_cancelar_volta_sem_contratar():
    exp = _exp()
    ate_opcoes(exp)
    ev(exp, "SELECT_OPTION", {"option_id": "balanced"})
    ev(exp, "CONTINUE")
    ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_NO"})
    r = ev(exp, "CANCEL")
    assert r["state"] == "REVIEWING" and Contexto.para(CLIENTE).estado["acordo"] is None


def test_at07_recomendacao_explicavel_sem_llm_e_com_llm():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "ASK_WHY", {"option_id": "balanced"})
    assert r["response_type"] == "TEXT" and r["state"] == "EXPLAINING"
    assert len(r["criteria"]) >= 3 and "cabe no seu bolso" in r["criteria"][0]

    async def llm(pergunta: str, numeros: list[float]) -> str:
        assert "sem pressão" in pergunta and numeros
        return "Destaquei essa opção porque a parcela cabe no seu mês e sobra reserva."

    exp2 = _exp(explicador=llm)
    r = ev(exp2, "ASK_WHY", {})
    assert "cabe no seu mês" in r["content"]["description"]


def test_at03_at04_proatividade_precisa_de_permissao_e_beneficio():
    ctx = Contexto.para(CLIENTE)
    exp = Experiencia(ctx)
    r = exp.avaliar_proatividade()
    assert r["silent"] is False and r["response_type"] == "PROACTIVE_MESSAGE" and r["benefit"]["benefit_type"] == "LOWER_MONTHLY_PAYMENT"
    # AT04: sem permissão -> silêncio, mesmo com oportunidade
    ctx.estado["preferencias"]["avisar"] = False
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["proactive_permission"] is False
    # AT03: gatilho sem oportunidade -> silêncio
    ctx.estado["preferencias"]["avisar"] = True
    ctx.capacidade.parcela_maxima = 1.0   # nada cabe -> nenhum benefício validado
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["benefit_validated"] is False
    # a mensagem já enviada hoje continua visível (idempotente) enquanto não for dispensada
    ctx.capacidade = __import__("motor").calcular_capacidade(ctx.perfil, ctx.politica)
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is False and r.get("repetida") is True
    # dispensada -> frequência: já contatado hoje -> silêncio (não insiste no mesmo dia)
    ev(Experiencia(ctx), "DISMISS")
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["contact_frequency_allowed"] is False


def test_at10_nenhuma_opcao_adequada_nao_forca_oferta():
    ctx = Contexto.para(CLIENTE)
    ctx.capacidade.parcela_maxima = 1.0
    exp = Experiencia(ctx)
    ev(exp, "START")
    r = ev(exp, "ANSWER", {"id": "NO"})
    assert r["state"] == "NO_SUITABLE_OPTION" and r["options"] == []
    assert "ESCALATE" in r["allowed_actions"]


def test_at09_falha_de_ferramenta_nao_inventa_dado(monkeypatch):
    exp = _exp()
    ev(exp, "START")
    monkeypatch.setattr("zera_agent.experiencia.montar_cenarios", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("BigQuery indisponível")))
    r = ev(exp, "ANSWER", {"id": "NO"})
    assert r["response_type"] == "ERROR" and r["state"] == "ERROR" and r["options"] == []
    assert "ESCALATE" in r["allowed_actions"] and "R$" not in r["content"]["description"]


def test_selecionar_card_nao_e_consentimento_e_confirm_fora_de_hora_falha():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "CONFIRM", {})
    assert r["response_type"] == "ERROR" and Contexto.para(CLIENTE).estado["acordo"] is None
