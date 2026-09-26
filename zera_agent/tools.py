"""Tools determinísticas do Zera (ADK function tools).

Regras:
- Nenhuma tool chama LLM. Toda conta vem de `motor/`.
- Toda resposta traz `numeros_permitidos` (guardrail de números) e `explicacao` (o que o agente pode citar).
- Ações com efeito (fechar_acordo, acionar_respiro, amortizar) exigem consentimento registrado na sessão
  — verificado pelo `before_tool_callback` em guardrails.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from google.adk.tools import ToolContext

from motor import (
    acionar_respiro as _acionar_respiro,
    amortizar as _amortizar,
    criar_acordo,
    criar_acordo_de_cenario,
    montar_cenarios as _montar_cenarios,
    numeros_de,
    priorizar_dividas as _priorizar,
    simular_planos as _simular,
)
from zera_agent.contexto import Contexto

ACOES_COM_CONSENTIMENTO = {"fechar_acordo", "acionar_respiro", "amortizar"}


def _ctx(tool_context: ToolContext) -> Contexto:
    return Contexto.para(tool_context.state.get("cliente_id", "cli_001"))


def _ui(tool_context: ToolContext, tipo: str, dados: dict) -> None:
    """Guarda blocos ricos para a UI renderizar como cards."""
    blocos = list(tool_context.state.get("ui", []))
    blocos.append({"tipo": tipo, "dados": dados})
    tool_context.state["ui"] = blocos[-6:]


# ---------- Diagnóstico ----------

def get_perfil_financeiro(tool_context: ToolContext) -> dict:
    """Raio-X consolidado do cliente: dívidas (saldo, taxa, custo mensal, atraso), total devido,
    quanto a dívida cresce por mês, renda e contas essenciais dos últimos 12 meses."""
    c = _ctx(tool_context)
    p = c.perfil
    resposta = {
        "cliente": p.nome,
        "hoje": c.estado["hoje"],
        "dividas": [d.to_dict() for d in p.dividas],
        "total_dividas": p.total_dividas,
        "custo_total_mensal": p.custo_total_mensal,
        "renda_mediana": p.renda_mediana,
        "essenciais_mediana": p.essenciais_mediana,
        "sobra_mediana": c.capacidade.sobra_mediana,
        "meses": p.meses,
        "sobra_por_mes": dict(zip(p.meses, p.sobra_mensal)),
        "tem_reserva": p.tem_reserva,
        "explicacao": (
            f"Hoje a dívida cresce {p.custo_total_mensal:.2f} por mês só de juros; "
            f"a sobra típica depois das contas essenciais é {c.capacidade.sobra_mediana:.2f}."
        ),
    }
    resposta["numeros_permitidos"] = numeros_de(resposta)
    _ui(tool_context, "raio_x", resposta)
    return resposta


def calcular_capacidade(tool_context: ToolContext) -> dict:
    """Capacidade real de pagamento: sobra segura, parcela máxima, meses fracos e respiros por ano,
    com a explicação de como foi calculada."""
    c = _ctx(tool_context)
    resposta = c.capacidade.to_dict()
    resposta["numeros_permitidos"] = numeros_de(resposta)
    _ui(tool_context, "capacidade", resposta)
    return resposta


def priorizar_dividas(tool_context: ToolContext) -> dict:
    """Ordem em que as dívidas devem ser atacadas, por custo mensal e consequência (negativação, corte)."""
    c = _ctx(tool_context)
    resposta = _priorizar(c.perfil, c.politica)
    resposta["numeros_permitidos"] = numeros_de(resposta)
    _ui(tool_context, "prioridades", resposta)
    return resposta


# ---------- Negociador ----------

def simular_planos(tool_context: ToolContext, dinheiro_extra: float = 0.0) -> dict:
    """Simula os planos de renegociação: A (à vista com desconto), B (parcela que cabe),
    C (parcela que cabe + respiros) e o plano padrão de 12x usado como contraste.
    `dinheiro_extra`: valor disponível agora (13º, restituição, FGTS), se houver."""
    c = _ctx(tool_context)
    resposta = _simular(c.perfil, c.capacidade, c.politica, dinheiro_extra=dinheiro_extra)
    tool_context.state["planos"] = {p["id"]: p for p in resposta["planos"]}
    _ui(tool_context, "planos", resposta)
    c.registrar_evento("plano_proposto", {"recomendado": resposta["recomendado"]})
    return resposta


def montar_cenarios(tool_context: ToolContext, valor_extra: float = 0.0) -> dict:
    """PRINCIPAL: dado o dinheiro extra disponível (FGTS, 13º, restituição, renda extra — ou 0), monta os cenários
    por dívida: qual quitar à vista com desconto, qual renegociar em 12x/18x/24x/36x e qual manter, respeitando
    a parcela máxima, a parcela de conforto do perfil (renda irregular) e os respiros. Devolve o recomendado
    (mais barato dentro do conforto que tira o cliente da negativação) e alternativas: mais_barato, mais_folga, mais_rapido."""
    c = _ctx(tool_context)
    resposta = _montar_cenarios(c.perfil, c.capacidade, valor_extra=valor_extra, politica=c.politica)
    tool_context.state["cenarios"] = {cen["id"]: cen for cen in resposta.get("cenarios", [])}
    _ui(tool_context, "cenarios", resposta)
    c.registrar_evento("cenarios_propostos", {"valor_extra": valor_extra, "recomendado": resposta.get("recomendado")})
    return resposta


def comparar_com_padrao(tool_context: ToolContext, plano_id: str) -> dict:
    """Compara um plano (A, B ou C) com a renegociação padrão de 12x e com a situação de hoje."""
    c = _ctx(tool_context)
    planos = tool_context.state.get("planos") or {p["id"]: p for p in _simular(c.perfil, c.capacidade, c.politica)["planos"]}
    plano = planos.get(plano_id.upper())
    if not plano:
        return {"erro": f"plano {plano_id} não existe; use A, B ou C"}
    padrao = _simular(c.perfil, c.capacidade, c.politica)["plano_padrao"]
    resposta = {
        "plano": plano_id.upper(),
        "parcela_plano": plano["parcela"],
        "prazo_plano": plano["prazo_nominal"],
        "parcela_padrao": padrao["parcela"],
        "prazo_padrao": padrao["prazo"],
        "meses_em_que_padrao_nao_cabe": padrao["meses_em_que_nao_cabe"],
        "qtd_meses_padrao_nao_cabe": len(padrao["meses_em_que_nao_cabe"]),
        "custo_mensal_hoje": c.perfil.custo_total_mensal,
        "parcela_maxima": c.capacidade.parcela_maxima,
        "explicacao": (
            f"O padrão de {padrao['prazo']}x cobra {padrao['parcela']:.2f} por mês e não caberia em "
            f"{len(padrao['meses_em_que_nao_cabe'])} dos últimos 12 meses; o plano {plano_id.upper()} cobra "
            f"{plano['parcela']:.2f} e fica dentro da parcela máxima de {c.capacidade.parcela_maxima:.2f}. "
            f"Hoje a dívida cresce {c.perfil.custo_total_mensal:.2f} por mês sem acordo."
        ),
    }
    resposta["numeros_permitidos"] = numeros_de(resposta)
    return resposta


# ---------- Consentimento ----------

def registrar_consentimento(tool_context: ToolContext, acao: str, frase_cliente: str) -> dict:
    """Registra o consentimento explícito do cliente para uma ação (fechar_acordo, acionar_respiro, amortizar),
    guardando a frase exata do cliente e o horário. Chame SOMENTE depois de o cliente confirmar."""
    if acao not in ACOES_COM_CONSENTIMENTO:
        return {"ok": False, "erro": f"ação desconhecida: {acao}", "acoes_validas": sorted(ACOES_COM_CONSENTIMENTO)}
    c = _ctx(tool_context)
    registro = {
        "consentimento_id": f"cs_{uuid4().hex[:8]}",
        "acao": acao,
        "frase_cliente": frase_cliente,
        "versao_termo": "demo-v1",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "data_simulada": c.estado["hoje"],
    }
    consentimentos = dict(tool_context.state.get("consentimento", {}))
    consentimentos[acao] = registro
    tool_context.state["consentimento"] = consentimentos
    c.estado["consentimentos"].append(registro)
    c.registrar_evento("consentimento_registrado", {"acao": acao})
    return {"ok": True, **registro, "explicacao": "Consentimento registrado; a ação pode ser executada."}


def revogar_consentimento(tool_context: ToolContext) -> dict:
    """Direito de esquecer (LGPD): apaga memória, consentimentos e estado do cliente no Zera."""
    c = _ctx(tool_context)
    c.resetar()
    tool_context.state["consentimento"] = {}
    tool_context.state["ui"] = []
    return {"ok": True, "apagado": ["memoria", "consentimentos", "acordo_simulado", "gatilhos"],
            "explicacao": "Apagamos o que o Zera guardava sobre você. O extrato segue as regras de retenção do banco."}


# ---------- Acompanhamento ----------

def fechar_acordo(tool_context: ToolContext, plano_id: str) -> dict:
    """Fecha o acordo escolhido: um cenário de montar_cenarios (C1, C2, ...) ou um plano consolidado (A, B, C).
    Exige consentimento registrado para 'fechar_acordo'."""
    c = _ctx(tool_context)
    pid = plano_id.strip().upper()
    cenarios = tool_context.state.get("cenarios") or {}
    if pid in cenarios:
        cen = cenarios[pid]
        acordo = criar_acordo_de_cenario(c.perfil, cen, c.hoje, c.politica)
        c.salvar(acordo)
        c.registrar_evento("acordo_fechado", {"cenario": pid, "parcela": acordo.parcela, "prazo": acordo.prazo,
                                              "quitacoes": [q["nome"] for q in acordo.quitacoes]})
        quit_txt = "; ".join(f"{q['nome']} quitado por {q['valor_pago']:.2f}" for q in acordo.quitacoes) or "nenhuma quitação"
        comp_txt = "; ".join(f"{k['nome']} em {k['prazo']}x de {k['parcela']:.2f}" for k in acordo.componentes) or "nenhuma parcela"
        resposta = {"ok": True, **acordo.to_dict(),
                    "explicacao": f"Acordo fechado. Quitações: {quit_txt}. Parcelas: {comp_txt}. Total por mês: {acordo.parcela:.2f}"
                                  f"{', primeira em ' + acordo.proximo_vencimento if acordo.proximo_vencimento else ''}, "
                                  f"com {acordo.respiros_max} respiro(s) por ano. Todas as dívidas do acordo saem do atraso."}
        resposta["numeros_permitidos"] = numeros_de(resposta)
        _ui(tool_context, "acordo", resposta)
        return resposta
    planos = tool_context.state.get("planos") or {p["id"]: p for p in _simular(c.perfil, c.capacidade, c.politica)["planos"]}
    plano = planos.get(pid)
    if not plano:
        return {"ok": False, "erro": f"plano/cenário {plano_id} não existe; chame montar_cenarios primeiro"}
    if not plano["cabe"]:
        return {"ok": False, "erro": "esse plano não cabe na sobra do cliente", "motivo": plano["motivo"]}
    acordo = criar_acordo(c.perfil, plano, c.hoje, c.politica)
    c.salvar(acordo)
    c.registrar_evento("acordo_fechado", {"plano": pid, "parcela": acordo.parcela, "prazo": acordo.prazo})
    resposta = {"ok": True, **acordo.to_dict(),
                "explicacao": f"Acordo ativo: {acordo.prazo} parcelas de {acordo.parcela:.2f}, primeira em {acordo.proximo_vencimento}, "
                              f"com {acordo.respiros_max} respiro(s) por ano."}
    resposta["numeros_permitidos"] = numeros_de(resposta)
    _ui(tool_context, "acordo", resposta)
    return resposta


def status_acordo(tool_context: ToolContext) -> dict:
    """Situação do acordo: parcelas pagas/restantes, saldo devedor, próximo vencimento, respiros."""
    c = _ctx(tool_context)
    acordo = c.acordo
    if acordo is None:
        return {"ok": False, "erro": "não há acordo ativo", "hoje": c.estado["hoje"]}
    resposta = {"ok": True, "hoje": c.estado["hoje"], **acordo.to_dict(),
                "sobra_prevista_mes": c.estado.get("sobra_prevista_mes"),
                "explicacao": f"{acordo.pagas} pagas, {acordo.restantes} restantes, saldo {acordo.saldo_devedor:.2f}."}
    resposta["numeros_permitidos"] = numeros_de(resposta)
    _ui(tool_context, "acordo", resposta)
    return resposta


def acionar_respiro(tool_context: ToolContext) -> dict:
    """Usa um respiro: a parcela do mês vai para o fim do acordo, sem juros nem mora.
    Exige consentimento registrado para 'acionar_respiro'."""
    c = _ctx(tool_context)
    acordo = c.acordo
    if acordo is None:
        return {"ok": False, "erro": "não há acordo ativo"}
    resposta = _acionar_respiro(acordo, c.hoje)
    if resposta.get("ok"):
        c.salvar(acordo)
        c.registrar_evento("respiro_acionado", {"mes": resposta["mes_do_respiro"]})
        _ui(tool_context, "acordo", {**acordo.to_dict(), "respiro": resposta})
    return resposta


def amortizar(tool_context: ToolContext, valor: float, preservar_reserva: bool = True, aplicar: bool = False) -> dict:
    """Simula (aplicar=False) ou executa (aplicar=True) o uso de dinheiro extra para abater o saldo com desconto,
    sugerindo guardar uma reserva se o cliente não tem. Executar exige consentimento para 'amortizar'."""
    c = _ctx(tool_context)
    acordo = c.acordo
    if acordo is None:
        return {"ok": False, "erro": "não há acordo ativo"}
    resposta = _amortizar(acordo, valor, c.capacidade, c.perfil, c.politica, preservar_reserva=preservar_reserva, aplicar=aplicar)
    if aplicar and resposta.get("ok"):
        c.salvar(acordo)
        c.registrar_evento("amortizacao", {"valor": valor, "abatimento": resposta["abatimento_no_saldo"]})
    _ui(tool_context, "amortizacao", resposta)
    return resposta


def listar_gatilhos(tool_context: ToolContext) -> dict:
    """Gatilhos proativos pendentes para o cliente (risco de parcela, dinheiro extra, pré-negativação)."""
    c = _ctx(tool_context)
    g = c.estado.get("gatilhos_pendentes", [])
    return {"hoje": c.estado["hoje"], "gatilhos": g, "numeros_permitidos": numeros_de(g)}


def escalar_humano(tool_context: ToolContext, motivo: str) -> dict:
    """Encaminha o cliente para atendimento humano (vulnerabilidade, pedido do cliente ou nenhum plano cabe)."""
    c = _ctx(tool_context)
    protocolo = f"ZR-{uuid4().hex[:6].upper()}"
    c.estado["escalonamentos"].append({"protocolo": protocolo, "motivo": motivo, "data": c.estado["hoje"]})
    c.registrar_evento("escalado_humano", {"motivo": motivo, "protocolo": protocolo})
    return {"ok": True, "protocolo": protocolo, "previsao_contato": "até 1 dia útil",
            "explicacao": "Uma pessoa do time vai entrar em contato. Nenhuma ação é executada até lá."}


TOOLS_DIAGNOSTICO = [get_perfil_financeiro, calcular_capacidade, priorizar_dividas]
TOOLS_NEGOCIADOR = [montar_cenarios, simular_planos, comparar_com_padrao]
TOOLS_ACOMPANHAMENTO = [fechar_acordo, status_acordo, acionar_respiro, amortizar, listar_gatilhos]
TOOLS_ROOT = [registrar_consentimento, revogar_consentimento, escalar_humano]
TODAS = TOOLS_DIAGNOSTICO + TOOLS_NEGOCIADOR + TOOLS_ACOMPANHAMENTO + TOOLS_ROOT
