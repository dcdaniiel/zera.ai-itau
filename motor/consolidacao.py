"""Visão "hoje vs nova opção" para o fluxo guiado do app (telas 1, 4, 5, 6, 7 e 8 do design).

Tudo determinístico: situação atual (quanto o cliente paga hoje), resumo de um cenário como
UM pagamento mensal, desconto de débito automático e termos da contratação (CET, 1º vencimento).
"""

from __future__ import annotations

from datetime import date

from .modelos import PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO
from .priorizacao import NOMES
from .simulacao import cet_anual, numeros_de, proximo_vencimento

ROTULO_UI = {
    "recomendado": {"titulo": "Mais equilíbrio", "descricao": "Equilibra o valor da parcela e o prazo."},
    "mais_folga": {"titulo": "Menor parcela", "descricao": "Mais espaço no seu orçamento."},
    "mais_rapido": {"titulo": "Terminar antes", "descricao": "Menor prazo para quitar."},
    "mais_barato": {"titulo": "Menor custo total", "descricao": "Paga menos no total."},
}


def pagamento_mensal_hoje(divida) -> float:
    """Quanto a dívida consome por mês hoje: a parcela, se existe; senão os juros que correm (rotativo, cheque)."""
    return r2(divida.parcela_atual) if divida.parcela_atual and divida.parcela_atual > 0 else divida.custo_mensal


def situacao_hoje(perfil: PerfilFinanceiro, politica: dict | None = None) -> dict:
    pol = politica or POLITICA_PADRAO
    h = pol["horizonte_manter_meses"]
    itens, total_mes, total_pagar, prazo = [], 0.0, 0.0, 0
    for d in perfil.dividas:
        mensal = pagamento_mensal_hoje(d)
        if d.parcela_atual and d.parcelas_restantes:
            restante = r2(d.parcela_atual * d.parcelas_restantes)
            prazo_d = d.parcelas_restantes
        else:  # rotativo/cheque: saldo + juros de 12 meses se nada mudar (estimativa conservadora, juros simples)
            restante = r2(d.saldo + d.saldo * d.taxa_mensal * h)
            prazo_d = h
        itens.append({"divida_id": d.divida_id, "nome": NOMES.get(d.produto, d.produto), "instituicao": d.instituicao,
                      "produto": d.produto, "saldo": d.saldo, "pagamento_mensal": mensal, "prazo_meses": prazo_d,
                      "total_estimado": restante, "dias_atraso": d.dias_atraso})
        total_mes += mensal
        total_pagar += restante
        prazo = max(prazo, prazo_d)
    resultado = {"pagamento_mensal": r2(total_mes), "qtd_pagamentos": len(itens), "prazo_meses": prazo,
                 "total_a_pagar": r2(total_pagar), "dividas": itens, "total_dividas": perfil.total_dividas,
                 "explicacao": f"Hoje suas dívidas comprometem {total_mes:.2f} por mês em {len(itens)} pagamentos."}
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def resumo_cenario(cenario: dict, hoje_ref: dict, politica: dict | None = None) -> dict:
    """Um cenário como 'nova opção' em UM pagamento mensal, com a comparação contra hoje."""
    pol = politica or POLITICA_PADRAO
    parcela = cenario["comprometimento_mensal"]
    total = cenario["custo_total"]
    prazo = cenario["prazo_meses"]
    livre = r2(hoje_ref["pagamento_mensal"] - parcela)
    rot = next((r for r in cenario.get("rotulos", []) if r in ROTULO_UI), "recomendado")
    desconto_da = r2(parcela * pol["desconto_debito_automatico_pct"])
    resultado = {
        "id": cenario["id"], "rotulos": cenario.get("rotulos", []), "titulo": ROTULO_UI[rot]["titulo"],
        "descricao": ROTULO_UI[rot]["descricao"], "recomendada": "recomendado" in cenario.get("rotulos", []),
        "parcela_mensal": parcela, "prazo_meses": prazo, "total_a_pagar": total, "qtd_pagamentos": 1,
        "liberado_por_mes": livre, "reserva": cenario.get("reserva", 0.0),
        "paga_menos_por_mes": livre > 0, "paga_por_mais_tempo": prazo > hoje_ref["prazo_meses"],
        "total_maior_que_hoje": total > hoje_ref["total_a_pagar"],
        "debito_automatico": {"desconto_mensal": desconto_da, "parcela_com_desconto": r2(parcela - desconto_da),
                              "total_com_desconto": r2(total - desconto_da * max(prazo, 1))},
        "acoes": cenario["acoes"],
        "hoje": {k: hoje_ref[k] for k in ("pagamento_mensal", "qtd_pagamentos", "prazo_meses", "total_a_pagar")},
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def termos(cenario: dict, perfil: PerfilFinanceiro, hoje: date, debito_automatico: bool, politica: dict | None = None) -> dict:
    pol = politica or POLITICA_PADRAO
    parcela = cenario["comprometimento_mensal"]
    prazo = cenario["prazo_meses"]
    desconto = r2(parcela * pol["desconto_debito_automatico_pct"]) if debito_automatico else 0.0
    parcela_final = r2(parcela - desconto)
    total = r2(cenario["custo_total"] - desconto * max(prazo, 1))
    venc = proximo_vencimento(hoje, perfil.dia_pagamento_preferido or pol["dia_vencimento_padrao"])
    incluidas = []
    for a in cenario["acoes"]:
        d = next((x for x in perfil.dividas if x.divida_id == a["divida_id"]), None)
        if d and a["acao"] != "manter":
            incluidas.append({"divida_id": d.divida_id, "nome": NOMES.get(d.produto, d.produto), "instituicao": d.instituicao,
                              "saldo": d.saldo, "acao": a["acao"], "parcela": a.get("parcela", 0.0), "prazo": a.get("prazo", 0),
                              "usa_caixa": a.get("usa_caixa", 0.0), "desconto_pct": a.get("desconto_pct", 0.0)})
    i = pol["taxa_mensal_renegociacao"]
    resultado = {
        "cenario_id": cenario["id"], "parcela_mensal": parcela_final, "desconto_debito_automatico": desconto,
        "prazo_meses": prazo, "total_a_pagar": total, "cet_mensal_pct": r2(i * 100), "cet_anual_pct": r2(cet_anual(i) * 100),
        "primeiro_vencimento": venc.isoformat(), "debito_automatico": debito_automatico, "dividas_incluidas": incluidas,
        "quitacoes": [x for x in incluidas if x["acao"] == "quitar"], "renegociacoes": [x for x in incluidas if x["acao"].startswith("renegociar")],
        "liberado_por_mes": None,
        "aviso": "Esta contratação só será concluída com a sua confirmação.",
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado
