"""Parâmetros de negócio do Zera.

Tudo que é "alavanca" de experimentação vive aqui e pode ser sobrescrito por
uma linha em `zera.politicas` no BigQuery (P1). Valores fictícios
para o hackathon — nunca use como política real do banco (a área de crédito
define catálogo, regras e flexibilidade permitida — quadro de produto, item 15).
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
    # --- renegociação: princípio "ambos ganham" ---
    # O banco NÃO abre mão do principal: o saldo devedor entra integral no acordo. O que muda é a TAXA
    # (rotativo/cheque a 8–14% a.m. -> taxa de renegociação) e o PRAZO (12x…48x): a parcela do cliente cai,
    # o banco recupera o saldo e recebe juros ao longo de um prazo maior, e a dívida ganha data para acabar.
    "taxa_mensal_renegociacao": 0.018,           # 1,8% a.m. (fictício)
    "prazos_oferecidos": [12, 18, 24, 36, 48, 60],   # "braços" de renegociação — prazo maior = parcela menor
    "prazo_max": 60,
    "prazo_padrao": 12,             # "renegociação padrão" usada como contraste
    "instituicoes_renegociaveis": ["Itaú", "Itau", "itau"],   # dívidas de outras instituições: só quitar (ou manter)
    "usar_entrada": True,           # dinheiro extra (13º, FGTS, restituição) vira ENTRADA: quita/abate as dívidas mais caras
    "cv_renda_irregular": 0.12,     # coeficiente de variação da renda a partir do qual o perfil é "renda irregular"
    "fator_conforto_renda_irregular": 0.70,  # parcela de conforto = 70% da parcela máxima para renda irregular
    "desconto_debito_automatico_pct": 0.02,  # desconto na parcela com débito automático (fictício)
    "reserva_meses_colchao": 3,     # reserva sugerida ao amortizar = min(3 colchões, 30% do extra)
    "reserva_pct_extra": 0.30,
    # --- dados insuficientes / inferência crítica (quadro item 14: dados internos + o que a cliente confirma) ---
    # A pergunta "tem gasto fixo fora do extrato?" só aparece quando os próprios dados sugerem que falta algo:
    "pct_essenciais_minimo": 0.30,  # contas essenciais < 30% da renda média -> provável gasto fixo fora desta conta (aluguel, escola...)
    "pct_sobra_suspeita": 0.55,     # sobra típica > 55% da renda média -> idem
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


def instituicao_renegociavel(instituicao: str, politica: dict | None = None) -> bool:
    pol = politica or POLITICA_PADRAO
    return (instituicao or "Itaú").strip().lower() in {i.lower() for i in pol["instituicoes_renegociaveis"]}
