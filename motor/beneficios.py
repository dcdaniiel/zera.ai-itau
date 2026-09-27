"""Benefícios validados e claims permitidos (spec zera.ai §8, §10, §11, §16).

Regra: um claim quantitativo só existe se veio daqui. "R$ X a menos por mês" exige
proposed_monthly < current_monthly; "R$ X a menos no total" exige comparar no MESMO prazo
(quitar em N meses nas condições de hoje vs. o acordo em N meses). Nunca derivar "economia" de "parcela menor".
"""

from __future__ import annotations

from .modelos import brl, r2

OBJETIVOS = {  # rótulo do motor -> objetivo da spec -> rótulo da interface
    "recomendado": ("BALANCED", "Mais equilibrada", "Cabe com folga no seu mês, com data para terminar."),
    "mais_folga": ("LOWER_MONTHLY_PAYMENT", "Menor parcela", "Mais espaço no seu orçamento."),
    "mais_rapido": ("SHORTER_TERM", "Terminar antes", "Menor prazo para quitar."),
    "mais_barato": ("LOWER_TOTAL_COST", "Menor custo total", "Paga menos juros no total."),
    "guardar_extra": ("KEEP_CASH", "Guardar o dinheiro extra", "Renegocia sem usar o dinheiro que entrou."),
}
ORDEM_OBJETIVOS = ["BALANCED", "LOWER_MONTHLY_PAYMENT", "SHORTER_TERM", "LOWER_TOTAL_COST", "INTERMEDIATE", "KEEP_CASH"]


def validar_beneficios(hoje: dict, opcao: dict) -> list[dict]:
    """Compara a nova opção com a situação atual e devolve só os benefícios comprováveis."""
    beneficios: list[dict] = []
    atual, proposto = hoje["pagamento_mensal"], opcao["parcela_mensal"]
    if proposto < atual:
        beneficios.append({"benefit_type": "LOWER_MONTHLY_PAYMENT", "current_monthly_payment": atual,
                           "proposed_monthly_payment": proposto, "monthly_difference": r2(atual - proposto)})
    proj = (hoje.get("projecoes") or {}).get(str(opcao.get("prazo_meses"))) or {}
    if proj.get("total") and opcao.get("total_a_pagar", 0) < proj["total"]:
        beneficios.append({"benefit_type": "LOWER_TOTAL_COST", "current_total_cost": proj["total"],
                           "proposed_total_cost": opcao["total_a_pagar"], "total_difference": r2(proj["total"] - opcao["total_a_pagar"]),
                           "basis": f"quitar em {opcao['prazo_meses']} meses nas condições de hoje"})
    if opcao.get("taxa_mensal") is not None and hoje.get("taxa_maxima") and opcao["taxa_mensal"] < hoje["taxa_maxima"]:
        beneficios.append({"benefit_type": "LOWER_INTEREST_RATE", "current_rate_pct": r2(hoje["taxa_maxima"] * 100),
                           "proposed_rate_pct": r2(opcao["taxa_mensal"] * 100)})
    if opcao.get("resolve_negativacao") and any(d.get("dias_atraso", 0) >= 30 for d in hoje.get("dividas", [])):
        beneficios.append({"benefit_type": "CLEAN_NAME", "dividas_em_atraso": [d["nome"] for d in hoje["dividas"] if d.get("dias_atraso", 0) >= 30]})
    if hoje.get("prazo_indefinido") and opcao.get("prazo_meses"):
        beneficios.append({"benefit_type": "DEFINED_TERM", "term_months": opcao["prazo_meses"]})
    if opcao.get("qtd_pagamentos", 1) < hoje.get("qtd_pagamentos", 1):
        beneficios.append({"benefit_type": "SINGLE_PAYMENT", "current_payments": hoje["qtd_pagamentos"], "proposed_payments": opcao.get("qtd_pagamentos", 1)})
    return beneficios


def beneficio_principal(beneficios: list[dict]) -> dict | None:
    prioridade = ["LOWER_MONTHLY_PAYMENT", "CLEAN_NAME", "LOWER_INTEREST_RATE", "LOWER_TOTAL_COST", "DEFINED_TERM", "SINGLE_PAYMENT"]
    for tipo in prioridade:
        for b in beneficios:
            if b["benefit_type"] == tipo:
                return b
    return None


