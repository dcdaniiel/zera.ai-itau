"""Capacidade de pagamento — determinística e explicável.

    sobra_mensal[m]  = renda[m] − essenciais[m] − compromissos_fora_do_acordo[m]
    sobra_p25        = percentil 25 da sobra mensal (12 meses)
    colchao          = colchao_pct × renda_mediana
    sobra_segura     = max(0, sobra_p25 − colchao)
    parcela_maxima   = fator_seguranca × sobra_segura
    meses_fracos     = meses com sobra < limiar × mediana da sobra
    respiros_ano     = min(len(meses_fracos), respiros_max)
"""

from __future__ import annotations

from statistics import median

from .modelos import Capacidade, PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO


def percentil(valores: list[float], p: float) -> float:
    """Percentil com interpolação linear (mesmo método padrão do numpy)."""
    if not valores:
        raise ValueError("lista vazia")
    v = sorted(valores)
    if len(v) == 1:
        return float(v[0])
    pos = (len(v) - 1) * (p / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    frac = pos - lo
    return float(v[lo] + (v[hi] - v[lo]) * frac)


def calcular_capacidade(perfil: PerfilFinanceiro, politica: dict | None = None) -> Capacidade:
    pol = politica or POLITICA_PADRAO
    sobras = perfil.sobra_mensal
    sobra_p25 = r2(percentil(sobras, pol["percentil_sobra"]))
    sobra_med = r2(median(sobras))
    colchao = r2(pol["colchao_pct"] * perfil.renda_mediana)
    sobra_segura = r2(max(0.0, sobra_p25 - colchao))
    parcela_maxima = r2(pol["fator_seguranca"] * sobra_segura)
    limiar = pol["limiar_mes_fraco"] * sobra_med
    meses_fracos = [m for m, s in zip(perfil.meses, sobras) if s < limiar]
    respiros = min(len(meses_fracos), int(pol["respiros_max"]))
    explicacao = {
        "como_calculamos": (
            "Olhamos 12 meses de extrato: renda menos contas essenciais em cada mês. "
            "Pegamos um mês tipicamente apertado (percentil 25), tiramos um colchão de "
            f"{int(pol['colchao_pct']*100)}% da renda para imprevistos e usamos "
            f"{int(pol['fator_seguranca']*100)}% do que sobrou como parcela máxima."
        ),
        "renda_mediana": perfil.renda_mediana,
        "essenciais_mediana": perfil.essenciais_mediana,
        "sobra_mediana": sobra_med,
        "sobra_p25": sobra_p25,
        "colchao": colchao,
        "meses_fracos": meses_fracos,
        "limiar_mes_fraco": r2(limiar),
    }
    return Capacidade(
        sobra_p25=sobra_p25,
        colchao=colchao,
        sobra_segura=sobra_segura,
        parcela_maxima=parcela_maxima,
        meses_fracos=meses_fracos,
        respiros_ano=respiros,
        sobra_mediana=sobra_med,
        explicacao=explicacao,
    )
