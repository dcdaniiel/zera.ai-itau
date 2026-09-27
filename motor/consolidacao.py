"""Visão "hoje vs nova opção" para o fluxo guiado do app (telas 1, 4, 5, 6, 7 e 8 do design).

Tudo determinístico: situação atual (quanto sai por mês, saldo devedor, juros que correm, sem prazo),
resumo de um cenário como nova opção, desconto de débito automático e termos da contratação (CET, 1º vencimento).

Comparação honesta (quadro de produto, item 10 — "transparência sobre custo total"):
  - "Hoje" não tem um "total a pagar": rotativo/cheque não têm prazo; o que existe é o saldo devedor e os juros
    que correm por mês. Para comparar custo total no MESMO prazo, projetamos o que custaria quitar as dívidas
    nas condições de hoje em N meses (Price com a taxa atual de cada dívida) — `projecoes[N]`.
  - "Nova opção": saldo devedor integral + juros do acordo = custo total, com data para acabar.
"""

from __future__ import annotations

from datetime import date

from .modelos import PerfilFinanceiro, brl, r2
from .politicas import POLITICA_PADRAO
from .priorizacao import NOMES
from .simulacao import cet_anual, numeros_de, pmt, proximo_vencimento

ROTULO_UI = {
    "recomendado": {"titulo": "Mais equilíbrio", "descricao": "Equilibra o valor da parcela e o prazo."},
    "mais_folga": {"titulo": "Menor parcela", "descricao": "Mais espaço no seu orçamento."},
    "mais_rapido": {"titulo": "Terminar antes", "descricao": "Menor prazo para quitar."},
    "mais_barato": {"titulo": "Menor custo total", "descricao": "Paga menos juros no total."},
    "guardar_extra": {"titulo": "Guardar o dinheiro extra", "descricao": "Renegocia sem usar o dinheiro que entrou."},
}


def pagamento_mensal_hoje(divida) -> float:
    """Quanto a dívida consome por mês hoje: a parcela, se existe; senão os juros que correm (rotativo, cheque)."""
    return r2(divida.parcela_atual) if divida.parcela_atual and divida.parcela_atual > 0 else divida.custo_mensal


def projecao_mesmo_prazo(perfil: PerfilFinanceiro, prazo: int) -> dict:
    """Quanto custaria quitar TODAS as dívidas em `prazo` meses nas condições de hoje (taxa atual de cada uma)."""
    parcela = r2(sum(pmt(d.saldo, d.taxa_mensal, prazo) for d in perfil.dividas)) if prazo > 0 else 0.0
    total = r2(parcela * prazo)
    return {"prazo_meses": prazo, "parcela": parcela, "total": total, "juros": r2(total - perfil.total_dividas)}


