"""Alocação de dinheiro extra e montagem de cenários por dívida.

Pergunta que responde: "entrou dinheiro (FGTS, 13º, restituição, renda extra) — qual dívida quitar,
qual renegociar (em 12x, 18x, 24x, 36x) e qual manter, para sair da negativação dentro da realidade
financeira da pessoa?"

Para cada dívida as ações possíveis são:
    quitar           — à vista com desconto da faixa de atraso, usando o dinheiro extra
    renegociar_N     — parcelar em N meses (menu de prazos da política) com desconto "parcelado"
    manter           — só para dívida em dia; custo = juros por 12 meses (nunca resolve negativação)

Enumeramos todas as combinações (poucas dívidas → poucas centenas), filtramos as viáveis
(caixa, parcela ≤ máxima, meses fracos ≤ respiros) e ranqueamos por: resolve a negativação >
custo total > parcela mensal. O recomendado respeita ainda a "parcela de conforto" do perfil
(renda irregular → 70% da parcela máxima).
"""

from __future__ import annotations

from itertools import product
from statistics import mean, pstdev

from .modelos import Capacidade, PerfilFinanceiro, r2
from .politicas import POLITICA_PADRAO
from .priorizacao import NOMES
from .simulacao import cet_anual, faixa_desconto, numeros_de, pmt


# ---------- perfil de risco ----------

def coeficiente_variacao_renda(perfil: PerfilFinanceiro) -> float:
    m = mean(perfil.renda_mensal)
    return r2(pstdev(perfil.renda_mensal) / m) if m else 0.0


def parcela_conforto(perfil: PerfilFinanceiro, capacidade: Capacidade, politica: dict) -> tuple[float, str]:
    cv = coeficiente_variacao_renda(perfil)
    if cv >= politica["cv_renda_irregular"]:
        return r2(politica["fator_conforto_renda_irregular"] * capacidade.parcela_maxima), "renda_irregular"
    return capacidade.parcela_maxima, "renda_estavel"


# ---------- opções por dívida ----------

def opcoes_da_divida(divida, politica: dict) -> list[dict]:
    faixa = faixa_desconto(divida.dias_atraso, politica)
    i = politica["taxa_mensal_renegociacao"]
    em_atraso = divida.dias_atraso >= politica["dias_atraso_consequencia"]
    nome = NOMES.get(divida.produto, divida.produto)
    opcoes = []
    avista = r2(divida.saldo * (1 - faixa["avista"]))
    opcoes.append({
        "acao": "quitar", "divida_id": divida.divida_id, "nome": nome, "usa_caixa": avista,
        "desconto_pct": faixa["avista"], "desconto_valor": r2(divida.saldo - avista),
        "parcela": 0.0, "prazo": 0, "custo_total": avista, "resolve_atraso": True,
        "descricao": f"quitar {nome} à vista por {avista:.2f} ({int(faixa['avista']*100)}% de desconto)",
    })
    base = r2(divida.saldo * (1 - faixa["parcelado"]))
    for n in politica["prazos_oferecidos"]:
        p = r2(pmt(base, i, n))
        opcoes.append({
            "acao": f"renegociar_{n}x", "divida_id": divida.divida_id, "nome": nome, "usa_caixa": 0.0,
            "desconto_pct": faixa["parcelado"], "desconto_valor": r2(divida.saldo - base),
            "parcela": p, "prazo": n, "custo_total": r2(p * n), "resolve_atraso": True,
            "taxa_mensal": i, "cet_anual": r2(cet_anual(i) * 100), "saldo_base": base,
            "descricao": f"renegociar {nome} em {n}x de {p:.2f}",
        })
    if not em_atraso:
        custo_manter = r2(divida.saldo * divida.taxa_mensal * politica["horizonte_manter_meses"])
        opcoes.append({
            "acao": "manter", "divida_id": divida.divida_id, "nome": nome, "usa_caixa": 0.0,
            "desconto_pct": 0.0, "desconto_valor": 0.0, "parcela": divida.custo_mensal, "prazo": 0,
            "custo_total": r2(divida.saldo + custo_manter), "resolve_atraso": False,
            "descricao": f"manter {nome} como está (custa {divida.custo_mensal:.2f}/mês só de juros)",
        })
    return opcoes


# ---------- cenários ----------

def _meses_que_nao_cabem(perfil: PerfilFinanceiro, capacidade: Capacidade, parcela: float) -> list[str]:
    return [m for m, s in zip(perfil.meses, perfil.sobra_mensal) if (s - capacidade.colchao) < parcela]