def claims(beneficios: list[dict]) -> list[str]:
    """Frases permitidas — cada uma nasce de um benefício validado."""
    frases = []
    for b in beneficios:
        t = b["benefit_type"]
        if t == "LOWER_MONTHLY_PAYMENT":
            frases.append(f"{brl(b['monthly_difference'])} a menos por mês")
        elif t == "LOWER_TOTAL_COST":
            frases.append(f"{brl(b['total_difference'])} a menos do que {b['basis']}")
        elif t == "LOWER_INTEREST_RATE":
            frases.append(f"Juros de até {b['current_rate_pct']:.1f}% caem para {b['proposed_rate_pct']:.1f}% ao mês")
        elif t == "CLEAN_NAME":
            frases.append("Suas dívidas em atraso saem do atraso")
        elif t == "DEFINED_TERM":
            frases.append(f"Data certa para terminar: {b['term_months']} meses")
        elif t == "SINGLE_PAYMENT":
            frases.append("Tudo em um único pagamento por mês")
    return frases


def tradeoffs(hoje: dict, opcao: dict) -> list[str]:
    """Trade-offs que precisam aparecer ANTES da decisão (spec §9, AT06) — inclusive o que o banco ganha."""
    t = []
    menor_parcela = opcao["parcela_mensal"] < hoje["pagamento_mensal"]
    mais_tempo = bool(hoje.get("prazo_indefinido")) or (hoje.get("prazo_meses") or 0) < opcao["prazo_meses"]
    if menor_parcela and mais_tempo:
        t.append(f"Você paga menos por mês, mas por mais tempo ({opcao['prazo_meses']} meses)."
                 + (" Hoje o rotativo e o cheque especial não têm data para acabar." if hoje.get("prazo_indefinido") else ""))
    if not menor_parcela and not mais_tempo:
        t.append("Você paga mais por mês, mas termina antes.")
    if opcao.get("juros_acordo", 0) > 0:
        t.append(f"Ao longo do acordo você paga {brl(opcao['juros_acordo'])} de juros (taxa de {opcao.get('taxa_mensal_pct', 0):.1f}% ao mês). "
                 f"Hoje são {brl(hoje.get('juros_mensais', 0))} por mês só de juros, e o saldo quase não diminui.")
    if opcao.get("entrada", 0) > 0:
        t.append(f"Usa {brl(opcao['entrada'])} do seu dinheiro extra como entrada, o que reduz a parcela"
                 + (f" (fica {brl(opcao['reserva'])} de reserva)." if opcao.get("reserva", 0) > 0 else "."))
    if opcao.get("saldo_mantido", 0) > 0:
        t.append("Dívidas de outras instituições não entram no acordo: a parcela delas continua saindo por fora.")
    t.append(f"O banco recebe o saldo integral de {brl(opcao.get('saldo_original', 0))} mais os juros do acordo — "
             "ninguém abre mão do principal; o que muda é a taxa e o prazo.")
    return t


def objetivo_de(rotulos: list[str], prazo: int | None = None) -> tuple[str, str, str]:
    for r in rotulos:
        if r in OBJETIVOS:
            return OBJETIVOS[r]
    return ("INTERMEDIATE", f"{prazo} meses" if prazo else "Alternativa", "Entre a menor parcela e o menor custo total.")


def criterio_recomendacao(opcao: dict, parcela_conforto: float, perfil_risco: str) -> list[str]:
    """Critérios explicáveis que sustentam recommended=true (definidos fora do LLM — AT07)."""
    c = [f"Parcela de {brl(opcao['parcela_mensal'])} fica dentro do que cabe no seu bolso (até {brl(parcela_conforto)})."]
    if perfil_risco == "renda_irregular":
        c.append("Como sua renda varia mês a mês, deixamos uma margem de segurança na parcela.")
    if opcao.get("resolve_negativacao"):
        c.append("Todas as dívidas em atraso entram no acordo e saem do atraso.")
    if opcao.get("reserva", 0) > 0:
        c.append(f"Sobram {brl(opcao['reserva'])} como reserva para imprevistos.")
    if opcao.get("entrada", 0) > 0:
        c.append(f"Seu dinheiro extra entra como entrada ({brl(opcao['entrada'])}) nas dívidas mais caras e derruba a parcela.")
    c.append("Entre as opções que cabem com folga, é a de menor prazo — e por isso a de menor custo total.")
    return c
