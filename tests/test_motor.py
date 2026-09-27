"""Testes do motor determinístico (princípio "ambos ganham") com a persona da demo (Cleide)."""

from datetime import date

import pytest

from dados.loader import carregar_perfil
from motor import (
    acionar_respiro,
    alocar_entrada,
    amortizar,
    calcular_capacidade,
    criar_acordo,
    criar_acordo_de_cenario,
    detectar_gatilhos,
    montar_cenarios,
    numeros_de,
    percentil,
    pmt,
    priorizar_dividas,
    processar_vencimentos,
    projecao_mesmo_prazo,
    pv,
    resumo_cenario,
    simular_planos,
    situacao_hoje,
    termos,
)
from motor.beneficios import claims, tradeoffs, validar_beneficios
from motor.politicas import POLITICA_PADRAO


@pytest.fixture(scope="module")
def perfil():
    p, _ = carregar_perfil("cli_001")
    return p


@pytest.fixture(scope="module")
def capacidade(perfil):
    return calcular_capacidade(perfil)


@pytest.fixture(scope="module")
def hoje(perfil):
    return situacao_hoje(perfil)


def test_percentil_linear():
    assert percentil([1, 2, 3, 4], 50) == 2.5
    assert percentil([10], 25) == 10


def test_price_e_valor_presente_sao_inversos():
    parcela = pmt(6800, 0.018, 48)
    assert pv(parcela, 0.018, 48) == pytest.approx(6800, abs=0.01)


def test_perfil_cleide(perfil):
    assert perfil.meses[0] == "2025-10" and perfil.meses[-1] == "2026-09"
    assert perfil.renda_mediana == 2325.0 and not perfil.renda_desconhecida
    assert perfil.total_dividas == 6800.0
    assert perfil.custo_total_mensal == pytest.approx(641.5)
    assert perfil.essenciais_mediana == 1550.0
    assert perfil.persona is True and all(d.instituicao == "Itaú" for d in perfil.dividas)


def test_capacidade(perfil, capacidade):
    assert capacidade.sobra_p25 == 592.5
    assert capacidade.colchao == 116.25
    assert capacidade.sobra_segura == 476.25
    assert capacidade.parcela_maxima == 357.19
    assert capacidade.meses_fracos == ["2026-01", "2026-07"]
    assert capacidade.respiros_ano == 2


def test_priorizacao_por_custo_e_consequencia(perfil):
    ordem = priorizar_dividas(perfil)["ordem"]
    assert [o["produto"] for o in ordem] == ["cartao_rotativo", "emprestimo", "cheque_especial"]
    assert ordem[0]["custo_mensal"] == 448.0


# ---------- situação de hoje: sem "total a pagar" mágico ----------

def test_situacao_hoje_sem_projecao_magica(hoje):
    assert hoje["pagamento_mensal"] == 900.0 and hoje["qtd_pagamentos"] == 3
    assert hoje["saldo_devedor"] == 6800.0 and hoje["juros_mensais"] == 641.5
    assert hoje["prazo_indefinido"] is True and hoje["prazo_meses"] is None       # rotativo/cheque não têm fim
    assert hoje["taxa_maxima_pct"] == 14.0
    assert "total_a_pagar" not in hoje                                            # nunca mais "R$ 13.380"
    proj = hoje["projecoes"]["48"]                                                # mesmo prazo, condições de hoje
    assert proj["total"] == pytest.approx(48 * proj["parcela"], abs=0.5) and proj["juros"] > 20000


# ---------- cenários: banco preserva o principal, cliente paga menos por mês ----------

