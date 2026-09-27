"""Montagem de cenários de renegociação — princípio "ambos ganham".

Pergunta que responde: "a cliente entrou no rotativo (ou entrou dinheiro extra): qual dívida quitar/abater,
o que renegociar e em quantas vezes (12x…48x), para a parcela caber no mês dela — sem o banco abrir mão do
saldo devedor?"

Como funciona (tudo determinístico, sem LLM):
    1. Dinheiro extra (13º, FGTS, restituição, renda extra) menos uma reserva mínima vira ENTRADA:
       quita por completo as dívidas mais caras que couberem e abate o que sobrar da mais cara restante.
    2. As dívidas do Itaú que sobram são REUNIDAS em um único acordo: saldo devedor integral (sem desconto no
       principal) à taxa de renegociação, em N meses. Dívidas de outras instituições só podem ser quitadas com
       a entrada; senão são mantidas como estão (a parcela delas continua saindo do bolso).
    3. Um cenário por prazo elegível. Viável = parcela + compromissos mantidos ≤ parcela máxima e no máximo
       `respiros` meses do histórico em que não caberia.
    4. Rótulos: recomendado = menor prazo que cabe com conforto (renda irregular → 70% da parcela máxima);
       mais_barato/mais_rapido = menor prazo viável (menos juros); mais_folga = maior prazo viável (menor parcela).

Ganho do banco = juros do acordo (recebe o saldo integral + juros, em vez de uma dívida em atraso a caminho
da provisão). Ganho da cliente = parcela menor, taxa menor, data para acabar, nome limpo.
"""

from __future__ import annotations

from statistics import mean, pstdev

from .modelos import Capacidade, Divida, PerfilFinanceiro, brl, r2
from .politicas import POLITICA_PADRAO, instituicao_renegociavel
from .priorizacao import NOMES
from .simulacao import cet_anual, numeros_de, pmt, pv


# ---------- perfil de risco ----------

def coeficiente_variacao_renda(perfil: PerfilFinanceiro) -> float:
    m = mean(perfil.renda_mensal) if perfil.renda_mensal else 0.0
    return r2(pstdev(perfil.renda_mensal) / m) if m else 0.0


def parcela_conforto(perfil: PerfilFinanceiro, capacidade: Capacidade, politica: dict) -> tuple[float, str]:
    cv = coeficiente_variacao_renda(perfil)
    if cv >= politica["cv_renda_irregular"]:
        return r2(politica["fator_conforto_renda_irregular"] * capacidade.parcela_maxima), "renda_irregular"
    return capacidade.parcela_maxima, "renda_estavel"


# ---------- entrada (dinheiro extra) ----------

def alocar_entrada(dividas: list[Divida], caixa: float, politica: dict) -> tuple[dict[str, float], float]:
    """Aplica o dinheiro extra nas dívidas mais caras: quitação integral das que couberem (da mais cara para
    a mais barata) e abatimento parcial na mais cara renegociável que sobrar. Devolve ({divida_id: valor}, sobra)."""
    entradas = {d.divida_id: 0.0 for d in dividas}
    restante = r2(max(0.0, caixa))
    por_taxa = sorted(dividas, key=lambda d: (d.taxa_mensal, d.saldo), reverse=True)
    for d in por_taxa:                                   # 1) quitações integrais
        if d.saldo > 0 and restante >= d.saldo - 1e-9:
            entradas[d.divida_id] = r2(d.saldo)
            restante = r2(restante - d.saldo)
    for d in por_taxa:                                   # 2) abatimento parcial (só em dívida que entra no acordo)
        if restante <= 0.005:
            break
        if entradas[d.divida_id] >= d.saldo - 1e-9 or not instituicao_renegociavel(d.instituicao, politica):
            continue
        v = r2(min(restante, d.saldo - entradas[d.divida_id]))
        entradas[d.divida_id] = r2(entradas[d.divida_id] + v)
        restante = r2(restante - v)
    return entradas, restante


# ---------- cenários ----------

def _meses_que_nao_cabem(perfil: PerfilFinanceiro, capacidade: Capacidade, parcela: float) -> list[str]:
    return [m for m, s in zip(perfil.meses, perfil.sobra_mensal) if (s - capacidade.colchao) < parcela]


def _pagamento_hoje(d: Divida) -> float:
    return r2(d.parcela_atual) if d.parcela_atual and d.parcela_atual > 0 else d.custo_mensal