def situacao_hoje(perfil: PerfilFinanceiro, politica: dict | None = None) -> dict:
    """Situação atual sem projeções mágicas: quanto sai por mês, saldo devedor, juros que correm, prazo (se existe)."""
    pol = politica or POLITICA_PADRAO
    itens, total_mes, prazo, indefinido = [], 0.0, 0, False
    for d in perfil.dividas:
        mensal = pagamento_mensal_hoje(d)
        if d.rotativo:
            indefinido = True
            prazo_d = None
        else:
            prazo_d = d.parcelas_restantes
            prazo = max(prazo, prazo_d)
        itens.append({"divida_id": d.divida_id, "nome": NOMES.get(d.produto, d.produto), "instituicao": d.instituicao,
                      "produto": d.produto, "saldo": d.saldo, "pagamento_mensal": mensal, "juros_mes": d.custo_mensal,
                      "prazo_meses": prazo_d, "dias_atraso": d.dias_atraso, "taxa_mensal": d.taxa_mensal,
                      "taxa_mensal_pct": r2(d.taxa_mensal * 100), "rotativo": d.rotativo, "fonte": d.fonte,
                      "descricao": d.descricao})
        total_mes += mensal
    saldo = perfil.total_dividas
    juros_mes = perfil.custo_total_mensal
    taxa_max = max((d.taxa_mensal for d in perfil.dividas), default=0.0)
    taxa_media = r2(juros_mes / saldo) if saldo else 0.0
    resultado = {
        "pagamento_mensal": r2(total_mes), "qtd_pagamentos": len(itens),
        "prazo_meses": (None if indefinido else prazo), "prazo_indefinido": indefinido,
        "saldo_devedor": saldo, "total_dividas": saldo,
        "juros_mensais": juros_mes, "custo_mensal_juros": juros_mes,
        "taxa_maxima": taxa_max, "taxa_maxima_pct": r2(taxa_max * 100), "taxa_media": taxa_media, "taxa_media_pct": r2(taxa_media * 100),
        "amortiza_por_mes": r2(total_mes - juros_mes),     # do que sai hoje, quanto de fato abate o saldo
        "projecoes": {str(n): projecao_mesmo_prazo(perfil, n) for n in pol["prazos_oferecidos"]},
        "dividas": itens, "maior_atraso": perfil.maior_atraso,
        "explicacao": (f"Hoje saem {brl(total_mes)} por mês em {len(itens)} pagamentos; o saldo devedor é {brl(saldo)} "
                       f"e {brl(juros_mes)} por mês são só juros (até {taxa_max*100:.0f}% a.m.)"
                       + (", sem data para terminar." if indefinido else ".")),
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def resumo_cenario(cenario: dict, hoje_ref: dict, politica: dict | None = None) -> dict:
    """Um cenário como 'nova opção' comparada com hoje. Total = entrada + parcelas = saldo devedor + juros do acordo."""
    pol = politica or POLITICA_PADRAO
    parcela = cenario["comprometimento_mensal"]
    total = cenario["custo_total"]
    prazo = cenario["prazo_meses"]
    livre = r2(hoje_ref["pagamento_mensal"] - parcela)
    rot = next((r for r in cenario.get("rotulos", []) if r in ROTULO_UI), "recomendado")
    desconto_da = r2(cenario["parcela_acordo"] * pol["desconto_debito_automatico_pct"])
    proj = (hoje_ref.get("projecoes") or {}).get(str(prazo)) or projecao_por_prazo_vazia(prazo)
    resultado = {
        "id": cenario["id"], "rotulos": cenario.get("rotulos", []), "titulo": ROTULO_UI[rot]["titulo"],
        "descricao": ROTULO_UI[rot]["descricao"], "recomendada": "recomendado" in cenario.get("rotulos", []),
        "parcela_mensal": parcela, "parcela_acordo": cenario["parcela_acordo"], "prazo_meses": prazo,
        "total_a_pagar": total, "qtd_pagamentos": cenario.get("qtd_pagamentos", 1),
        "taxa_mensal": cenario["taxa_mensal"], "taxa_mensal_pct": r2(cenario["taxa_mensal"] * 100), "cet_anual_pct": cenario["cet_anual"],
        "entrada": cenario.get("entrada", 0.0), "usa_caixa": cenario.get("usa_caixa", 0.0),
        "quitacoes_valor": cenario.get("quitacoes_valor", 0.0), "abatimentos_valor": cenario.get("abatimentos_valor", 0.0),
        "total_parcelas": cenario.get("total_parcelas", 0.0),
        "saldo_original": cenario.get("saldo_original", hoje_ref.get("saldo_devedor", 0.0)),
        "saldo_consolidado": cenario.get("saldo_consolidado", 0.0), "saldo_mantido": cenario.get("saldo_mantido", 0.0),
        "juros_acordo": cenario.get("juros_acordo", 0.0), "ganho_banco": cenario.get("ganho_banco", 0.0),
        "recebido_banco": cenario.get("recebido_banco", total),
        "hoje_mesmo_prazo": proj,                                   # custo de quitar em N meses nas condições de hoje
        "economia_vs_hoje_mesmo_prazo": r2(proj["total"] - total) if proj["total"] else 0.0,
        "liberado_por_mes": livre, "reserva": cenario.get("reserva", 0.0),
        "paga_menos_por_mes": livre > 0,
        "paga_por_mais_tempo": bool(hoje_ref.get("prazo_indefinido")) or (hoje_ref.get("prazo_meses") or 0) < prazo,
        "resolve_negativacao": cenario.get("resolve_negativacao", False),
        "debito_automatico": {"desconto_mensal": desconto_da, "parcela_com_desconto": r2(parcela - desconto_da),
                              "total_com_desconto": r2(total - desconto_da * max(prazo, 1))},
        "acoes": cenario["acoes"],
        "hoje": {k: hoje_ref.get(k) for k in ("pagamento_mensal", "qtd_pagamentos", "prazo_meses", "prazo_indefinido",
                                              "saldo_devedor", "juros_mensais", "taxa_maxima_pct")},
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def projecao_por_prazo_vazia(prazo: int) -> dict:
    return {"prazo_meses": prazo, "parcela": 0.0, "total": 0.0, "juros": 0.0}


def termos(cenario: dict, perfil: PerfilFinanceiro, hoje: date, debito_automatico: bool, politica: dict | None = None) -> dict:
    """Termos da contratação: o que a cliente assina. Recalculados a cada exibição (spec §16)."""
    pol = politica or POLITICA_PADRAO
    parcela_acordo = cenario["parcela_acordo"]
    prazo = cenario["prazo_meses"]
    desconto = r2(parcela_acordo * pol["desconto_debito_automatico_pct"]) if (debito_automatico and prazo > 0) else 0.0
    parcela_final = r2(parcela_acordo - desconto)
    manter_mensal = cenario.get("juros_mantidos_mes", 0.0)
    total_parcelas = r2(parcela_final * prazo)
    entrada = r2(cenario.get("entrada", 0.0))
    total = r2(entrada + total_parcelas)
    venc = proximo_vencimento(hoje, perfil.dia_pagamento_preferido or pol["dia_vencimento_padrao"])
    ultimo = _somar_meses(venc, max(prazo - 1, 0))
    incluidas = []
    for a in cenario["acoes"]:
        d = next((x for x in perfil.dividas if x.divida_id == a["divida_id"]), None)
        if d is None:
            continue
        incluidas.append({"divida_id": d.divida_id, "nome": NOMES.get(d.produto, d.produto), "instituicao": d.instituicao,
                          "saldo": d.saldo, "taxa_hoje_pct": r2(d.taxa_mensal * 100), "acao": a["acao"],
                          "parcela": a.get("parcela", 0.0), "prazo": a.get("prazo", 0), "usa_caixa": a.get("usa_caixa", 0.0),
                          "entrada": a.get("entrada", 0.0), "saldo_base": a.get("saldo_base", 0.0), "fonte": d.fonte,
                          "descricao": a.get("descricao", "")})
    i = cenario["taxa_mensal"]
    resultado = {
        "cenario_id": cenario["id"], "parcela_mensal": r2(parcela_final + manter_mensal), "parcela_acordo": parcela_final,
        "compromissos_mantidos_mes": manter_mensal,
        "desconto_debito_automatico": desconto, "prazo_meses": prazo, "total_a_pagar": total,
        "entrada": entrada, "quitacoes_valor": cenario.get("quitacoes_valor", 0.0), "abatimentos_valor": cenario.get("abatimentos_valor", 0.0),
        "total_parcelas": total_parcelas, "saldo_original": cenario.get("saldo_original", 0.0),
        "saldo_consolidado": cenario.get("saldo_consolidado", 0.0),
        "juros_acordo": r2(total_parcelas - cenario.get("saldo_consolidado", 0.0)) if prazo > 0 else 0.0,
        "taxa_mensal_pct": r2(i * 100), "cet_mensal_pct": r2(i * 100), "cet_anual_pct": r2(cet_anual(i) * 100),
        "primeiro_vencimento": venc.isoformat(), "ultimo_vencimento": ultimo.isoformat(),
        "debito_automatico": debito_automatico, "dividas_incluidas": incluidas,
        "quitacoes": [x for x in incluidas if x["acao"] == "quitar"],
        "renegociacoes": [x for x in incluidas if x["acao"].startswith("renegociar")],
        "mantidas": [x for x in incluidas if x["acao"] == "manter"],
        "aviso": "Esta contratação só será concluída com a sua confirmação.",
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def _somar_meses(d: date, n: int) -> date:
    ano, mes = d.year, d.month + n
    ano += (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    from .simulacao import _ultimo_dia
    return date(ano, mes, min(d.day, _ultimo_dia(ano, mes)))
