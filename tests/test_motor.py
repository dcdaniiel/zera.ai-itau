"""Testes do motor determinístico com a persona da demo (Cleide)."""

from datetime import date

import pytest

from dados.loader import carregar_perfil
from motor import (
    acionar_respiro,
    amortizar,
    calcular_capacidade,
    criar_acordo,
    detectar_gatilhos,
    numeros_de,
    percentil,
    priorizar_dividas,
    processar_vencimentos,
    simular_planos,
)


@pytest.fixture(scope="module")
def perfil():
    p, _ = carregar_perfil("cli_001")
    return p


@pytest.fixture(scope="module")
def capacidade(perfil):
    return calcular_capacidade(perfil)


def test_percentil_linear():
    assert percentil([1, 2, 3, 4], 50) == 2.5
    assert percentil([10], 25) == 10


def test_perfil_cleide(perfil):
    assert perfil.meses[0] == "2025-10" and perfil.meses[-1] == "2026-09"
    assert perfil.renda_mediana == 2325.0
    assert perfil.total_dividas == 6800.0
    assert perfil.custo_total_mensal == pytest.approx(641.5)
    assert perfil.essenciais_mediana == 1550.0


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


def test_planos_cabem_por_construcao(perfil, capacidade):
    sim = simular_planos(perfil, capacidade)
    planos = {p["id"]: p for p in sim["planos"]}
    assert planos["A"]["valor_avista"] == 5440.0 and planos["A"]["cabe"] is False
    for pid in ("B", "C"):
        assert planos[pid]["cabe"] is True
        assert planos[pid]["parcela"] <= capacidade.parcela_maxima
        assert planos[pid]["prazo"] <= 48
    assert len(planos["C"]["meses_em_que_nao_cabe"]) <= planos["C"]["respiros"]
    assert planos["C"]["parcela"] < planos["B"]["parcela"]
    padrao = sim["plano_padrao"]
    assert padrao["cabe"] is False and padrao["parcela"] > capacidade.parcela_maxima
    assert len(padrao["meses_em_que_nao_cabe"]) == 4
    assert sim["recomendado"] == "C"
    assert 5440.0 in sim["numeros_permitidos"]


def test_plano_a_cabe_com_dinheiro_extra(perfil, capacidade):
    sim = simular_planos(perfil, capacidade, dinheiro_extra=6000)
    assert sim["recomendado"] == "A"


def test_jornada_da_demo(perfil, capacidade):
    sim = simular_planos(perfil, capacidade)
    plano_c = next(p for p in sim["planos"] if p["id"] == "C")
    acordo = criar_acordo(perfil, plano_c, date(2026, 9, 26))
    assert acordo.proximo_vencimento == "2026-10-10" and acordo.status == "ativo"

    # salto 1: janeiro (mês fraco), D-3
    processar_vencimentos(acordo, date(2027, 1, 7))
    assert acordo.pagas == 3 and acordo.proximo_vencimento == "2027-01-10"
    gat = detectar_gatilhos(perfil, acordo, date(2027, 1, 7), sobra_prevista_mes=200.0)
    assert [g["tipo"] for g in gat] == ["risco_parcela"]
    r = acionar_respiro(acordo, date(2027, 1, 7))
    assert r["ok"] and r["mes_do_respiro"] == "2027-01" and acordo.respiros_usados == 1
    assert acordo.proximo_vencimento == "2027-02-10"

    # salto 2: maio, restituição do IR
    processar_vencimentos(acordo, date(2027, 5, 12))
    assert acordo.pagas == 7 and acordo.restantes == 18
    gat = detectar_gatilhos(perfil, acordo, date(2027, 5, 12), sobra_prevista_mes=650.0,
                            creditos_recentes=[{"valor": 1400.0, "descricao": "RESTITUICAO IRPF", "recorrente": False}])
    assert [g["tipo"] for g in gat] == ["dinheiro_extra"]
    sim_am = amortizar(acordo, 1400.0, capacidade, perfil, aplicar=False)
    assert sim_am["reserva_sugerida"] == 348.75 and sim_am["parcelas_a_menos"] == 5
    saldo_antes = acordo.saldo_devedor
    amortizar(acordo, 1400.0, capacidade, perfil, aplicar=True)
    assert acordo.saldo_devedor < saldo_antes and acordo.restantes == 13

    # segue até quitar
    processar_vencimentos(acordo, date(2030, 1, 1))
    assert acordo.status == "quitado" and acordo.saldo_devedor == 0.0


def test_respiro_esgota(perfil, capacidade):
    sim = simular_planos(perfil, capacidade)
    acordo = criar_acordo(perfil, next(p for p in sim["planos"] if p["id"] == "C"), date(2026, 9, 26))
    assert acionar_respiro(acordo)["ok"] and acionar_respiro(acordo)["ok"]
    assert acionar_respiro(acordo)["ok"] is False


def test_nao_cabe_em_48x_escala(perfil):
    cap = calcular_capacidade(perfil)
    cap.parcela_maxima = 50.0  # cliente sem folga
    sim = simular_planos(perfil, cap)
    assert sim["nenhum_plano_cabe"] is True
    assert all(p["cabe"] is False for p in sim["planos"])


def test_numeros_de_inclui_taxas_em_pct():
    ns = numeros_de({"taxa": 0.015, "valor": 10.5, "lista": [3], "numeros_permitidos": [999]})
    assert 1.5 in ns and 0.02 in ns and 10.5 in ns and 3.0 in ns and 999 not in ns
