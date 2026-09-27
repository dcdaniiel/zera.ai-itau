"""Detector de gatilhos proativos (P1: scheduled query diária no BigQuery + Pub/Sub; na demo, pelo relógio de simulação).

    entrada_rotativo : cartão entrou no rotativo (caso de uso principal do quadro de produto, item 11)
    pre_negativacao  : dívida com atraso >= 45 dias
    risco_parcela    : acordo ativo, vencimento em <= 3 dias e sobra prevista < parcela
    dinheiro_extra   : crédito atípico (>= 40% da renda mediana fora do padrão, ou 13º / IR / FGTS / bônus)

Um gatilho NUNCA vira mensagem sozinho: a experiência ainda valida permissão, contexto, oportunidade,
benefício, ação disponível e frequência de contato (spec §7) antes de falar com a cliente.
"""

from __future__ import annotations

import re
from datetime import date

from .modelos import Acordo, PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO
from .simulacao import numeros_de

PADRAO_EXTRA = re.compile(r"(?:RESTITUI|IRPF|IMPOSTO DE RENDA|FGTS|13|DECIMO|D[EÉ]CIMO|BONUS|BÔNUS|PLR)", re.IGNORECASE)
ORDEM_PRIORIDADE = {"entrada_rotativo": 0, "pre_negativacao": 1, "risco_parcela": 2, "dinheiro_extra": 3}


def detectar_gatilhos(perfil: PerfilFinanceiro, acordo: Acordo | None, hoje: date,
                      sobra_prevista_mes: float | None = None,
                      creditos_recentes: list[dict] | None = None,
                      politica: dict | None = None) -> list[dict]:
    pol = politica or POLITICA_PADRAO
    gatilhos: list[dict] = []
    sem_acordo = acordo is None or acordo.status != "ativo"

    # 0) entrada no rotativo (só faz sentido sem acordo ativo)
    if sem_acordo:
        for d in perfil.dividas:
            if d.produto == "cartao_rotativo" and d.saldo > 0:
                ciclos = max(1, d.dias_atraso // 30) if d.dias_atraso else 1
                gatilhos.append({
                    "tipo": "entrada_rotativo", "data": hoje.isoformat(), "divida_id": d.divida_id, "produto": d.produto,
                    "saldo": d.saldo, "taxa_mensal": d.taxa_mensal, "ciclos": ciclos, "juros_mes": d.custo_mensal,
                    "mensagem": (f"Cartão entrou no rotativo ({ciclos}º ciclo): {d.saldo:.2f} a {d.taxa_mensal*100:.0f}% a.m. "
                                 f"custam {d.custo_mensal:.2f} por mês só de juros."),
                })
                break

    # 1) pré-negativação
    if sem_acordo:
        for d in perfil.dividas:
            if d.dias_atraso >= pol["dias_atraso_pre_negativacao"]:
                gatilhos.append({
                    "tipo": "pre_negativacao", "data": hoje.isoformat(), "divida_id": d.divida_id, "produto": d.produto,
                    "dias_atraso": d.dias_atraso, "saldo": d.saldo,
                    "mensagem": f"{d.produto} com {d.dias_atraso} dias de atraso — risco de negativação.",
                })
                break

    # 2) risco de parcela (D-3)
    if acordo is not None and acordo.status == "ativo" and sobra_prevista_mes is not None:
        venc = date.fromisoformat(acordo.proximo_vencimento)
        dias = (venc - hoje).days
        if 0 <= dias <= pol["d_menos"] and sobra_prevista_mes < acordo.parcela:
            gatilhos.append({
                "tipo": "risco_parcela", "data": hoje.isoformat(), "vencimento": acordo.proximo_vencimento,
                "dias_para_vencimento": dias, "parcela": acordo.parcela, "sobra_prevista": r2(sobra_prevista_mes),
                "respiros_restantes": acordo.respiros_max - acordo.respiros_usados,
                "mensagem": f"Parcela de {acordo.parcela:.2f} vence em {dias} dias e a sobra prevista é {sobra_prevista_mes:.2f}.",
            })

    # 3) dinheiro extra
    limiar = pol["dinheiro_extra_pct_renda"] * perfil.renda_mediana
    for c in creditos_recentes or []:
        valor = float(c.get("valor", 0))
        desc = str(c.get("descricao", ""))
        atipico = valor >= limiar and not c.get("recorrente", False) and limiar > 0
        if atipico or PADRAO_EXTRA.search(desc):
            gatilhos.append({
                "tipo": "dinheiro_extra", "data": hoje.isoformat(), "valor": r2(valor), "descricao": desc,
                "mensagem": f"Entrou {valor:.2f} ({desc}) — dá para quitar ou abater as dívidas mais caras.",
            })

    gatilhos.sort(key=lambda g: ORDEM_PRIORIDADE.get(g["tipo"], 9))
    for g in gatilhos:
        g["numeros_permitidos"] = numeros_de(g)
    return gatilhos
