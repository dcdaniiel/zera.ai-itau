"""Motor determinístico do Zera: capacidade, priorização, simulação, gatilhos."""

from .alocacao import coeficiente_variacao_renda, montar_cenarios, opcoes_da_divida
from .capacidade import calcular_capacidade, percentil
from .gatilhos import detectar_gatilhos
from .modelos import Acordo, Capacidade, Divida, PerfilFinanceiro, Plano
from .politicas import POLITICA_PADRAO, carregar_politica
from .priorizacao import priorizar_dividas
from .simulacao import (
    acionar_respiro,
    amortizar,
    criar_acordo,
    criar_acordo_de_cenario,
    numeros_de,
    processar_vencimentos,
    registrar_pagamento,
    simular_planos,
)

__all__ = [
    "Acordo", "Capacidade", "Divida", "PerfilFinanceiro", "Plano",
    "POLITICA_PADRAO", "carregar_politica", "percentil",
    "calcular_capacidade", "priorizar_dividas", "simular_planos", "criar_acordo", "criar_acordo_de_cenario",
    "montar_cenarios", "opcoes_da_divida", "coeficiente_variacao_renda",
    "registrar_pagamento", "acionar_respiro", "amortizar", "processar_vencimentos",
    "detectar_gatilhos", "numeros_de",
]
