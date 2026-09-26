"""Detector de gatilhos proativos (roda diariamente via Cloud Scheduler; na demo, pelo relógio de simulação).

    pre_negativacao : dívida com atraso >= 45 dias (ou 2º ciclo de rotativo)
    risco_parcela   : acordo ativo, vencimento em <= 3 dias e sobra prevista < parcela
    dinheiro_extra  : crédito atípico (>= 40% da renda mediana fora do padrão, ou 13º / IR / FGTS / bônus)
"""

from __future__ import annotations

import re
from datetime import date

from .modelos import Acordo, PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO
from .simulacao import numeros_de

PADRAO_EXTRA = re.compile(r"(?:RESTITUI|IRPF|IMPOSTO DE RENDA|FGTS|13|DECIMO|D[EÉ]CIMO|BONUS|BÔNUS|PLR)", re.IGNORECASE)


def detectar_gatilhos(perfil: PerfilFinanceiro, acordo: Acordo | None, hoje: date,
                      sobra_prevista_mes: float | None = None,
                      creditos_recentes: list[dict] | None = None,
                      politica: dict | None = None) -> list[dict]:
    pol = politica or POLITICA_PADRAO
    gatilhos: list[dict] = []

    # 1) pré-negativação (só faz sentido sem acordo ativo)
    if acordo is None or acordo.status != "ativo":
        for d in perfil.dividas:
            if d.dias_atraso >= pol["dias_atraso_pre_negativacao"]:
                gatilhos.append({
                    "tipo": "pre_negativacao",
                    "data": hoje.isoformat(),
                    "divida_id": d.divida_id,
                    "produto": d.produto,
                    "dias_atraso": d.dias_atraso,
                    "saldo": d.saldo,
                    "mensagem": f"{d.produto} com {d.dias_atraso} dias de atraso — risco de negativação.",
                })
                break

    # 2) risco de parcela (D-3)
    if acordo is not None and acordo.status == "ativo" and sobra_prevista_mes is not None:
        venc = date.fromisoformat(acordo.proximo_vencimento)
        dias = (venc - hoje).days
        if 0 <= dias <= pol["d_menos"] and sobra_prevista_mes < acordo.parcela:
            gatilhos.append({
                "tipo": "risco_parcela",
                "data": hoje.isoformat(),
                "vencimento": acordo.proximo_vencimento,
                "dias_para_vencimento": dias,
                "parcela": acordo.parcela,
                "sobra_prevista": r2(sobra_prevista_mes),
                "respiros_restantes": acordo.respiros_max - acordo.respiros_usados,
                "mensagem": f"Parcela de {acordo.parcela:.2f} vence em {dias} dias e a sobra prevista é {sobra_prevista_mes:.2f}.",
            })

    # 3) dinheiro extra
    limiar = pol["dinheiro_extra_pct_renda"] * perfil.renda_mediana
    for c in creditos_recentes or []:
        valor = float(c.get("valor", 0))
        desc = str(c.get("descricao", ""))
        atipico = valor >= limiar and not c.get("recorrente", False)
        if atipico or PADRAO_EXTRA.search(desc):
            gatilhos.append({
                "tipo": "dinheiro_extra",
                "data": hoje.isoformat(),
                "valor": r2(valor),
                "descricao": desc,
                "mensagem": f"Entrou {valor:.2f} ({desc}) — dá para amortizar ou quitar com desconto.",
            })

    for g in gatilhos:
        g["numeros_permitidos"] = numeros_de(g)
    return gatilhos
