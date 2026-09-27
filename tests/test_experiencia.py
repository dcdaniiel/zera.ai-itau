"""Acceptance tests da spec zera.ai (AT01–AT10) + garantias de fluxo ponta a ponta (sem beco sem saída).

Cenários do quadro de produto (item 13): oferta compatível; nenhuma oferta compatível; dados insuficientes;
correção de despesas; solicitação de condição inexistente; recusa/pausa; pedido de atendimento humano.
"""

from __future__ import annotations

import asyncio

import pytest

from zera_agent.contexto import Contexto
from zera_agent.experiencia import ACOES, ESTADOS, Experiencia

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
    r = ev(exp, "START")
    if r["state"] == "NEEDS_INFORMATION":          # a pergunta de gasto só aparece quando os dados sugerem (não é etapa fixa)
        r = ev(exp, "ANSWER", {"id": "NO"})
    return r


def pergunta(exp: Experiencia, texto: str) -> dict:
    return ev(exp, "ASK_QUESTION", {"text": texto})


# ---------- jornada principal (quadro item 11) ----------

def test_pergunta_de_gasto_so_aparece_quando_os_dados_sugerem():
    """A tela "tem gasto fixo fora do extrato?" não é etapa fixa: só entra quando essenciais/sobra destoam da renda."""
    from motor import sinais_gastos_invisiveis

    exp = _exp()
    assert sinais_gastos_invisiveis(exp.ctx.perfil, exp.ctx.politica) is None            # fixture: essenciais ~67% da renda
    r = ev(exp, "START")
    assert r["state"] == "SHOWING_OPTIONS"                                               # nada a confirmar -> direto às opções


def test_at01_nao_repete_renda_e_at02_pergunta_gasto_e_recalcula():
    exp = _exp()
    exp.ctx.politica["pct_essenciais_minimo"] = 0.90                                     # força o sinal (essenciais "baixos")
    r = ev(exp, "START")
    assert r["state"] == "NEEDS_INFORMATION" and r["response_type"] == "QUESTION" and r["question"] == "gasto_recorrente"
    assert r["sinal"]["motivos"] == ["essenciais_baixos"] and "R$" in r["content"]["description"]   # motivo com os números reais
    assert "renda" not in r["content"]["title"].lower()                                   # AT01: renda vem do extrato
    r = ev(exp, "ANSWER", {"id": "YES", "valor_mensal": 80, "descricao": "remédio"})     # nova despesa informada -> recálculo
    assert r["state"] == "SHOWING_OPTIONS" and r["option"]["term_months"] == 60         # a recomendação muda (48x -> 60x)
    assert Contexto.para(CLIENTE).estado["compromissos_extras"][0]["valor_mensal"] == 80
    ev(exp, "CANCEL")
    assert ev(exp, "START")["state"] == "SHOWING_OPTIONS"                                # não pergunta de novo


def test_contrato_estruturado_e_claims_validados_at05():
    exp = _exp()
    r = ate_opcoes(exp)
    assert r["response_type"] == "OPTION_DETAIL" and r["status"]["steps"][-1] == "Calculando opções"
    opt = r["option"]
    assert opt["recommended"] is True and opt["objective"] == "BALANCED" and opt["term_months"] == 48
    assert opt["principal"] == 6800.0 and opt["total_cost"] == pytest.approx(6800 + opt["interest_total"], abs=0.05)
    assert opt["bank_gain"] > 0 and opt["monthly_payment"] < r["current"]["pagamento_mensal"]
    tipos = {b["benefit_type"] for b in opt["benefits"]}
    assert "LOWER_MONTHLY_PAYMENT" in tipos and "a menos por mês" in " ".join(opt["claims"])
    assert r["current"]["prazo_indefinido"] is True and "total_a_pagar" not in r["current"]
    comp = ev(exp, "VIEW_OPTIONS")
    assert comp["response_type"] == "OPTIONS_COMPARISON" and len(comp["options"]) == 3
    assert {o["objective"] for o in comp["options"]} == {"BALANCED", "LOWER_MONTHLY_PAYMENT", "LOWER_TOTAL_COST"}
    assert sum(o["recommended"] for o in comp["options"]) == 1