def montar_cenarios(perfil: PerfilFinanceiro, capacidade: Capacidade, valor_extra: float = 0.0,
                    politica: dict | None = None) -> dict:
    pol = politica or POLITICA_PADRAO
    dividas = perfil.dividas
    if not dividas:
        return {"cenarios": [], "recomendado": None, "motivo": "sem dívidas", "numeros_permitidos": []}

    reserva_minima = r2(capacidade.colchao if (not perfil.tem_reserva and valor_extra > 0) else 0.0)
    caixa = r2(max(0.0, valor_extra - reserva_minima))
    alvo, perfil_risco = parcela_conforto(perfil, capacidade, pol)
    opcoes = [opcoes_da_divida(d, pol) for d in dividas]
    em_atraso = {d.divida_id for d in dividas if d.dias_atraso >= pol["dias_atraso_consequencia"]}

    cenarios = []
    for combo in product(*opcoes):
        usa_caixa = r2(sum(o["usa_caixa"] for o in combo))
        if usa_caixa > caixa + 1e-9:
            continue
        parcelas = r2(sum(o["parcela"] for o in combo if o["acao"] != "manter"))
        juros_mantidos = r2(sum(o["parcela"] for o in combo if o["acao"] == "manter"))
        comprometimento = r2(parcelas + juros_mantidos)
        if comprometimento > capacidade.parcela_maxima + 1e-9:
            continue
        ruins = _meses_que_nao_cabem(perfil, capacidade, comprometimento)
        if len(ruins) > capacidade.respiros_ano:
            continue
        nao_resolvidas = [o["nome"] for o in combo if o["divida_id"] in em_atraso and not o["resolve_atraso"]]
        sobra_caixa = r2(caixa - usa_caixa)
        cenarios.append({
            "acoes": list(combo),
            "usa_caixa": usa_caixa,
            "reserva": r2(reserva_minima + sobra_caixa),
            "parcela_mensal": parcelas,
            "juros_mantidos_mes": juros_mantidos,
            "comprometimento_mensal": comprometimento,
            "prazo_meses": max((o["prazo"] for o in combo), default=0),
            "custo_total": r2(sum(o["custo_total"] for o in combo)),
            "resolve_negativacao": not nao_resolvidas,
            "dividas_nao_resolvidas": nao_resolvidas,
            "meses_em_que_nao_cabe": ruins,
            "respiros": capacidade.respiros_ano,
            "dentro_do_conforto": comprometimento <= alvo + 1e-9,
        })

    if not cenarios:
        return {
            "valor_extra": r2(valor_extra), "reserva_minima": reserva_minima, "caixa_disponivel": caixa,
            "parcela_maxima": capacidade.parcela_maxima, "parcela_conforto": alvo, "perfil_risco": perfil_risco,
            "cenarios": [], "recomendado": None, "nenhum_cenario_cabe": True,
            "motivo": f"Nem em {max(pol['prazos_oferecidos'])}x o total das parcelas fica dentro da parcela máxima; priorizar a dívida mais cara e escalar para humano.",
            "numeros_permitidos": numeros_de({"a": [valor_extra, reserva_minima, caixa, capacidade.parcela_maxima, alvo]}),
        }

    # ranking: resolve negativação > custo total > parcela mensal
    cenarios.sort(key=lambda c: (not c["resolve_negativacao"], c["custo_total"], c["comprometimento_mensal"]))
    resolvem = [c for c in cenarios if c["resolve_negativacao"]] or cenarios
    confortaveis = [c for c in resolvem if c["dentro_do_conforto"]]
    recomendado = confortaveis[0] if confortaveis else resolvem[0]
    mais_barato = resolvem[0]
    mais_folga = min(resolvem, key=lambda c: (c["comprometimento_mensal"], c["custo_total"]))
    mais_rapido = min(resolvem, key=lambda c: (c["prazo_meses"], c["custo_total"]))

    rotulados, vistos = [], set()
    for rotulo, c in (("recomendado", recomendado), ("mais_barato", mais_barato), ("mais_folga", mais_folga), ("mais_rapido", mais_rapido)):
        chave = tuple(o["acao"] for o in c["acoes"])
        if chave in vistos:
            for r in rotulados:
                if tuple(o["acao"] for o in r["acoes"]) == chave:
                    r["rotulos"].append(rotulo)
            continue
        vistos.add(chave)
        rotulados.append({**c, "id": f"C{len(rotulados)+1}", "rotulos": [rotulo],
                          "resumo": " + ".join(o["descricao"] for o in c["acoes"])})

    rec = rotulados[0]
    explicacao = (
        f"Com {valor_extra:.2f} de dinheiro extra (guardando {reserva_minima:.2f} de reserva), o melhor uso é: {rec['resumo']}. "
        f"Fica {rec['comprometimento_mensal']:.2f} por mês, dentro da parcela de conforto de {alvo:.2f} "
        f"({'renda irregular' if perfil_risco == 'renda_irregular' else 'renda estável'}), e "
        f"{'todas as dívidas em atraso saem da negativação' if rec['resolve_negativacao'] else 'ainda sobra dívida em atraso: ' + ', '.join(rec['dividas_nao_resolvidas'])}."
    )
    resultado = {
        "valor_extra": r2(valor_extra), "reserva_minima": reserva_minima, "caixa_disponivel": caixa,
        "parcela_maxima": capacidade.parcela_maxima, "parcela_conforto": alvo, "perfil_risco": perfil_risco,
        "coeficiente_variacao_renda": coeficiente_variacao_renda(perfil),
        "prazos_oferecidos": pol["prazos_oferecidos"],
        "cenarios": rotulados, "recomendado": rec["id"], "nenhum_cenario_cabe": False,
        "total_combinacoes_avaliadas": len(cenarios),
        "explicacao": explicacao,
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado
