"""Priorização de dívidas por custo e consequência — não por quem cobra mais alto.

    score = custo_mensal (saldo × taxa) + peso_consequencia (se já há atraso relevante)
"""

from __future__ import annotations

from .modelos import PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO

NOMES = {
    "cartao_rotativo": "Cartão (rotativo)",
    "cheque_especial": "Cheque especial",
    "emprestimo": "Empréstimo pessoal",
    "crediario": "Crediário",
    "outro": "Outra dívida",
}


def priorizar_dividas(perfil: PerfilFinanceiro, politica: dict | None = None) -> dict:
    pol = politica or POLITICA_PADRAO
    pesos = pol["pesos_consequencia"]
    ordem = []
    for d in perfil.dividas:
        peso = pesos.get(d.consequencia, 0.0) if d.dias_atraso >= pol["dias_atraso_consequencia"] else 0.0
        score = d.custo_mensal + peso
        motivo = f"custa {d.custo_mensal:.2f} por mês ({d.taxa_mensal*100:.1f}% a.m.)"
        if peso > 0:
            motivo += f"; {d.dias_atraso} dias de atraso, risco de {d.consequencia.replace('_', ' ')}"
        ordem.append({
            "divida_id": d.divida_id,
            "produto": d.produto,
            "nome": NOMES.get(d.produto, d.produto),
            "saldo": d.saldo,
            "taxa_mensal": d.taxa_mensal,
            "custo_mensal": d.custo_mensal,
            "dias_atraso": d.dias_atraso,
            "consequencia": d.consequencia,
            "score": r2(score),
            "motivo": motivo,
        })
    ordem.sort(key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(ordem, start=1):
        item["prioridade"] = i
    return {
        "ordem": ordem,
        "total_dividas": perfil.total_dividas,
        "custo_total_mensal": perfil.custo_total_mensal,
        "explicacao": (
            "Ordenamos pelo que custa mais por mês e pelo que acontece se atrasar mais "
            "(negativação, corte de serviço), não por quem cobra mais alto."
        ),
    }