def test_at06_tradeoffs_antes_da_decisao_e_at08_confirmacao_explicita():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "SELECT_OPTION", {"option_id": "lower_monthly_payment"})
    assert r["response_type"] == "TERMS_REVIEW" and r["state"] == "REVIEWING"
    assert any("por mais tempo" in t for t in r["tradeoffs"]) and any("saldo integral" in t for t in r["tradeoffs"])   # AT06
    assert r["terms"]["saldo_original"] == 6800.0 and r["terms"]["juros_acordo"] > 0
    assert Contexto.para(CLIENTE).estado["acordo"] is None                              # selecionar não contrata
    r = ev(exp, "CONTINUE")
    assert r["response_type"] == "QUESTION" and r["benefit"]["benefit_type"] == "AUTOPAY_DISCOUNT"
    r = ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_YES"})
    assert r["response_type"] == "CONFIRMATION_REQUEST" and r["requires_confirmation"] is True
    assert r["final_terms"]["debito_automatico"] is True and r["final_terms"]["desconto_debito_automatico"] > 0
    r = pergunta(exp, "sim, pode fechar")                                               # "sim" digitado NUNCA contrata
    assert r["response_type"] == "CONFIRMATION_REQUEST" and Contexto.para(CLIENTE).estado["acordo"] is None
    r = ev(exp, "CONFIRM", {"frase": "Confirmar contratação"})
    assert r["response_type"] == "SUCCESS" and r["state"] == "COMPLETED"                # AT08
    ctx = Contexto.para(CLIENTE)
    assert ctx.acordo is not None and ctx.acordo.status == "ativo" and ctx.estado["consentimentos"][-1]["acao"] == "fechar_acordo"
    assert r["result"]["monthly_reduction"] > 0 and r["agreement"]["parcela"] == r["final_terms"]["parcela_acordo"]
    r = ev(exp, "CONFIRM", {})                                                          # segundo clique não cria outro acordo
    assert r["response_type"] == "SUMMARY" and len(ctx.estado["consentimentos"]) == 1


def test_cancelar_volta_sem_contratar_e_pausa_por_texto():
    exp = _exp()
    ate_opcoes(exp)
    ev(exp, "SELECT_OPTION", {"option_id": "balanced"})
    ev(exp, "CONTINUE")
    ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_NO"})
    r = ev(exp, "CANCEL")
    assert r["state"] == "REVIEWING" and Contexto.para(CLIENTE).estado["acordo"] is None
    r = pergunta(exp, "agora não, depois eu vejo")
    assert r["state"] == "IDLE" and "sem pressa" in r["content"]["title"].lower() and "START" in r["allowed_actions"]


def test_at07_recomendacao_explicavel_sem_llm_e_com_llm():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "ASK_WHY", {"option_id": "balanced"})
    assert r["response_type"] == "TEXT" and r["state"] == "EXPLAINING" and r["llm"] is False
    assert len(r["criteria"]) >= 3 and "cabe no seu bolso" in r["criteria"][0] and r["quick_replies"]

    async def llm(pergunta_: str, numeros: list[float]) -> str:
        assert "sem pressão" in pergunta_ and numeros
        return "Destaquei essa opção porque a parcela cabe no seu mês e sobra reserva."

    exp2 = _exp(explicador=llm)
    ate_opcoes(exp2)
    r = pergunta(exp2, "por que essa opção?")                                           # texto livre -> ASK_WHY
    assert "cabe no seu mês" in r["content"]["description"] and r["llm"] is True


# ---------- proatividade ----------

def test_at03_at04_proatividade_precisa_de_permissao_e_beneficio():
    ctx = Contexto.para(CLIENTE)
    exp = Experiencia(ctx)
    r = exp.avaliar_proatividade()
    assert r["silent"] is False and r["response_type"] == "PROACTIVE_MESSAGE" and r["trigger"] == "entrada_rotativo"
    assert r["benefit"]["benefit_type"] == "LOWER_MONTHLY_PAYMENT" and "Cleide" in r["content"]["description"]
    ctx.estado["preferencias"]["avisar"] = False
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["proactive_permission"] is False          # AT04
    ctx.estado["preferencias"]["avisar"] = True
    ctx.capacidade.parcela_maxima = 1.0
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["benefit_validated"] is False             # AT03
    ctx.capacidade = __import__("motor").calcular_capacidade(ctx.perfil, ctx.politica)
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is False and r.get("repetida") is True
    ev(Experiencia(ctx), "DISMISS")
    r = Experiencia(ctx).avaliar_proatividade()
    assert r["silent"] is True and r["checks"]["contact_frequency_allowed"] is False


# ---------- exceções (quadro item 13): sem beco sem saída ----------