def test_cenarios_sem_extra_ambos_ganham(perfil, capacidade, hoje):
    r = montar_cenarios(perfil, capacidade, valor_extra=0.0)
    assert r["nenhum_cenario_cabe"] is False and r["perfil_risco"] == "renda_irregular"
    rec = r["cenarios"][0]
    assert "recomendado" in rec["rotulos"] and rec["prazo_meses"] == 48
    assert rec["saldo_original"] == 6800.0 and rec["saldo_consolidado"] == 6800.0        # sem desconto no principal
    assert rec["comprometimento_mensal"] == pytest.approx(212.77, abs=0.05) and rec["comprometimento_mensal"] <= r["parcela_conforto"]
    assert rec["custo_total"] == pytest.approx(6800 + rec["juros_acordo"], abs=0.05)     # total = saldo + juros do acordo
    assert rec["juros_acordo"] > 0 and rec["ganho_banco"] == rec["juros_acordo"]         # o banco ganha os juros
    assert rec["custo_total"] > 6800.0                                                   # nunca abaixo do saldo devedor
    assert rec["resolve_negativacao"] and all(a["acao"] == "renegociar_48x" for a in rec["acoes"])
    prazos = {c["prazo_meses"]: c for c in r["cenarios"]}
    assert set(prazos) == {36, 48, 60}                                                   # 12/18/24x não cabem em 3+ meses fracos
    assert "mais_barato" in prazos[36]["rotulos"] and "mais_folga" in prazos[60]["rotulos"]
    assert prazos[36]["custo_total"] < prazos[48]["custo_total"] < prazos[60]["custo_total"]
    assert prazos[60]["comprometimento_mensal"] < prazos[48]["comprometimento_mensal"] < hoje["pagamento_mensal"]


def test_dinheiro_extra_vira_entrada_nas_dividas_mais_caras(perfil, capacidade):
    entradas, sobra = alocar_entrada(perfil.dividas, 2683.75, POLITICA_PADRAO)
    assert entradas["dv_cheque"] == 900.0                                                # quita inteira a que cabe (8% a.m.)
    assert entradas["dv_cartao"] == pytest.approx(1783.75) and entradas["dv_emprestimo"] == 0.0   # abate a mais cara (14% a.m.)
    assert sobra == 0.0
    r = montar_cenarios(perfil, capacidade, valor_extra=2800.0)
    rec = r["cenarios"][0]
    assert r["reserva_minima"] == capacidade.colchao and rec["reserva"] == 116.25          # entrada atípica ≠ renda livre
    assert rec["prazo_meses"] == 24 and rec["saldo_consolidado"] == pytest.approx(4116.25)
    acoes = {a["divida_id"]: a["acao"] for a in rec["acoes"]}
    assert acoes["dv_cheque"] == "quitar" and acoes["dv_cartao"] == "renegociar_24x" and acoes["dv_emprestimo"] == "renegociar_24x"
    assert rec["custo_total"] == pytest.approx(rec["entrada"] + rec["total_parcelas"], abs=0.05)
    assert rec["custo_total"] == pytest.approx(6800 + rec["juros_acordo"], abs=0.05)
    rotulos = {rot for c in r["cenarios"] for rot in c["rotulos"]}
    assert {"recomendado", "mais_barato", "mais_folga", "guardar_extra"} <= rotulos      # inclusive "guardar o extra"


def test_beneficios_e_claims_so_do_que_e_comprovavel(perfil, capacidade, hoje):
    r = montar_cenarios(perfil, capacidade, valor_extra=0.0)
    rec = resumo_cenario(r["cenarios"][0], hoje)
    tipos = {b["benefit_type"] for b in validar_beneficios(hoje, rec)}
    assert {"LOWER_MONTHLY_PAYMENT", "LOWER_INTEREST_RATE", "CLEAN_NAME", "DEFINED_TERM", "SINGLE_PAYMENT", "LOWER_TOTAL_COST"} <= tipos
    frases = " ".join(claims(validar_beneficios(hoje, rec)))
    assert "R$ 687,23 a menos por mês" in frases and "condições de hoje" in frases
    t = tradeoffs(hoje, rec)
    assert any("por mais tempo" in x for x in t) and any("saldo integral" in x for x in t)   # transparência: banco preserva o principal
    assert rec["liberado_por_mes"] == pytest.approx(687.23, abs=0.05)


def test_termos_recalculados_com_debito_automatico(perfil, capacidade):
    r = montar_cenarios(perfil, capacidade, valor_extra=0.0)
    t = termos(r["cenarios"][0], perfil, date(2026, 9, 26), True)
    assert t["desconto_debito_automatico"] == pytest.approx(212.77 * 0.02, abs=0.01)
    assert t["parcela_mensal"] == pytest.approx(212.77 - t["desconto_debito_automatico"], abs=0.01)
    assert t["primeiro_vencimento"] == "2026-10-10" and t["ultimo_vencimento"] == "2030-09-10"
    assert t["total_a_pagar"] == pytest.approx(t["parcela_mensal"] * 48, abs=0.05)
    assert [d["acao"] for d in t["dividas_incluidas"]] == ["renegociar_48x"] * 3


