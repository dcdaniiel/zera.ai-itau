"""Parâmetros de negócio do Zera.

Tudo que é "alavanca" de experimentação vive aqui e pode ser sobrescrito por
uma linha em `zera.politicas` no BigQuery (P1). Valores fictícios
para o hackathon — nunca use como política real do banco.
"""

from __future__ import annotations

from copy import deepcopy

POLITICA_PADRAO: dict = {
    # --- capacidade de pagamento ---
    "percentil_sobra": 25,          # sobra "segura" = percentil 25 da sobra mensal
    "colchao_pct": 0.05,            # colchão = 5% da renda mediana
    "fator_seguranca": 0.75,        # parcela máxima = 75% da sobra segura
    "limiar_mes_fraco": 0.50,       # mês fraco: sobra < 50% da mediana da sobra
    "respiros_max": 2,              # respiros por ano previstos no acordo
    # --- renegociação ---
    "taxa_mensal_renegociacao": 0.015,
    "prazo_max": 48,
    "prazo_padrao": 12,             # "renegociação padrão" usada como contraste
    # desconto sobre o saldo total, por faixa de dias de atraso (fictício)
    "faixas_desconto": [
        {"de": 0,   "ate": 30,     "avista": 0.05, "parcelado": 0.00},
        {"de": 31,  "ate": 90,     "avista": 0.20, "parcelado": 0.08},
        {"de": 91,  "ate": 180,    "avista": 0.35, "parcelado": 0.15},
        {"de": 181, "ate": 10**9,  "avista": 0.50, "parcelado": 0.25},
    ],
    "prazos_oferecidos": [12, 18, 24, 36],   # "braços" de renegociação por dívida
    "horizonte_manter_meses": 12,   # custo de "manter" uma dívida em dia = juros por 12 meses
    "cv_renda_irregular": 0.12,     # coeficiente de variação da renda a partir do qual o perfil é "renda irregular"
    "fator_conforto_renda_irregular": 0.70,  # parcela de conforto = 70% da parcela máxima para renda irregular
    "desconto_debito_automatico_pct": 0.02,  # desconto na parcela com débito automático (fictício)
    "desconto_amortizacao": 0.15,   # cada R$ 1 amortizado abate R$ 1/(1-0,15)
    "reserva_meses_colchao": 3,     # reserva sugerida = min(3 colchões, 30% do extra)
    "reserva_pct_extra": 0.30,
    # --- priorização ---
    "pesos_consequencia": {"negativacao": 1000.0, "corte_servico": 500.0, "garantia": 300.0, "nenhuma": 0.0},
    "dias_atraso_consequencia": 30,  # a consequência só pesa se já há atraso relevante
    # --- gatilhos ---
    "dias_atraso_pre_negativacao": 45,
    "d_menos": 3,
    "dinheiro_extra_pct_renda": 0.40,
    "dia_vencimento_padrao": 10,
}


def carregar_politica(sobrescritas: dict | None = None) -> dict:
    """Retorna a política padrão com sobrescritas (ex.: vindas do BigQuery)."""
    politica = deepcopy(POLITICA_PADRAO)
    if sobrescritas:
        politica.update(sobrescritas)
    return politica