def test_at10_nenhuma_opcao_adequada_e_actionable():
    exp = _exp()
    exp.ctx.politica["pct_essenciais_minimo"] = 0.90                                     # força a pergunta de gasto
    ev(exp, "START")
    r = ev(exp, "ANSWER", {"id": "YES", "valor_mensal": 300})                           # gasto grande -> nada cabe
    assert r["state"] == "NO_SUITABLE_OPTION" and r["options"] == [] and r["diagnosis"]["entrada_necessaria"] > 0
    assert {"ADJUST", "ESCALATE", "RETRY"} <= set(r["allowed_actions"]) and len(r["quick_replies"]) >= 3
    r = pergunta(exp, "Ok me ajude com as opcoes.")                                      # o caso que nunca pode virar beco
    assert r["state"] == "NO_SUITABLE_OPTION" and r["quick_replies"] and "Não consegui responder" not in r["content"]["description"]
    r = ev(exp, "ADJUST", {"tipo": "remover_gasto"})                                     # correção de despesas
    assert r["state"] == "NEEDS_INFORMATION"
    r = ev(exp, "ANSWER", {"id": "NO"})
    assert r["state"] == "SHOWING_OPTIONS"
    exp2 = _exp()
    r = ev(exp2, "ADJUST", {"tipo": "gasto", "valor": 300})
    assert exp2.state == "NO_SUITABLE_OPTION"
    necessaria = r["diagnosis"]["entrada_necessaria"]                                    # o diagnóstico é acionável
    r = ev(exp2, "ADJUST", {"tipo": "dinheiro_extra", "valor": necessaria + 200})       # entrada faz caber
    assert r["state"] == "SHOWING_OPTIONS" and r["option"]["down_payment"] > 0


def test_escalonamento_registra_protocolo_e_mantem_saida():
    exp = _exp()
    ate_opcoes(exp)
    r = pergunta(exp, "quero falar com uma pessoa")
    assert "protocolo" in r["content"]["description"] and r["escalation"]["protocolo"].startswith("ZR-")
    assert Contexto.para(CLIENTE).estado["escalonamentos"][-1]["motivo"] == "pedido do cliente"
    assert {"HOME", "RETRY"} <= set(r["allowed_actions"])
    r = ev(exp, "RETRY")
    assert r["response_type"] == "OPTION_DETAIL"


def test_condicao_inexistente_e_prazo_fora_do_que_cabe():
    exp = _exp()
    ate_opcoes(exp)
    r = pergunta(exp, "tem como zerar os juros ou dar um desconto?")
    assert "não tenho desconto" in r["content"]["description"].lower() and "ESCALATE" in r["allowed_actions"]
    r = pergunta(exp, "quero em 24 vezes")
    assert "36x, 48x, 60x" in r["content"]["description"]
    r = pergunta(exp, "e em 60 meses?")
    assert r["response_type"] == "TERMS_REVIEW" and r["option"]["term_months"] == 60
    ev(exp, "VIEW_OPTIONS")
    r = pergunta(exp, "quero a de menor custo")
    assert r["response_type"] == "TERMS_REVIEW" and r["option"]["objective"] == "LOWER_TOTAL_COST"


def test_dados_insuficientes_pergunta_renda_uma_vez():
    ctx = Contexto.para(CLIENTE)
    ctx.perfil.renda_mensal = [0.0] * len(ctx.perfil.meses)
    ctx._renda_base = list(ctx.perfil.renda_mensal)
    ctx.capacidade = __import__("motor").calcular_capacidade(ctx.perfil, ctx.politica)
    assert ctx.perfil.renda_desconhecida
    exp = Experiencia(ctx)
    assert exp.avaliar_proatividade()["silent"] is True                                  # sem contexto, sem abordagem proativa
    r = ev(exp, "START")
    assert r["question"] == "renda"
    r = pergunta(exp, "uns 2.300 por mês")                                              # número no texto vira resposta
    assert ctx.perfil.renda_mediana == 2300.0
    if r.get("question") == "gasto_recorrente":                                          # só se os dados sugerirem gasto fora do extrato
        r = ev(exp, "ANSWER", {"id": "NO"})
    assert r["state"] == "SHOWING_OPTIONS"


def test_llm_indisponivel_nunca_vira_beco_sem_saida():
    async def llm_quebrado(pergunta_: str, numeros: list[float]) -> str:
        raise RuntimeError("Gemini indisponível")

    exp = _exp(explicador=llm_quebrado)
    ate_opcoes(exp)
    r = pergunta(exp, "quanto tempo demora para o nome limpar?")
    assert r["response_type"] == "TEXT" and r["reason"] == "llm_indisponivel"
    assert r["quick_replies"] and {"SELECT_OPTION", "VIEW_OPTIONS"} <= set(r["allowed_actions"])


def test_at09_falha_de_ferramenta_nao_inventa_dado(monkeypatch):
    exp = _exp()
    monkeypatch.setattr("zera_agent.experiencia.montar_cenarios", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("BigQuery indisponível")))
    r = ev(exp, "START")
    assert r["response_type"] == "ERROR" and r["state"] == "ERROR" and r["options"] == []
    assert "ESCALATE" in r["allowed_actions"] and "R$" not in r["content"]["description"]
    monkeypatch.undo()
    r = ev(exp, "RETRY")
    assert r["response_type"] == "OPTION_DETAIL"