def _montar_cenario(perfil: PerfilFinanceiro, capacidade: Capacidade, pol: dict, entradas: dict[str, float],
                    reserva: float, prazo: int, alvo: float) -> dict:
    i = pol["taxa_mensal_renegociacao"]
    acoes, quitadas, consolidadas, mantidas = [], [], [], []
    for d in perfil.dividas:
        nome = NOMES.get(d.produto, d.produto)
        entrada = entradas.get(d.divida_id, 0.0)
        base = {"divida_id": d.divida_id, "nome": nome, "instituicao": d.instituicao, "saldo": d.saldo,
                "taxa_hoje": d.taxa_mensal, "dias_atraso": d.dias_atraso, "entrada": entrada}
        if entrada >= d.saldo - 1e-9 and d.saldo > 0:
            quitadas.append(d)
            acoes.append({**base, "acao": "quitar", "usa_caixa": r2(d.saldo), "saldo_base": 0.0, "parcela": 0.0, "prazo": 0,
                          "resolve_atraso": True, "descricao": f"quitar {nome} ({brl(d.saldo)}) com o dinheiro extra"})
        elif instituicao_renegociavel(d.instituicao, pol):
            saldo_base = r2(d.saldo - entrada)
            parcela = r2(pmt(saldo_base, i, prazo)) if prazo > 0 else 0.0
            consolidadas.append(d)
            acoes.append({**base, "acao": f"renegociar_{prazo}x", "usa_caixa": entrada, "saldo_base": saldo_base,
                          "parcela": parcela, "prazo": prazo, "taxa_mensal": i, "resolve_atraso": True,
                          "descricao": (f"abater {brl(entrada)} e renegociar o restante de {nome} ({brl(saldo_base)}) em {prazo}x de {brl(parcela)}"
                                        if entrada > 0 else f"renegociar {nome} ({brl(saldo_base)}) em {prazo}x de {brl(parcela)}")})
        else:
            mensal = _pagamento_hoje(d)
            mantidas.append(d)
            acoes.append({**base, "acao": "manter", "usa_caixa": 0.0, "saldo_base": 0.0, "parcela": mensal, "prazo": 0,
                          "resolve_atraso": False,
                          "descricao": f"manter {nome} ({d.instituicao}) como está — {brl(mensal)}/mês continuam saindo"})

    saldo_consolidado = r2(sum(a["saldo_base"] for a in acoes if a["acao"].startswith("renegociar")))
    parcela_acordo = r2(sum(a["parcela"] for a in acoes if a["acao"].startswith("renegociar")))
    manter_mensal = r2(sum(a["parcela"] for a in acoes if a["acao"] == "manter"))
    comprometimento = r2(parcela_acordo + manter_mensal)
    total_parcelas = r2(parcela_acordo * prazo)
    juros_acordo = r2(total_parcelas - saldo_consolidado) if saldo_consolidado > 0 else 0.0
    quitacoes_valor = r2(sum(a["usa_caixa"] for a in acoes if a["acao"] == "quitar"))
    abatimentos_valor = r2(sum(a["entrada"] for a in acoes if a["acao"].startswith("renegociar")))
    entrada_total = r2(quitacoes_valor + abatimentos_valor)
    saldo_original = r2(sum(d.saldo for d in quitadas + consolidadas))
    custo_total = r2(entrada_total + total_parcelas)            # = saldo_original + juros_acordo
    ruins = _meses_que_nao_cabem(perfil, capacidade, comprometimento)
    cabe = comprometimento <= capacidade.parcela_maxima + 1e-9
    nao_resolvidas = [NOMES.get(d.produto, d.produto) for d in mantidas if d.dias_atraso >= pol["dias_atraso_consequencia"]]
    prazo_efetivo = prazo if saldo_consolidado > 0 else 0
    return {
        "acoes": acoes,
        "prazo_meses": prazo_efetivo,
        "taxa_mensal": i, "cet_anual": r2(cet_anual(i) * 100),
        "parcela_acordo": parcela_acordo,                 # a parcela do novo acordo (um pagamento)
        "parcela_mensal": comprometimento,                # o que sai do bolso por mês (acordo + dívidas mantidas)
        "comprometimento_mensal": comprometimento,
        "juros_mantidos_mes": manter_mensal,
        "qtd_pagamentos": (1 if saldo_consolidado > 0 else 0) + len(mantidas),
        "entrada": entrada_total, "usa_caixa": entrada_total,
        "quitacoes_valor": quitacoes_valor, "abatimentos_valor": abatimentos_valor,
        "reserva": reserva,
        "saldo_original": saldo_original,                 # saldo devedor das dívidas que entram (integral, sem desconto)
        "saldo_consolidado": saldo_consolidado,           # o que vira o novo acordo (após a entrada)
        "saldo_mantido": r2(sum(d.saldo for d in mantidas)),
        "total_parcelas": total_parcelas,
        "juros_acordo": juros_acordo,                     # ganho do banco ao longo do acordo
        "custo_total": custo_total,                       # entrada + parcelas = saldo original + juros
        "ganho_banco": juros_acordo,
        "recebido_banco": custo_total,
        "resolve_negativacao": not nao_resolvidas,
        "dividas_nao_resolvidas": nao_resolvidas,
        "meses_em_que_nao_cabe": ruins,
        "respiros": capacidade.respiros_ano,
        "cabe": cabe,
        "viavel": cabe and len(ruins) <= capacidade.respiros_ano,
        "dentro_do_conforto": comprometimento <= alvo + 1e-9,
        "rotulos": [],
    }