def test_nenhum_cenario_cabe_traz_diagnostico(perfil):
    cap = calcular_capacidade(perfil)
    cap.parcela_maxima = 120.0
    r = montar_cenarios(perfil, cap, valor_extra=0.0)
    assert r["nenhum_cenario_cabe"] is True and r["recomendado"] is None
    d = r["diagnostico"]
    assert d["parcela_minima_possivel"] == pytest.approx(186.26, abs=0.05) and d["prazo_da_parcela_minima"] == 60
    assert d["entrada_necessaria"] > 0 and d["falta_por_mes"] == pytest.approx(66.26, abs=0.05)
    assert "60x" in r["motivo"]


def test_planos_consolidados_sem_desconto(perfil, capacidade):
    sim = simular_planos(perfil, capacidade)
    planos = {p["id"]: p for p in sim["planos"]}
    assert planos["A"]["valor_avista"] == 6800.0 and planos["A"]["cabe"] is False
    for pid in ("B", "C"):
        assert planos[pid]["cabe"] is True and planos[pid]["saldo_base"] == 6800.0 and planos[pid]["desconto_valor"] == 0.0
        assert planos[pid]["parcela"] <= capacidade.parcela_maxima
    assert sim["plano_padrao"]["cabe"] is False
    assert simular_planos(perfil, capacidade, dinheiro_extra=7000)["recomendado"] == "A"


def test_acordo_de_cenario_com_componentes_e_amortizacao(perfil, capacidade):
    r = montar_cenarios(perfil, capacidade, valor_extra=2800.0)
    ac = criar_acordo_de_cenario(perfil, r["cenarios"][0], date(2026, 9, 26))
    assert len(ac.quitacoes) == 1 and len(ac.componentes) == 2 and ac.respiros_max == 2
    assert ac.parcela == pytest.approx(sum(c["parcela"] for c in ac.componentes))
    assert ac.saldo_inicial == pytest.approx(4116.25)
    sim = amortizar(ac, 500.0, capacidade, perfil, aplicar=True)
    assert sim["ok"] and sim["abatimento_no_saldo"] <= 500.0 and sim["divida_alvo"] == "Empréstimo pessoal"
    processar_vencimentos(ac, date(2030, 1, 1))
    assert ac.status == "quitado" and ac.saldo_devedor == 0.0


def test_jornada_da_demo_com_respiro(perfil, capacidade):
    sim = simular_planos(perfil, capacidade)
    plano_c = next(p for p in sim["planos"] if p["id"] == "C")
    acordo = criar_acordo(perfil, plano_c, date(2026, 9, 26))
    assert acordo.proximo_vencimento == "2026-10-10" and acordo.status == "ativo"
    processar_vencimentos(acordo, date(2027, 1, 7))
    assert acordo.pagas == 3 and acordo.proximo_vencimento == "2027-01-10"
    gat = detectar_gatilhos(perfil, acordo, date(2027, 1, 7), sobra_prevista_mes=200.0)
    assert [g["tipo"] for g in gat] == ["risco_parcela"]
    r = acionar_respiro(acordo, date(2027, 1, 7))
    assert r["ok"] and r["mes_do_respiro"] == "2027-01" and acordo.proximo_vencimento == "2027-02-10"
    assert acionar_respiro(acordo)["ok"] and acionar_respiro(acordo)["ok"] is False


def test_gatilhos_entrada_no_rotativo_primeiro(perfil):
    gat = detectar_gatilhos(perfil, None, date(2026, 9, 26),
                            creditos_recentes=[{"valor": 2800.0, "descricao": "PIX RECEBIDO - 13 SALARIO", "recorrente": False}])
    assert [g["tipo"] for g in gat] == ["entrada_rotativo", "pre_negativacao", "dinheiro_extra"]
    assert gat[0]["ciclos"] == 2 and gat[0]["juros_mes"] == 448.0


def test_projecao_mesmo_prazo_e_numeros(perfil):
    p = projecao_mesmo_prazo(perfil, 24)
    assert p["total"] == pytest.approx(17757.84, abs=1) and p["juros"] == pytest.approx(10957.84, abs=1)
    ns = numeros_de({"taxa": 0.015, "valor": 10.5, "lista": [3], "numeros_permitidos": [999]})
    assert 1.5 in ns and 0.02 in ns and 10.5 in ns and 3.0 in ns and 999 not in ns
