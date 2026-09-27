"""Benefícios validados e claims permitidos (spec zera.ai §8, §10, §11, §16).

Regra: um claim quantitativo só existe se veio daqui. "R$ X a menos por mês" exige
proposed_monthly < current_monthly; "Economize R$ X" exige proposed_total < current_total.
Nunca derivar "economia" de "parcela menor".
"""

from __future__ import annotations

from .modelos import brl, r2

OBJETIVOS = {  # rótulo do motor -> objetivo da spec -> rótulo da interface
    "recomendado": ("BALANCED", "Mais equilibrada", "Equilibra o valor da parcela e o prazo."),
    "mais_folga": ("LOWER_MONTHLY_PAYMENT", "Menor parcela", "Mais espaço no seu orçamento."),
    "mais_rapido": ("SHORTER_TERM", "Terminar antes", "Menor prazo para quitar."),
    "mais_barato": ("LOWER_TOTAL_COST", "Menor custo total", "Paga menos no total."),
}
ORDEM_OBJETIVOS = ["BALANCED", "LOWER_MONTHLY_PAYMENT", "SHORTER_TERM", "LOWER_TOTAL_COST"]


def validar_beneficios(hoje: dict, opcao: dict) -> list[dict]:
    """Compara a nova opção com a situação atual e devolve só os benefícios comprováveis."""
    beneficios: list[dict] = []
    atual, proposto = hoje["pagamento_mensal"], opcao["parcela_mensal"]
    if proposto < atual:
        beneficios.append({"benefit_type": "LOWER_MONTHLY_PAYMENT", "current_monthly_payment": atual,
                           "proposed_monthly_payment": proposto, "monthly_difference": r2(atual - proposto)})
    if opcao["total_a_pagar"] < hoje["total_a_pagar"]:
        beneficios.append({"benefit_type": "LOWER_TOTAL_COST", "current_total_cost": hoje["total_a_pagar"],
                           "proposed_total_cost": opcao["total_a_pagar"], "total_difference": r2(hoje["total_a_pagar"] - opcao["total_a_pagar"])})
    if opcao.get("resolve_negativacao") and any(d.get("dias_atraso", 0) >= 30 for d in hoje.get("dividas", [])):
        beneficios.append({"benefit_type": "CLEAN_NAME", "dividas_em_atraso": [d["nome"] for d in hoje["dividas"] if d.get("dias_atraso", 0) >= 30]})
    if opcao.get("qtd_pagamentos", 1) < hoje.get("qtd_pagamentos", 1):
        beneficios.append({"benefit_type": "SINGLE_PAYMENT", "current_payments": hoje["qtd_pagamentos"], "proposed_payments": opcao.get("qtd_pagamentos", 1)})
    return beneficios


def beneficio_principal(beneficios: list[dict]) -> dict | None:
    prioridade = ["LOWER_MONTHLY_PAYMENT", "CLEAN_NAME", "LOWER_TOTAL_COST", "SINGLE_PAYMENT"]
    for tipo in prioridade:
        for b in beneficios:
            if b["benefit_type"] == tipo:
                return b
    return None


def claims(beneficios: list[dict]) -> list[str]:
    """Frases permitidas — cada uma nasce de um benefício validado."""
    frases = []
    for b in beneficios:
        if b["benefit_type"] == "LOWER_MONTHLY_PAYMENT":
            frases.append(f"{brl(b['monthly_difference'])} a menos por mês")
        elif b["benefit_type"] == "LOWER_TOTAL_COST":
            frases.append(f"Economize {brl(b['total_difference'])} no total")
        elif b["benefit_type"] == "CLEAN_NAME":
            frases.append("Suas dívidas em atraso saem do atraso")
        elif b["benefit_type"] == "SINGLE_PAYMENT":
            frases.append("Tudo em um único pagamento por mês")
    return frases


def tradeoffs(hoje: dict, opcao: dict) -> list[str]:
    """Trade-offs que precisam aparecer ANTES da decisão (spec §9, AT06)."""
    t = []
    menor_parcela = opcao["parcela_mensal"] < hoje["pagamento_mensal"]
    mais_tempo = opcao["prazo_meses"] > hoje["prazo_meses"]
    total_maior = opcao["total_a_pagar"] > hoje["total_a_pagar"]
    if menor_parcela and mais_tempo:
        t.append("Você paga menos por mês, mas por mais tempo.")
    if menor_parcela and total_maior:
        t.append("No total, você paga mais do que hoje.")
    if not menor_parcela and not mais_tempo:
        t.append("Você paga mais por mês, mas termina antes.")
    if opcao.get("usa_caixa", 0) > 0:
        t.append(f"Usa {brl(opcao['usa_caixa'])} do seu dinheiro extra agora.")
    return t


def objetivo_de(rotulos: list[str]) -> tuple[str, str, str]:
    for r in rotulos:
        if r in OBJETIVOS:
            return OBJETIVOS[r]
    return OBJETIVOS["recomendado"]


def criterio_recomendacao(opcao: dict, parcela_conforto: float, perfil_risco: str) -> list[str]:
    """Critérios explicáveis que sustentam recommended=true (definidos fora do LLM — AT07)."""
    c = [f"Parcela de {brl(opcao['parcela_mensal'])} fica dentro do que cabe no seu bolso (até {brl(parcela_conforto)})."]
    if perfil_risco == "renda_irregular":
        c.append("Como sua renda varia mês a mês, deixamos uma margem de segurança na parcela.")
    if opcao.get("resolve_negativacao"):
        c.append("Todas as dívidas em atraso entram no acordo e saem do atraso.")
    if opcao.get("reserva", 0) > 0:
        c.append(f"Sobram {brl(opcao['reserva'])} como reserva para imprevistos.")
    c.append("Entre as opções que cabem, é a de menor custo total.")
    return c