def _rotular(viaveis: list[dict], prefixo: str = "C") -> list[dict]:
    por_prazo = sorted(viaveis, key=lambda c: c["prazo_meses"])
    confortaveis = [c for c in por_prazo if c["dentro_do_conforto"]]
    recomendado = confortaveis[0] if confortaveis else por_prazo[0]
    mais_barato, mais_folga = por_prazo[0], por_prazo[-1]
    for rotulo, c in (("recomendado", recomendado), ("mais_barato", mais_barato), ("mais_rapido", mais_barato), ("mais_folga", mais_folga)):
        if rotulo not in c["rotulos"]:
            c["rotulos"].append(rotulo)
    for k, c in enumerate(por_prazo, start=1):
        c["id"] = f"{prefixo}{k}"
        c["resumo"] = " + ".join(a["descricao"] for a in c["acoes"])
    # recomendado primeiro, depois do menor para o maior prazo
    return sorted(por_prazo, key=lambda c: (0 if "recomendado" in c["rotulos"] else 1, c["prazo_meses"]))


def montar_cenarios(perfil: PerfilFinanceiro, capacidade: Capacidade, valor_extra: float = 0.0,
                    politica: dict | None = None) -> dict:
    pol = politica or POLITICA_PADRAO
    dividas = perfil.dividas
    if not dividas:
        return {"cenarios": [], "recomendado": None, "motivo": "sem dívidas", "nenhum_cenario_cabe": True, "numeros_permitidos": []}

    valor_extra = r2(max(0.0, valor_extra))
    reserva_minima = r2(capacidade.colchao if (not perfil.tem_reserva and valor_extra > 0) else 0.0)
    caixa = r2(max(0.0, valor_extra - reserva_minima)) if pol["usar_entrada"] else 0.0
    alvo, perfil_risco = parcela_conforto(perfil, capacidade, pol)
    entradas, sobra_caixa = alocar_entrada(dividas, caixa, pol)
    reserva = r2(reserva_minima + sobra_caixa)

    cenarios = [_montar_cenario(perfil, capacidade, pol, entradas, reserva, n, alvo) for n in pol["prazos_oferecidos"]]
    if all(c["saldo_consolidado"] <= 0.5 for c in cenarios):      # a entrada quitou tudo: um único cenário sem parcela
        cenarios = cenarios[:1]
    viaveis = [c for c in cenarios if c["viavel"]]
    if valor_extra > 0 and caixa > 0:
        # alternativa "guardar o dinheiro extra": só renegociação, o extra fica com a cliente (entrada atípica ≠ renda livre)
        sem_entrada = {d.divida_id: 0.0 for d in dividas}
        guardar = [_montar_cenario(perfil, capacidade, pol, sem_entrada, r2(valor_extra), n, alvo) for n in pol["prazos_oferecidos"]]
        guardar_viaveis = [c for c in guardar if c["viavel"]]
        if guardar_viaveis:
            melhor = sorted(guardar_viaveis, key=lambda c: (not c["dentro_do_conforto"], c["prazo_meses"]))[0]
            melhor["rotulos"].append("guardar_extra")
            viaveis.append(melhor)

    base = {
        "valor_extra": valor_extra, "reserva_minima": reserva_minima, "caixa_disponivel": caixa,
        "saldo_total": perfil.total_dividas, "custo_mensal_hoje": perfil.custo_total_mensal,
        "parcela_maxima": capacidade.parcela_maxima, "parcela_conforto": alvo, "perfil_risco": perfil_risco,
        "coeficiente_variacao_renda": coeficiente_variacao_renda(perfil),
        "prazos_oferecidos": pol["prazos_oferecidos"], "taxa_mensal_renegociacao": pol["taxa_mensal_renegociacao"],
        "entradas": entradas,
    }

    if not viaveis:
        i = pol["taxa_mensal_renegociacao"]
        maior = max(cenarios, key=lambda c: c["prazo_meses"])
        manter_mensal = maior["juros_mantidos_mes"]
        # parcela que caberia de fato: limitada pela parcela máxima E pelos meses fracos além dos respiros
        sobras_liquidas = sorted(s - capacidade.colchao for s in perfil.sobra_mensal)
        limite_meses = sobras_liquidas[min(capacidade.respiros_ano, len(sobras_liquidas) - 1)] if sobras_liquidas else capacidade.parcela_maxima
        disponivel = r2(min(capacidade.parcela_maxima, limite_meses) - manter_mensal)
        entrada_necessaria = r2(max(0.0, maior["saldo_consolidado"] - pv(disponivel, i, pol["prazo_max"]))) if disponivel > 0 else None
        falta_por_mes = r2(maior["comprometimento_mensal"] - min(capacidade.parcela_maxima, limite_meses))
        diagnostico = {
            "parcela_minima_possivel": maior["comprometimento_mensal"], "prazo_da_parcela_minima": maior["prazo_meses"],
            "parcela_maxima": capacidade.parcela_maxima, "parcela_disponivel": disponivel, "falta_por_mes": falta_por_mes,
            "compromissos_mantidos_mes": manter_mensal,
            "entrada_necessaria": entrada_necessaria,            # dinheiro extra que faria caber em 48x
            "reducao_gastos_necessaria": r2(falta_por_mes / pol["fator_seguranca"]),   # quanto a sobra mensal precisaria subir
            "meses_em_que_nao_cabe": maior["meses_em_que_nao_cabe"], "respiros": capacidade.respiros_ano,
        }
        motivo = (f"Nem em {maior['prazo_meses']}x a parcela ({brl(maior['comprometimento_mensal'])}) fica dentro da parcela máxima "
                  f"({brl(capacidade.parcela_maxima)}). " +
                  (f"Faltam {brl(falta_por_mes)} por mês. " if falta_por_mes > 0 else
                   f"A parcela cabe, mas não caberia em {len(maior['meses_em_que_nao_cabe'])} dos últimos 12 meses (mais que os {capacidade.respiros_ano} respiros). "))
        resultado = {**base, "cenarios": [], "recomendado": None, "nenhum_cenario_cabe": True, "motivo": motivo, "diagnostico": diagnostico}
        resultado["numeros_permitidos"] = numeros_de(resultado)
        return resultado

    rotulados = _rotular(viaveis)
    rec = rotulados[0]
    explicacao = (
        (f"Com {brl(valor_extra)} de dinheiro extra (guardando {brl(reserva)} de reserva), o melhor uso é: {rec['resumo']}. "
         if valor_extra > 0 else f"Sem dinheiro extra agora, o caminho é: {rec['resumo']}. ")
        + f"Fica {brl(rec['comprometimento_mensal'])} por mês, dentro da parcela de conforto de {brl(alvo)} "
        f"({'renda irregular' if perfil_risco == 'renda_irregular' else 'renda estável'}); "
        f"{'todas as dívidas em atraso saem do atraso' if rec['resolve_negativacao'] else 'ainda sobra dívida em atraso: ' + ', '.join(rec['dividas_nao_resolvidas'])}. "
        f"O banco recebe o saldo integral de {brl(rec['saldo_original'])} mais {brl(rec['juros_acordo'])} de juros ao longo de "
        f"{rec['prazo_meses']} meses (taxa de {pol['taxa_mensal_renegociacao']*100:.1f}% a.m.) — ninguém abre mão do principal."
    )
    resultado = {**base, "cenarios": rotulados, "recomendado": rec["id"], "nenhum_cenario_cabe": False,
                 "total_combinacoes_avaliadas": len(cenarios), "explicacao": explicacao}
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


# compatibilidade: a API antiga do agente chamava opcoes_da_divida
def opcoes_da_divida(divida: Divida, politica: dict | None = None) -> list[dict]:
    pol = politica or POLITICA_PADRAO
    i = pol["taxa_mensal_renegociacao"]
    nome = NOMES.get(divida.produto, divida.produto)
    return [{"acao": f"renegociar_{n}x", "divida_id": divida.divida_id, "nome": nome, "saldo_base": divida.saldo,
             "parcela": r2(pmt(divida.saldo, i, n)), "prazo": n, "taxa_mensal": i} for n in pol["prazos_oferecidos"]]
