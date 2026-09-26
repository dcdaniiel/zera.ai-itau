"""Simulação de planos de renegociação, acordo, respiro e amortização.

Toda conta de dinheiro do Zera nasce aqui (Price + política parametrizada).
O LLM nunca calcula: ele só cita o que estas funções devolvem.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from uuid import uuid4

from .modelos import Acordo, Capacidade, PerfilFinanceiro, Plano, r2
from .politicas import POLITICA_PADRAO


# ---------- matemática financeira ----------

def pmt(pv: float, i: float, n: int) -> float:
    if n <= 0:
        raise ValueError("prazo deve ser >= 1")
    if i <= 0:
        return pv / n
    return pv * i / (1 - (1 + i) ** (-n))


def cet_anual(i: float) -> float:
    return (1 + i) ** 12 - 1


def prazo_para_parcela(pv: float, i: float, parcela_max: float, prazo_max: int) -> int | None:
    """Menor prazo (1..prazo_max) cuja parcela Price fica <= parcela_max. None se não cabe."""
    if parcela_max <= 0:
        return None
    for n in range(1, prazo_max + 1):
        if pmt(pv, i, n) <= parcela_max + 1e-9:
            return n
    return None


def faixa_desconto(dias_atraso: int, politica: dict) -> dict:
    for faixa in politica["faixas_desconto"]:
        if faixa["de"] <= dias_atraso <= faixa["ate"]:
            return faixa
    return politica["faixas_desconto"][-1]


def meses_em_que_nao_cabe(perfil: PerfilFinanceiro, capacidade: Capacidade, parcela: float) -> list[str]:
    """Meses do histórico em que (sobra − colchão) < parcela — o mês precisaria de respiro."""
    return [m for m, s in zip(perfil.meses, perfil.sobra_mensal) if (s - capacidade.colchao) < parcela]


# ---------- planos ----------

def _plano_parcelado(perfil, capacidade, pol, saldo_base, desconto_pct, desconto_valor, com_respiro: bool) -> Plano:
    i = pol["taxa_mensal_renegociacao"]
    respiros = capacidade.respiros_ano if com_respiro else 0
    n_escolhido, parcela_escolhida, meses_ruins = None, None, []
    for n in range(1, pol["prazo_max"] + 1):
        p = pmt(saldo_base, i, n)
        if p > capacidade.parcela_maxima + 1e-9:
            continue
        ruins = meses_em_que_nao_cabe(perfil, capacidade, p)
        if com_respiro and len(ruins) > respiros:
            continue
        n_escolhido, parcela_escolhida, meses_ruins = n, r2(p), ruins
        break
    if n_escolhido is None:
        return Plano(
            id="C" if com_respiro else "B",
            tipo="parcela_com_respiro" if com_respiro else "parcela_que_cabe",
            nome="Parcela que cabe + respiro" if com_respiro else "Parcela que cabe",
            saldo_base=saldo_base, desconto_pct=desconto_pct, desconto_valor=desconto_valor,
            parcela=0.0, prazo=0, prazo_nominal=0, taxa_mensal=i, cet_anual=r2(cet_anual(i) * 100),
            total_pago=0.0, respiros=respiros, cabe=False,
            motivo=f"Nem em {pol['prazo_max']} parcelas a parcela fica dentro da sua sobra segura.",
        )
    total = r2(parcela_escolhida * n_escolhido)
    return Plano(
        id="C" if com_respiro else "B",
        tipo="parcela_com_respiro" if com_respiro else "parcela_que_cabe",
        nome="Parcela que cabe + respiro" if com_respiro else "Parcela que cabe",
        saldo_base=saldo_base, desconto_pct=desconto_pct, desconto_valor=desconto_valor,
        parcela=parcela_escolhida, prazo=n_escolhido, prazo_nominal=n_escolhido + respiros,
        taxa_mensal=i, cet_anual=r2(cet_anual(i) * 100), total_pago=total, respiros=respiros,
        cabe=True,
        motivo=(
            f"Parcela de {parcela_escolhida:.2f} fica dentro da sua parcela máxima de {capacidade.parcela_maxima:.2f}"
            + (f"; {respiros} respiro(s) por ano cobrem os meses mais apertados." if com_respiro else ".")
        ),
        meses_em_que_nao_cabe=meses_ruins,
    )


def simular_planos(perfil: PerfilFinanceiro, capacidade: Capacidade, politica: dict | None = None,
                   dinheiro_extra: float = 0.0) -> dict:
    pol = politica or POLITICA_PADRAO
    i = pol["taxa_mensal_renegociacao"]
    saldo_total = perfil.total_dividas
    faixa = faixa_desconto(perfil.maior_atraso, pol)

    # Plano A — à vista
    desc_a = faixa["avista"]
    valor_avista = r2(saldo_total * (1 - desc_a))
    plano_a = Plano(
        id="A", tipo="avista", nome="Quitação à vista com desconto",
        saldo_base=valor_avista, desconto_pct=desc_a, desconto_valor=r2(saldo_total - valor_avista),
        parcela=valor_avista, prazo=1, prazo_nominal=1, taxa_mensal=0.0, cet_anual=0.0,
        total_pago=valor_avista, respiros=0, cabe=dinheiro_extra >= valor_avista,
        motivo=("Cabe: o dinheiro extra cobre o valor à vista." if dinheiro_extra >= valor_avista
                else "Só faz sentido quando entrar dinheiro extra (13º, restituição, FGTS) — avisamos na hora."),
        valor_avista=valor_avista,
    )

    # Planos B e C — parcelados
    desc_p = faixa["parcelado"]
    saldo_base = r2(saldo_total * (1 - desc_p))
    desconto_valor = r2(saldo_total - saldo_base)
    plano_b = _plano_parcelado(perfil, capacidade, pol, saldo_base, desc_p, desconto_valor, com_respiro=False)
    plano_c = _plano_parcelado(perfil, capacidade, pol, saldo_base, desc_p, desconto_valor, com_respiro=True)

    # Plano padrão (contraste): prazo fixo, sem olhar a sobra
    n_pad = pol["prazo_padrao"]
    parcela_pad = r2(pmt(saldo_base, i, n_pad))
    ruins_pad = meses_em_que_nao_cabe(perfil, capacidade, parcela_pad)
    plano_padrao = Plano(
        id="PADRAO", tipo="padrao", nome=f"Renegociação padrão ({n_pad}x)",
        saldo_base=saldo_base, desconto_pct=desc_p, desconto_valor=desconto_valor,
        parcela=parcela_pad, prazo=n_pad, prazo_nominal=n_pad, taxa_mensal=i,
        cet_anual=r2(cet_anual(i) * 100), total_pago=r2(parcela_pad * n_pad), respiros=0,
        cabe=parcela_pad <= capacidade.parcela_maxima and not ruins_pad,
        motivo=(f"Parcela de {parcela_pad:.2f} passa da sua parcela máxima de {capacidade.parcela_maxima:.2f}"
                f" e não caberia em {len(ruins_pad)} dos últimos 12 meses."
                if ruins_pad or parcela_pad > capacidade.parcela_maxima else "Cabe."),
        meses_em_que_nao_cabe=ruins_pad,
    )

    # Recomendação
    if plano_a.cabe:
        recomendado = "A"
    elif plano_b.cabe and not plano_b.meses_em_que_nao_cabe:
        recomendado = "B"
    elif plano_c.cabe:
        recomendado = "C"
    else:
        recomendado = None

    resultado = {
        "saldo_total": saldo_total,
        "maior_atraso_dias": perfil.maior_atraso,
        "faixa_desconto": faixa,
        "custo_mensal_hoje": perfil.custo_total_mensal,
        "parcela_maxima": capacidade.parcela_maxima,
        "planos": [p.to_dict() for p in (plano_a, plano_b, plano_c)],
        "plano_padrao": plano_padrao.to_dict(),
        "recomendado": recomendado,
        "nenhum_plano_cabe": recomendado is None,
        "dinheiro_extra": r2(dinheiro_extra),
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


# ---------- acordo ----------

def proximo_vencimento(hoje: date, dia: int, minimo_dias: int = 10) -> date:
    """Primeiro dia `dia` a pelo menos `minimo_dias` de distância."""
    ano, mes = hoje.year, hoje.month
    while True:
        ultimo = _ultimo_dia(ano, mes)
        candidato = date(ano, mes, min(dia, ultimo))
        if (candidato - hoje).days >= minimo_dias:
            return candidato
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _ultimo_dia(ano: int, mes: int) -> int:
    prox = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return (prox - timedelta(days=1)).day


def _mes_seguinte(d: date) -> date:
    ano, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(ano, mes, min(d.day, _ultimo_dia(ano, mes)))


def criar_acordo(perfil: PerfilFinanceiro, plano: dict, hoje: date, politica: dict | None = None) -> Acordo:
    pol = politica or POLITICA_PADRAO
    if not plano.get("cabe"):
        raise ValueError("plano não cabe — não pode virar acordo")
    venc = proximo_vencimento(hoje, perfil.dia_pagamento_preferido or pol["dia_vencimento_padrao"])
    return Acordo(
        acordo_id=f"ac_{uuid4().hex[:8]}",
        cliente_id=perfil.cliente_id,
        plano_id=plano["id"],
        parcela=plano["parcela"],
        prazo=plano["prazo"],
        taxa_mensal=plano["taxa_mensal"],
        saldo_inicial=plano["saldo_base"],
        saldo_devedor=plano["saldo_base"],
        status="ativo",
        respiros_max=plano.get("respiros", 0),
        criado_em=hoje.isoformat(),
        proximo_vencimento=venc.isoformat(),
        historico=[{"data": hoje.isoformat(), "evento": "acordo_fechado", "plano": plano["id"]}],
    )


def registrar_pagamento(acordo: Acordo, data: date | None = None) -> Acordo:
    if acordo.status != "ativo":
        return acordo
    venc = date.fromisoformat(acordo.proximo_vencimento)
    data = data or venc
    if acordo.plano_id == "A":
        acordo.saldo_devedor = 0.0
    else:
        acordo.saldo_devedor = r2(acordo.saldo_devedor * (1 + acordo.taxa_mensal) - acordo.parcela)
    acordo.pagas += 1
    acordo.historico.append({"data": data.isoformat(), "evento": "parcela_paga", "n": acordo.pagas, "valor": acordo.parcela})
    if acordo.pagas >= acordo.prazo or acordo.saldo_devedor <= 0.5:
        acordo.saldo_devedor = 0.0
        acordo.status = "quitado"
        acordo.historico.append({"data": data.isoformat(), "evento": "quitado"})
    else:
        acordo.proximo_vencimento = _mes_seguinte(venc).isoformat()
    return acordo


def acionar_respiro(acordo: Acordo, data: date | None = None) -> dict:
    """Empurra a parcela do mês para o fim, sem juros nem mora (política do respiro)."""
    if acordo.status != "ativo":
        return {"ok": False, "motivo": f"acordo está {acordo.status}"}
    if acordo.respiros_usados >= acordo.respiros_max:
        return {"ok": False, "motivo": "todos os respiros do acordo já foram usados"}
    venc = date.fromisoformat(acordo.proximo_vencimento)
    data = data or venc
    acordo.respiros_usados += 1
    acordo.proximo_vencimento = _mes_seguinte(venc).isoformat()
    acordo.historico.append({"data": data.isoformat(), "evento": "respiro", "mes": venc.strftime("%Y-%m")})
    resultado = {
        "ok": True,
        "mes_do_respiro": venc.strftime("%Y-%m"),
        "proximo_vencimento": acordo.proximo_vencimento,
        "respiros_restantes": acordo.respiros_max - acordo.respiros_usados,
        "parcelas_pagas": acordo.pagas,
        "parcelas_restantes": acordo.restantes,
        "saldo_devedor": acordo.saldo_devedor,
        "explicacao": "A parcela deste mês vai para o fim do acordo, sem juros nem multa; o prazo final aumenta um mês.",
    }
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def amortizar(acordo: Acordo, valor: float, capacidade: Capacidade, perfil: PerfilFinanceiro,
              politica: dict | None = None, preservar_reserva: bool = True, aplicar: bool = False) -> dict:
    """Usa dinheiro extra para abater o saldo com desconto, preservando uma reserva se o cliente não tem."""
    pol = politica or POLITICA_PADRAO
    if acordo.status != "ativo":
        return {"ok": False, "motivo": f"acordo está {acordo.status}"}
    reserva = 0.0
    if preservar_reserva and not perfil.tem_reserva:
        reserva = r2(min(capacidade.colchao * pol["reserva_meses_colchao"], valor * pol["reserva_pct_extra"]))
    valor_amortizado = r2(valor - reserva)
    desc = pol["desconto_amortizacao"]
    abatimento = r2(min(valor_amortizado / (1 - desc), acordo.saldo_devedor))
    novo_saldo = r2(max(0.0, acordo.saldo_devedor - abatimento))
    prazo_antes = acordo.restantes
    if novo_saldo <= 0.5:
        novo_restante = 0
    else:
        novo_restante = prazo_para_parcela(novo_saldo, acordo.taxa_mensal, acordo.parcela, pol["prazo_max"]) or prazo_antes
    resultado = {
        "ok": True,
        "valor_recebido": r2(valor),
        "reserva_sugerida": reserva,
        "valor_amortizado": valor_amortizado,
        "desconto_pct": desc,
        "abatimento_no_saldo": abatimento,
        "saldo_antes": acordo.saldo_devedor,
        "saldo_depois": novo_saldo,
        "parcelas_restantes_antes": prazo_antes,
        "parcelas_restantes_depois": novo_restante,
        "parcelas_a_menos": max(0, prazo_antes - novo_restante),
        "parcela": acordo.parcela,
        "quita": novo_restante == 0,
        "explicacao": (
            f"Cada 1 real amortizado abate {1/(1-desc):.2f} do saldo. "
            + ("Sugerimos guardar parte como reserva porque você ainda não tem uma." if reserva > 0 else "")
        ),
    }
    if aplicar:
        acordo.saldo_devedor = novo_saldo
        acordo.prazo = acordo.pagas + novo_restante
        acordo.historico.append({"data": acordo.proximo_vencimento, "evento": "amortizacao", "valor": valor_amortizado, "abatimento": abatimento})
        if novo_restante == 0:
            acordo.status = "quitado"
            acordo.historico.append({"data": acordo.proximo_vencimento, "evento": "quitado"})
    resultado["numeros_permitidos"] = numeros_de(resultado)
    return resultado


def processar_vencimentos(acordo: Acordo, ate: date, meses_respiro: set[str] | None = None) -> list[dict]:
    """Avança o acordo até `ate`: paga cada vencimento vencido (ou aplica respiro agendado)."""
    meses_respiro = meses_respiro or set()
    eventos = []
    while acordo.status == "ativo" and date.fromisoformat(acordo.proximo_vencimento) <= ate:
        venc = date.fromisoformat(acordo.proximo_vencimento)
        if venc.strftime("%Y-%m") in meses_respiro and acordo.respiros_usados < acordo.respiros_max:
            eventos.append(acionar_respiro(acordo, venc))
        else:
            registrar_pagamento(acordo, venc)
            eventos.append({"evento": "parcela_paga", "data": venc.isoformat(), "pagas": acordo.pagas})
    return eventos


# ---------- utilidades ----------

def numeros_de(obj) -> list[float]:
    """Coleta todos os números de uma estrutura (para o guardrail de números do agente)."""
    achados: set[float] = set()

    def visitar(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            v = float(x)
            if math.isfinite(v):
                achados.add(r2(v))
                if 0 < abs(v) < 1:          # taxas: 0.015 -> 1.5 (%)
                    achados.add(r2(v * 100))
        elif isinstance(x, dict):
            for k, v in x.items():
                if k != "numeros_permitidos":
                    visitar(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                visitar(v)

    visitar(obj)
    return sorted(achados)