def test_selecionar_card_nao_e_consentimento_e_confirm_fora_de_hora_falha():
    exp = _exp()
    ate_opcoes(exp)
    r = ev(exp, "CONFIRM", {})
    assert r["response_type"] == "ERROR" and Contexto.para(CLIENTE).estado["acordo"] is None
    assert r["quick_replies"]


def test_toda_acao_tem_transicao_em_todo_estado():
    """Nenhum estado × ação pode levantar exceção ou devolver resposta sem saída (allowed_actions vazio)."""
    for estado in ESTADOS:
        for acao in ACOES:
            exp = _exp()
            ate_opcoes(exp)
            exp.exp["state"] = estado
            r = ev(exp, acao, {"id": "NO", "option_id": "balanced", "text": "olá", "tipo": "gasto", "valor": 50})
            assert r["allowed_actions"], f"{estado} × {acao} sem saída"
            assert r["response_type"] != "ERROR" or acao == "CONFIRM", f"{estado} × {acao} -> ERROR"
            Contexto.limpar_cache()


# ---------- mais de uma opção contratada ----------

def test_mais_de_uma_opcao_contratada_jornada_nova_sobre_o_que_ficou_de_fora():
    """Depois do 1º acordo, uma dívida nova aparece no extrato: a cliente abre outra jornada só sobre o que ficou de fora;
    o 2º acordo respeita a parcela já contratada (vira compromisso fixo) e os dois ficam ativos."""
    from motor.modelos import Divida

    exp = _exp()
    ate_opcoes(exp)
    ctx = Contexto.para(CLIENTE)
    capacidade_antes = ctx.capacidade.parcela_maxima
    ev(exp, "SELECT_OPTION", {"option_id": "balanced"}); ev(exp, "CONTINUE"); ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_NO"})
    r = ev(exp, "CONFIRM", {"frase": "Confirmar contratação"})
    assert r["state"] == "COMPLETED" and len([a for a in ctx.acordos if a.status == "ativo"]) == 1
    parcela_1 = ctx.acordo.parcela
    assert ctx.capacidade.parcela_maxima < capacidade_antes                            # parcela contratada vira compromisso fixo
    assert ctx.perfil.dividas == []                                                      # tudo entrou no acordo: nada de fora
    r = ev(exp, "GET")
    assert r["response_type"] == "SUMMARY" and not any(q["id"] == "START_RESTANTE" for q in r["quick_replies"])
    assert ev(exp, "START", {"nova_jornada": True})["response_type"] == "SUMMARY"      # sem dívida de fora, não abre jornada

    # dívida nova no extrato (ex.: entrou no rotativo de novo) -> fica fora do acordo
    ctx._dividas_base.append(Divida(divida_id="d_nova", produto="cartao_rotativo", saldo=1500.0, taxa_mensal=0.14, instituicao="Itaú", fonte="derivada_extrato"))
    ctx._aplicar_acordos()
    assert [d.divida_id for d in ctx.perfil.dividas] == ["d_nova"] and len(ctx.dividas_em_acordo) == 3
    r = ev(exp, "GET")
    assert any(q["id"] == "START_RESTANTE" for q in r["quick_replies"]) and r["dividas_restantes"][0]["divida_id"] == "d_nova"

    r = ev(exp, "START", {"nova_jornada": True})
    if r["state"] == "NEEDS_INFORMATION":
        r = ev(exp, "ANSWER", {"id": "NO"})
    assert r["state"] == "SHOWING_OPTIONS" and all(a["divida_id"] == "d_nova" for o in r["options"] for a in o["actions"])
    ev(exp, "SELECT_OPTION", {"option_id": r["option"]["id"]}); ev(exp, "CONTINUE"); ev(exp, "SET_AUTOPAY", {"id": "AUTOPAY_NO"})
    r = ev(exp, "CONFIRM", {"frase": "Confirmar contratação"})
    assert r["state"] == "COMPLETED"
    ativos = [a for a in ctx.acordos if a.status == "ativo"]
    assert len(ativos) == 2 and ativos[0].parcela == parcela_1 and ativos[1].componentes[0]["divida_id"] == "d_nova"
    assert ctx.perfil.dividas == [] and ctx.estado["acordo"]["acordo_id"] == ativos[1].acordo_id
    r = ev(exp, "GET")
    assert r["content"]["title"] == "Suas opções contratadas" and r["parcela_total"] == round(ativos[0].parcela + ativos[1].parcela, 2)
    assert len(r["agreements"]) == 2
