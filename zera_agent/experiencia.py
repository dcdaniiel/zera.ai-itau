"""Orquestrador determinístico da experiência zera.ai (spec "Agent Behavior & Content Specification v1").

Máquina de estados + decision engine (ASK / TOOL / CONFIRM / RESPOND) + contrato de resposta estruturado.
O LLM NÃO decide o fluxo: entra só para explicar (EXPLAINING) e para perguntas livres (ASK_QUESTION),
sempre atrás dos guardrails e depois do roteamento determinístico de intenção. Todo número vem do núcleo (`motor/`).

    IDLE -> EVALUATING -> NEEDS_INFORMATION -> EVALUATING -> CALCULATING -> SHOWING_OPTIONS
         -> EXPLAINING / REVIEWING -> AWAITING_CONFIRMATION -> EXECUTING -> COMPLETED | ERROR | NO_SUITABLE_OPTION

Garantias (quadro de produto, itens 13, 16, 18, 20):
  * todo estado × ação tem transição definida — nunca um beco sem saída; texto livre é roteado antes do LLM;
  * NO_SUITABLE_OPTION explica o porquê (diagnóstico do motor) e oferece ajustar, informar entrada ou falar com pessoa;
  * só a ação CONFIRM contrata; "sim" digitado nunca executa nada;
  * condição que não existe (desconto no principal, juros zero) recebe resposta honesta com o que existe.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime
from typing import Awaitable, Callable
from uuid import uuid4

from motor import criar_acordo_de_cenario, montar_cenarios, resumo_cenario, situacao_hoje, termos
from motor.beneficios import (
    ORDEM_OBJETIVOS,
    beneficio_principal,
    claims,
    criterio_recomendacao,
    objetivo_de,
    tradeoffs,
    validar_beneficios,
)
from motor.modelos import brl, r2
from zera_agent.contexto import Contexto
from zera_agent.observabilidade import medir, registrar_metrica

log = logging.getLogger("zera.experiencia")

ESTADOS = ["IDLE", "EVALUATING", "NEEDS_INFORMATION", "CALCULATING", "SHOWING_OPTIONS", "EXPLAINING", "REVIEWING",
           "AWAITING_CONFIRMATION", "EXECUTING", "COMPLETED", "NO_SUITABLE_OPTION", "ERROR"]
ACOES = ["GET", "RESET", "START", "ANSWER", "VIEW_OPTIONS", "SELECT_OPTION", "ASK_WHY", "ASK_QUESTION", "CONTINUE",
         "SET_AUTOPAY", "CONFIRM", "CANCEL", "DISMISS", "ESCALATE", "ADJUST", "RETRY", "HOME", "FOLLOW", "CANCEL_AUTOPAY"]
ACOES_SENSIVEIS = {"CONFIRM"}
PREFERENCIAS_PADRAO = {"analisar": True, "momentos": True, "recomendar": True, "avisar": True, "open_finance": False}
DISCLAIMER = "Resposta gerada por IA e pode ter informações imprecisas."
STATUS_CALCULO = {"title": "Buscando uma parcela que cabe no seu bolso...",
                  "steps": ["Considerando seus gastos do mês", "Comparando suas dívidas", "Calculando opções"]}
STATUS_EXECUCAO = {"title": "Finalizando sua contratação...",
                   "steps": ["Validando suas informações", "Formalizando a contratação", "Configurando o débito automático",
                             "Reunindo suas dívidas", "Confirmando a conclusão"]}
MENSAGENS_PROATIVAS = {
    "entrada_rotativo": ("Diminua suas parcelas", "{nome}, quer ajuda para organizar seus próximos pagamentos? Dá para reunir suas dívidas em uma parcela que cabe no seu bolso.", "Diminuir parcelas"),
    "pre_negativacao": ("Vamos colocar as contas em dia?", "{nome}, existe um jeito de organizar seus pagamentos com uma parcela que cabe no seu mês, antes que o atraso vire negativação.", "Ver como"),
    "dinheiro_extra": ("Entrou um dinheiro extra", "{nome}, dá para usar parte dele para quitar a dívida mais cara e diminuir suas parcelas — guardando uma reserva.", "Ver a melhor forma de usar"),
    "risco_parcela": ("Sua parcela vence em breve", "{nome}, se este mês está apertado, você pode usar um respiro: a parcela vai para o fim do acordo, sem juros.", "Ver opções"),
}

Explicador = Callable[[str, list[float]], Awaitable[str]]  # (pergunta, numeros_permitidos) -> texto do LLM


def _resposta(state: str, response_type: str, title: str, description: str = "", **extra) -> dict:
    base = {"state": state, "response_type": response_type, "content": {"title": title, "description": description},
            "options": [], "quick_replies": [], "allowed_actions": [], "requires_confirmation": False,
            "disclaimer": DISCLAIMER}
    base.update(extra)
    return base


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch)).strip()


def _numero_em(texto: str) -> float | None:
    m = re.search(r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)", texto)
    if not m:
        return None
    bruto = m.group(1)
    if "." in bruto and "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif "," in bruto:
        bruto = bruto.replace(",", ".")
    elif bruto.count(".") == 1 and len(bruto.split(".")[1]) == 3:
        bruto = bruto.replace(".", "")
    try:
        return float(bruto)
    except ValueError:
        return None


# padrões de intenção (texto normalizado, sem acento)
RE_ESCALAR = re.compile(r"\b(pessoa|atendente|humano|gerente|alguem|atendimento|ligar|telefone|falar com)\b")
RE_CANCELAR = re.compile(r"\b(agora nao|depois|desist|cancel|parar|pausa|sair|deixa pra la|deixa para la|nao quero)\b")
RE_OPCOES = re.compile(r"\b(opcao|opcoes|alternativa|alternativas|outras|ver mais|mostra|mostrar|me ajud|ajuda|ajudar|quero ver|simula|simular|calcul|comecar|vamos la|bora|quanto fica|quanto ficaria|proposta|renegoci|parcelar|reunir)\b")
RE_PORQUE = re.compile(r"\b(por ?que|pq|motivo|explica|explicar|entender|entendi nao|nao entendi)\b")
RE_SIM = re.compile(r"^(sim|confirmo|confirmar|aceito|pode|fechar|fecha|quero|ok|isso|topo|bora|vamos|continuar|continua|seguir|segue|avancar|proximo)\b")
RE_NAO = re.compile(r"^(nao|nenhum|nada|n)\b")
RE_CONDICAO_INEXISTENTE = re.compile(r"\b(sem juros|juros zero|zero juros|desconto|abatimento|perdao|perdoar|zerar|cancelar a divida|tirar o nome|limpar o nome|limpar meu nome|sem entrada)\b")
RE_LGPD = re.compile(r"\b(apagar (meus |os )?dados|apague (meus |os )?dados|esquecer de mim|esqueca de mim|revogar|excluir (minha )?conta)\b")
RE_SAUDACAO = re.compile(r"^(oi|ola|bom dia|boa tarde|boa noite|obrigad[oa]?|valeu|brigad[oa]?)\b")
RE_PRAZO = re.compile(r"\b(\d{1,3})\s?(x|meses|vezes|parcelas)\b")
RE_ROTULO = {"lower_monthly_payment": re.compile(r"menor parcela|mais folga|parcela menor|mais barata por mes"),
             "lower_total_cost": re.compile(r"mais barat|menor custo|menos juros|terminar antes|mais rapid|menor prazo"),
             "balanced": re.compile(r"equilibr|recomendad|a primeira|essa mesmo|esta mesmo|essa opcao|esta opcao"),
             "keep_cash": re.compile(r"guardar|sem usar o dinheiro|nao usar o dinheiro")}


class Experiencia:
    """Uma instância por cliente. Estado persistido em `estado['experiencia']` (JSON local ou BigQuery)."""

    def __init__(self, ctx: Contexto, explicador: Explicador | None = None):
        self.ctx = ctx
        self.explicador = explicador
        self.exp = ctx.estado.setdefault("experiencia", {})
        for k, v in {"state": "IDLE", "perguntas_feitas": [], "selected_option": None, "autopay": None, "valor_extra": 0.0,
                     "opcoes": [], "cenarios": {}, "hoje": None, "contatos_proativos": [], "diagnostico": None,
                     "escalado": None, "jornada_id": None, "historico": []}.items():
            self.exp.setdefault(k, v)
        ctx.estado.setdefault("preferencias", dict(PREFERENCIAS_PADRAO))

    # ------------------------------------------------------------------ util
    @property
    def state(self) -> str:
        return self.exp["state"]

    def _ir(self, novo: str) -> None:
        if novo != self.exp["state"]:
            log.info("transicao", extra={"zera": {"cliente": self.ctx.cliente_id, "de": self.exp["state"], "para": novo, "jornada_id": self.exp.get("jornada_id")}})
            registrar_metrica("zera.transicao", 1, {"de": self.exp["state"], "para": novo})
        self.exp["state"] = novo
        self.ctx.salvar()

    def _salvar(self) -> None:
        self.ctx.salvar()

    def _valor_extra(self) -> float:
        g = next((g for g in self.ctx.estado.get("gatilhos_pendentes", []) if g.get("tipo") == "dinheiro_extra"), None)
        informado = float(self.exp.get("valor_extra") or 0.0)
        return max(float(g.get("valor", 0.0)) if g else 0.0, informado)

    def _nome(self) -> str:
        return (self.ctx.perfil.nome or "").split(" ")[0] or "Cliente"

    def _contexto(self) -> dict:
        """O que a interface mostra como 'considerado': gasto informado, dinheiro extra, capacidade, origem dos dados."""
        p = self.ctx.perfil
        return {"cliente": p.nome, "persona": p.persona, "fonte": p.fonte, "renda_desconhecida": p.renda_desconhecida,
                "renda_informada": p.renda_informada, "compromissos": self.ctx.estado.get("compromissos_extras", []),
                "valor_extra": self._valor_extra(), "parcela_maxima": self.ctx.capacidade.parcela_maxima,
                "parcela_conforto": self.exp.get("parcela_conforto"), "hoje_simulado": self.ctx.estado.get("hoje"),
                "escalado": self.exp.get("escalado"), "autopay": self.ctx.estado.get("debito_automatico")}

    # ------------------------------------------------------------------ cálculo (TOOL -> núcleo determinístico)
    def _calcular(self) -> tuple[dict, list[dict], dict]:
        """Hoje vs opções, com benefícios validados por opção. Levanta exceção se a fonte falhar (AT09)."""
        c = self.ctx
        with medir("motor.montar_cenarios", {"cliente": c.cliente_id}):
            hoje = situacao_hoje(c.perfil, c.politica)
            r = montar_cenarios(c.perfil, c.capacidade, valor_extra=self._valor_extra(), politica=c.politica)
        opcoes = []
        for cen in r.get("cenarios", []):
            rc = resumo_cenario(cen, hoje, c.politica)
            objetivo, label, desc = objetivo_de(cen.get("rotulos", []), cen.get("prazo_meses"))
            beneficios = validar_beneficios(hoje, rc)
            oid = objetivo.lower() if objetivo != "INTERMEDIATE" else f"prazo_{cen['prazo_meses']}"
            opcoes.append({
                "id": oid, "cenario_id": cen["id"], "objective": objetivo, "label": label, "description": desc,
                "recommended": "recomendado" in cen.get("rotulos", []), "highlight": bool(cen.get("rotulos")),
                "monthly_payment": rc["parcela_mensal"], "agreement_payment": rc["parcela_acordo"], "term_months": rc["prazo_meses"],
                "total_cost": rc["total_a_pagar"], "total_installments": rc["total_parcelas"], "interest_total": rc["juros_acordo"],
                "rate_monthly_pct": rc["taxa_mensal_pct"], "cet_annual_pct": rc["cet_anual_pct"],
                "principal": rc["saldo_original"], "consolidated_balance": rc["saldo_consolidado"],
                "down_payment": rc["entrada"], "payoffs_value": rc["quitacoes_valor"], "reserve": rc["reserva"], "uses_cash": rc["usa_caixa"],
                "bank_gain": rc["ganho_banco"], "bank_receives": rc["recebido_banco"],
                "today_same_term": rc["hoje_mesmo_prazo"], "savings_same_term": rc["economia_vs_hoje_mesmo_prazo"],
                "payments_count": rc["qtd_pagamentos"], "freed_per_month": rc["liberado_por_mes"],
                "benefits": beneficios, "claims": claims(beneficios), "tradeoffs": tradeoffs(hoje, rc),
                "actions": cen["acoes"], "resolve_negativacao": cen.get("resolve_negativacao", False),
                "autopay": rc["debito_automatico"], "numeros_permitidos": rc["numeros_permitidos"],
            })
        opcoes.sort(key=lambda o: (ORDEM_OBJETIVOS.index(o["objective"]) if o["objective"] in ORDEM_OBJETIVOS else 9, o["term_months"]))
        return hoje, opcoes, r

    # ------------------------------------------------------------------ proatividade (§7)
    def avaliar_proatividade(self) -> dict:
        """TRIGGER -> CONTEXT -> OPPORTUNITY -> BENEFIT -> CONTENT. Qualquer pré-condição falhando => silêncio."""
        prefs = self.ctx.estado.get("preferencias", PREFERENCIAS_PADRAO)
        gatilhos = self.ctx.estado.get("gatilhos_pendentes", [])
        ativa = self.exp.get("proativa_ativa")  # mensagem já enviada hoje e ainda não dispensada (re-exibida, não é novo contato)
        checks = {"proactive_permission": bool(prefs.get("avisar", False)), "trigger_present": bool(gatilhos),
                  "opportunity_found": False, "benefit_validated": False, "required_context_available": False,
                  "action_available": False, "contact_frequency_allowed": True}
        hoje_sim = self.ctx.estado["hoje"]
        ultimos = self.exp.get("contatos_proativos", [])
        if ultimos and ultimos[-1] == hoje_sim and not ativa:
            checks["contact_frequency_allowed"] = False  # no máximo 1 contato proativo NOVO por dia (simulado)
        acordo = self.ctx.estado.get("acordo")
        if acordo and acordo.get("status") == "ativo" and not gatilhos:
            # acompanhamento (design: "Sua nova opção — Acompanhar"): não é contato proativo novo, é o card do acordo
            return _resposta("COMPLETED", "PROACTIVE_MESSAGE", "Sua nova opção", "Acompanhe sua parcela e mantenha tudo sob controle.",
                             cta="Acompanhar", trigger="acordo_ativo", checks=checks, allowed_actions=["START", "DISMISS"], silent=False,
                             agreement=acordo, acompanhamento=True)
        if not (checks["proactive_permission"] and checks["trigger_present"]):
            return {"silent": True, "checks": checks, "reason": "sem permissão ou sem gatilho"}
        gatilho = gatilhos[0]
        acordo_ativo = bool(self.ctx.estado.get("acordo")) and self.ctx.acordo is not None and self.ctx.acordo.status == "ativo"
        if acordo_ativo and gatilho.get("tipo") == "dinheiro_extra":
            checks["action_available"] = False
            return {"silent": True, "checks": checks, "reason": "acordo ativo: dinheiro extra segue outro fluxo (amortização)"}
        if self.ctx.perfil.renda_desconhecida:
            checks["required_context_available"] = False
            return {"silent": True, "checks": checks, "reason": "renda não identificada no extrato: sem contexto suficiente para abordar proativamente"}
        if acordo_ativo and gatilho.get("tipo") == "risco_parcela":
            checks.update({"opportunity_found": True, "benefit_validated": True, "required_context_available": True, "action_available": True})
            if ativa:
                return {**ativa, "checks": checks, "repetida": True}
            titulo, desc, cta = MENSAGENS_PROATIVAS["risco_parcela"]
            msg = _resposta("IDLE", "PROACTIVE_MESSAGE", titulo, desc.format(nome=self._nome()), cta=cta,
                            benefit={"benefit_type": "BREATHER", "respiros_restantes": gatilho.get("respiros_restantes")},
                            trigger="risco_parcela", checks=checks, allowed_actions=["START", "DISMISS"], silent=False)
            self._registrar_proativa(msg, hoje_sim, ultimos, gatilho, "BREATHER")
            return msg
        try:
            hoje, opcoes, r = self._calcular()
        except Exception as e:  # noqa: BLE001
            return {"silent": True, "checks": checks, "reason": f"fonte de dados indisponível: {e}"}
        checks["required_context_available"] = bool(self.ctx.perfil.renda_mensal) and bool(self.ctx.perfil.dividas)
        rec = next((o for o in opcoes if o["recommended"]), None)
        checks["opportunity_found"] = rec is not None
        principal = beneficio_principal(rec["benefits"]) if rec else None
        checks["benefit_validated"] = principal is not None
        checks["action_available"] = rec is not None and not r.get("nenhum_cenario_cabe", False)
        if not all(checks.values()):
            return {"silent": True, "checks": checks, "reason": "pré-condição de proatividade não atendida"}
        if ativa:  # tudo continua válido: re-exibe a mesma mensagem (benefício revalidado agora)
            return {**ativa, "benefit": principal, "checks": checks, "repetida": True}
        self.exp["hoje"] = hoje
        titulo, desc, cta = MENSAGENS_PROATIVAS.get(gatilho["tipo"], MENSAGENS_PROATIVAS["entrada_rotativo"])
        msg = _resposta("IDLE", "PROACTIVE_MESSAGE", titulo, desc.format(nome=self._nome()), cta=cta, benefit=principal,
                        trigger=gatilho["tipo"], checks=checks, allowed_actions=["START", "DISMISS"], silent=False,
                        numeros_permitidos=rec["numeros_permitidos"])
        self._registrar_proativa(msg, hoje_sim, ultimos, gatilho, principal["benefit_type"])
        return msg

    def _registrar_proativa(self, msg: dict, hoje_sim: str, ultimos: list, gatilho: dict, beneficio: str) -> None:
        self.exp["contatos_proativos"] = (ultimos + [hoje_sim])[-30:]
        self.exp["proativa_ativa"] = msg
        self._salvar()
        self.ctx.registrar_evento("proativa_enviada", {"benefit": beneficio, "gatilho": gatilho["tipo"]})
        registrar_metrica("zera.proativa_enviada", 1, {"gatilho": gatilho["tipo"]})

    # ------------------------------------------------------------------ eventos do usuário
    async def evento(self, acao: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        acao = (acao or "").upper()
        inicio = time.perf_counter()
        estado_antes = self.state
        if not self.exp.get("jornada_id"):
            self.exp["jornada_id"] = f"j_{uuid4().hex[:10]}"
        try:
            resposta = await self._despachar(acao, payload)
        except Exception as e:  # noqa: BLE001 — falha de tool/dado: nunca inventar (AT09)
            log.exception("erro na experiência")
            resposta = self._erro(str(e))
        resposta.setdefault("jornada_id", self.exp.get("jornada_id"))
        resposta.setdefault("context", self._contexto())
        self.exp["historico"] = (self.exp.get("historico") or [])[-19:] + [{"acao": acao, "de": estado_antes, "para": self.state,
                                                                            "tipo": resposta.get("response_type")}]
        self._salvar()
        registrar_metrica("zera.evento", 1, {"acao": acao, "estado": estado_antes, "resultado": resposta.get("response_type")})
        registrar_metrica("zera.evento_latencia_ms", (time.perf_counter() - inicio) * 1000, {"acao": acao})
        return resposta

    async def _despachar(self, acao: str, payload: dict) -> dict:
        if acao == "RESET":
            self.ctx.resetar()
            self.__init__(self.ctx, self.explicador)
            return self.resposta_atual()
        if acao in ("GET", "HOME", "FOLLOW"):
            return self.resposta_atual()
        if acao == "START":
            return self._start()
        if acao == "ANSWER":
            return self._answer(payload)
        if acao == "VIEW_OPTIONS":
            return self._view_options()
        if acao == "ASK_WHY":
            return await self._ask_why(payload)
        if acao == "ASK_QUESTION":
            return await self._ask_question(payload)
        if acao == "SELECT_OPTION":
            return self._select(payload)
        if acao == "CONTINUE":
            return self._continue()
        if acao == "SET_AUTOPAY":
            return self._set_autopay(payload)
        if acao == "CONFIRM":
            return self._confirm(payload)
        if acao == "CANCEL":
            return self._cancel()
        if acao == "DISMISS":
            self.exp["proativa_ativa"] = None
            self.ctx.registrar_evento("proativa_dispensada", {})
            self._ir("IDLE")
            return self.resposta_atual()
        if acao == "ESCALATE":
            return self._escalate(payload)
        if acao == "ADJUST":
            return self._adjust(payload)
        if acao == "RETRY":
            return self._retry()
        if acao == "CANCEL_AUTOPAY":
            return self._cancel_autopay()
        return self._orientar(f"Não conheço a ação {acao}.", motivo="acao_desconhecida")

    def _cancel_autopay(self) -> dict:
        """Acompanhamento: desliga o débito automático do acordo ativo (a parcela volta ao valor sem desconto)."""
        acordo = self.ctx.acordo
        if acordo is None or acordo.status != "ativo" or not self.ctx.estado.get("debito_automatico"):
            return self._orientar("Não há débito automático ativo para cancelar.", motivo="sem_autopay")
        pct = self.ctx.politica["desconto_debito_automatico_pct"]
        for comp in acordo.componentes:
            comp["parcela"] = r2(comp["parcela"] / (1 - pct))
        acordo.parcela = r2(sum(c["parcela"] for c in acordo.componentes_ativos)) if acordo.componentes else r2(acordo.parcela / (1 - pct))
        acordo.historico.append({"data": self.ctx.estado["hoje"], "evento": "debito_automatico_cancelado"})
        self.ctx.estado["debito_automatico"] = False
        self.ctx.salvar(acordo)
        self.ctx.registrar_evento("debito_automatico_cancelado", {"parcela": acordo.parcela})
        r = self._entrada()
        r["content"]["title"] = "Débito automático cancelado."
        r["content"]["description"] = f"Sua parcela passa a {brl(acordo.parcela)} por mês e você recebe o boleto todo mês. Pode reativar quando quiser."
        return r

    # --- IDLE / entrada
    def resposta_atual(self) -> dict:
        st = self.state
        if self.exp.get("escalado") and st in ("NO_SUITABLE_OPTION", "ERROR", "IDLE"):
            return self._tela_escalado()
        if st == "NO_SUITABLE_OPTION":
            return self._sem_opcao()
        if st in ("IDLE", "COMPLETED", "ERROR", "EVALUATING", "EXECUTING"):
            return self._entrada()
        if st == "NEEDS_INFORMATION":
            return self._pergunta_pendente()
        if st in ("SHOWING_OPTIONS", "CALCULATING"):
            return self._showing()
        if st == "EXPLAINING":
            return self._showing(comparacao=True)
        if st == "REVIEWING":
            return self._termos(self.exp.get("autopay"))
        if st == "AWAITING_CONFIRMATION":
            return self._confirmacao()
        return self._entrada()

    def _entrada(self) -> dict:
        """Tela 1: benefício + contexto. O claim quantitativo só aparece se já foi validado."""
        hoje = situacao_hoje(self.ctx.perfil, self.ctx.politica)
        self.exp["hoje"] = hoje
        acordo = self.ctx.estado.get("acordo")
        st = self.state if self.state not in ("COMPLETED", "ERROR", "EVALUATING", "EXECUTING") else "IDLE"
        if acordo and acordo.get("status") == "ativo":
            autopay = bool(self.ctx.estado.get("debito_automatico"))
            return _resposta("COMPLETED", "SUMMARY", "Sua nova opção",
                             f"Suas dívidas foram reunidas em uma única parcela de {brl(acordo['parcela'])}; próximo vencimento em {acordo['proximo_vencimento']}. "
                             "Se um mês apertar, é só me chamar: dá para usar um respiro.",
                             summary=hoje, agreement=acordo, final_terms=self.exp.get("termos_finais"), autopay=autopay,
                             allowed_actions=["ASK_QUESTION", "HOME"] + (["CANCEL_AUTOPAY"] if autopay else []),
                             quick_replies=[{"id": "Q_RESPIRO", "label": "Este mês está apertado", "text": "Este mês está apertado, posso usar um respiro?"},
                                            {"id": "Q_STATUS", "label": "Como está meu acordo?", "text": "Como está meu acordo?"}],
                             numeros_permitidos=hoje["numeros_permitidos"])
        if self.ctx.perfil.renda_desconhecida:
            desc = ("Encontrei suas dívidas, mas não identifiquei entradas de renda no seu extrato. "
                    "Antes de calcular, vou te perguntar quanto entra por mês — nada é calculado sem isso.")
        else:
            desc = (f"{self._nome()}, quer ajuda para organizar seus próximos pagamentos? Hoje saem {brl(hoje['pagamento_mensal'])} por mês "
                    f"em {hoje['qtd_pagamentos']} pagamentos e {brl(hoje['juros_mensais'])} são só juros. Posso buscar uma forma de reunir tudo em uma parcela que caiba no seu mês.")
        return _resposta(st, "SUMMARY", "Encontrei uma forma de aliviar seus pagamentos mensais.", desc,
                         summary=hoje, cta="Encontrar uma opção", allowed_actions=["START", "ASK_QUESTION", "DISMISS"],
                         quick_replies=[{"id": "START", "label": "Encontrar uma opção"},
                                        {"id": "Q_COMO", "label": "Como funciona?", "text": "Como funciona a renegociação?"}],
                         numeros_permitidos=hoje["numeros_permitidos"])

    # --- EVALUATING -> NEEDS_INFORMATION | CALCULATING
    def _start(self) -> dict:
        acordo = self.ctx.estado.get("acordo")
        if acordo and acordo.get("status") == "ativo":
            return self._entrada()
        self.exp["escalado"] = None
        self._ir("EVALUATING")
        pendente = self._proxima_pergunta()
        if pendente:
            self._ir("NEEDS_INFORMATION")
            return self._pergunta_pendente()
        return self._calculating()

    def _proxima_pergunta(self) -> str | None:
        feitas = self.exp["perguntas_feitas"]
        # 5.1 contexto suficiente? renda vem do extrato; se não veio, é a ÚNICA vez que perguntamos (dados insuficientes).
        if self.ctx.perfil.renda_desconhecida and "renda" not in feitas:
            return "renda"
        # inferência crítica: gastos fixos fora do extrato mudam "quanto cabe" -> perguntar uma vez (AT02, 5.3)
        if "gasto_recorrente" not in feitas:
            return "gasto_recorrente"
        return None

    def _pergunta_pendente(self) -> dict:
        pendente = self._proxima_pergunta() or "gasto_recorrente"
        if pendente == "renda":
            return _resposta("NEEDS_INFORMATION", "QUESTION", "Quanto entra por mês, mais ou menos?",
                             "Não encontrei entradas de renda no seu extrato. Informe um valor aproximado — ele só é usado para calcular o que cabe no seu mês.",
                             question="renda",
                             quick_replies=[{"id": "YES", "label": "Informar minha renda", "input": {"campo": "valor_mensal", "tipo": "moeda", "placeholder": "Renda por mês (R$)"}}],
                             allowed_actions=["ANSWER", "ASK_QUESTION", "CANCEL"])
        return _resposta("NEEDS_INFORMATION", "QUESTION", "Antes de calcular, preciso confirmar uma coisa.",
                         "Você tem algum gasto importante todo mês que não aparece nas suas contas? Assim você mantém esse compromisso em vista ao comparar as opções.",
                         question="gasto_recorrente",
                         quick_replies=[{"id": "NO", "label": "Não", "hint": "Seguir com as informações que já tenho"},
                                        {"id": "YES", "label": "Sim", "hint": "Quero incluir um gasto", "input": {"campo": "valor_mensal", "tipo": "moeda", "placeholder": "Valor mensal do gasto (R$)"}}],
                         allowed_actions=["ANSWER", "ASK_QUESTION", "CANCEL"],
                         compromissos=self.ctx.estado.get("compromissos_extras", []))

    def _answer(self, payload: dict) -> dict:
        if self.state != "NEEDS_INFORMATION":
            return self._orientar("Não há pergunta pendente agora.", motivo="sem_pergunta")
        pendente = self._proxima_pergunta() or "gasto_recorrente"
        resposta = str(payload.get("id", "NO")).upper()
        valor = float(payload.get("valor_mensal") or 0)
        if pendente == "renda":
            if valor <= 0:
                return _resposta("NEEDS_INFORMATION", "QUESTION", "Preciso de um valor para continuar.",
                                 "Informe um valor aproximado de renda por mês (ex.: 2.300). Sem isso não dá para calcular o que cabe.",
                                 question="renda", quick_replies=[{"id": "YES", "label": "Informar minha renda", "input": {"campo": "valor_mensal", "tipo": "moeda"}}],
                                 allowed_actions=["ANSWER", "ASK_QUESTION", "CANCEL"])
            self.ctx.informar_renda(valor)
            self.exp["perguntas_feitas"].append("renda")
        else:
            if resposta == "YES" and valor > 0:
                self.ctx.adicionar_compromisso(str(payload.get("descricao") or "gasto importante"), valor)
            self.exp["perguntas_feitas"].append("gasto_recorrente")
        if self._proxima_pergunta():
            return self._pergunta_pendente()
        self._ir("EVALUATING")
        return self._calculating()

    # --- CALCULATING -> SHOWING_OPTIONS | NO_SUITABLE_OPTION
    def _calculating(self) -> dict:
        self._ir("CALCULATING")
        hoje, opcoes, r = self._calcular()
        self.exp["hoje"] = hoje
        self.exp["opcoes"] = opcoes
        self.exp["cenarios"] = {c["id"]: c for c in r.get("cenarios", [])}
        self.exp["parcela_conforto"] = r.get("parcela_conforto")
        self.exp["perfil_risco"] = r.get("perfil_risco")
        self.exp["selected_option"] = None
        validas = [o for o in opcoes if o["benefits"]]
        if r.get("nenhum_cenario_cabe") or not validas:
            self.exp["diagnostico"] = {"motivo": r.get("motivo"), **(r.get("diagnostico") or {}), "valor_extra": r.get("valor_extra", 0.0)}
            self._ir("NO_SUITABLE_OPTION")
            self.ctx.registrar_evento("nenhuma_opcao_adequada", {"motivo": r.get("motivo")})
            registrar_metrica("zera.nenhuma_opcao", 1, {})
            return self._sem_opcao(status=STATUS_CALCULO)
        self.exp["opcoes"] = validas
        self.exp["diagnostico"] = None
        self._ir("SHOWING_OPTIONS")
        self.ctx.registrar_evento("opcoes_apresentadas", {"qtd": len(validas), "recomendada": next((o["id"] for o in validas if o["recommended"]), None)})
        registrar_metrica("zera.opcoes_apresentadas", len(validas), {})
        return self._showing(status=STATUS_CALCULO)

    def _sem_opcao(self, status: dict | None = None) -> dict:
        d = self.exp.get("diagnostico") or {}
        compromissos = self.ctx.estado.get("compromissos_extras", [])
        caminhos, quick = [], []
        if d.get("entrada_necessaria"):
            caminhos.append(f"Com uma entrada de {brl(d['entrada_necessaria'])} (13º, FGTS, restituição), a parcela caberia em {d.get('prazo_da_parcela_minima', 60)}x.")
            quick.append({"id": "ADJUST_EXTRA", "label": "Tenho um dinheiro extra", "acao": "ADJUST", "payload": {"tipo": "dinheiro_extra"},
                          "input": {"campo": "valor", "tipo": "moeda", "placeholder": "Quanto entrou (R$)"}})
        if compromissos:
            total = r2(sum(c["valor_mensal"] for c in compromissos))
            caminhos.append(f"Você informou {brl(total)} por mês de gastos fora do extrato; se algum deles mudar, recalculo na hora.")
            quick.append({"id": "ADJUST_GASTO", "label": "Revisar o gasto informado", "acao": "ADJUST", "payload": {"tipo": "remover_gasto"}})
        elif d.get("reducao_gastos_necessaria"):
            caminhos.append(f"Se sobrassem {brl(d['reducao_gastos_necessaria'])} a mais por mês, a menor parcela caberia.")
        caminhos.append("Uma pessoa do time pode olhar seu caso com calma e ver condições que eu não tenho aqui.")
        quick.append({"id": "ESCALATE", "label": "Falar com uma pessoa", "acao": "ESCALATE"})
        quick.append({"id": "RETRY", "label": "Calcular de novo", "acao": "RETRY"})
        desc = ("Não vou te empurrar uma opção que não cabe. " + (d.get("motivo") or "")).strip()
        return _resposta("NO_SUITABLE_OPTION", "TEXT", "Não encontrei uma opção que caiba no seu bolso agora.", desc,
                         status=status, diagnosis=d, paths=caminhos, quick_replies=quick,
                         allowed_actions=["ADJUST", "ESCALATE", "RETRY", "ASK_QUESTION", "HOME"],
                         numeros_permitidos=(self.exp.get("hoje") or {}).get("numeros_permitidos", []))

    def _showing(self, comparacao: bool = False, status: dict | None = None) -> dict:
        opcoes = self.exp.get("opcoes") or []
        hoje = self.exp.get("hoje") or situacao_hoje(self.ctx.perfil, self.ctx.politica)
        rec = next((o for o in opcoes if o["recommended"]), opcoes[0] if opcoes else None)
        if rec is None:
            return self._sem_opcao() if self.state == "NO_SUITABLE_OPTION" else self._start()
        numeros = sorted({n for o in opcoes for n in o["numeros_permitidos"]} | set(hoje["numeros_permitidos"]))
        if comparacao:
            destaque = [o for o in opcoes if o["highlight"]] or opcoes
            return _resposta("SHOWING_OPTIONS", "OPTIONS_COMPARISON", f"Encontrei {len(destaque)} formas de diminuir suas parcelas.",
                             "Todas cabem no valor que você pode pagar por mês. Compare o que muda em cada uma.",
                             options=opcoes, current=hoje, allowed_actions=["SELECT_OPTION", "ASK_WHY", "ASK_QUESTION", "ADJUST", "CANCEL"],
                             quick_replies=[{"id": "ADJUST_GASTO", "label": "Precisa de um valor diferente? Posso ajustar as opções.", "acao": "ADJUST",
                                             "payload": {"tipo": "gasto"}, "input": {"campo": "valor", "tipo": "moeda", "placeholder": "Gasto mensal a considerar (R$)"}}],
                             numeros_permitidos=numeros)
        principal = beneficio_principal(rec["benefits"])
        titulo = (f"Você pode liberar {brl(principal['monthly_difference'])} por mês" if principal and principal["benefit_type"] == "LOWER_MONTHLY_PAYMENT"
                  else "Encontrei uma opção para reunir suas dívidas")
        return _resposta("SHOWING_OPTIONS", "OPTION_DETAIL", titulo,
                         "Encontrei uma opção para reunir suas dívidas em uma parcela que cabe no seu mês, com data para terminar.",
                         option=rec, current=hoje, benefit=principal, claims=rec["claims"], tradeoffs=rec["tradeoffs"],
                         status=status, allowed_actions=["SELECT_OPTION", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION", "CANCEL"],
                         cta="Continuar com esta opção", numeros_permitidos=numeros)

    def _view_options(self) -> dict:
        if self.exp.get("opcoes") and self.state in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING", "AWAITING_CONFIRMATION", "CALCULATING"):
            self.exp["selected_option"] = None
            self._ir("SHOWING_OPTIONS")
            return self._showing(comparacao=True)
        if self.state == "NO_SUITABLE_OPTION":
            return self._retry()
        return self._start()

    # --- EXPLAINING (critério determinístico + LLM opcional)
    async def _ask_why(self, payload: dict) -> dict:
        opcoes = self.exp.get("opcoes") or []
        if not opcoes or self.state not in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING", "AWAITING_CONFIRMATION"):
            if self.state == "NO_SUITABLE_OPTION":
                return self._sem_opcao()
            return self._orientar("Ainda não calculei nada para explicar. Vamos começar?", motivo="sem_opcoes")
        alvo = next((o for o in opcoes if o["id"] == str(payload.get("option_id", "")).lower()), None) \
            or next((o for o in opcoes if o["id"] == self.exp.get("selected_option")), None) \
            or next((o for o in opcoes if o["recommended"]), opcoes[0])
        criterios = criterio_recomendacao(alvo | {"parcela_mensal": alvo["monthly_payment"], "reserva": alvo["reserve"], "entrada": alvo["down_payment"]},
                                          self.exp.get("parcela_conforto") or self.ctx.capacidade.parcela_maxima,
                                          self.exp.get("perfil_risco", "renda_estavel"))
        texto = ""
        hoje = self.exp["hoje"]
        if self.explicador:
            pergunta = ("Explique em até 4 frases curtas, em linguagem cotidiana e sem pressão, por que esta opção foi destacada, "
                        "usando apenas estes fatos e números: " + " ".join(criterios) +
                        f" Parcela {brl(alvo['monthly_payment'])} por mês, prazo {alvo['term_months']} meses, total {brl(alvo['total_cost'])} "
                        f"(saldo devedor {brl(alvo['principal'])} + {brl(alvo['interest_total'])} de juros a {alvo['rate_monthly_pct']:.1f}% ao mês); "
                        f"hoje {brl(hoje['pagamento_mensal'])} por mês em {hoje['qtd_pagamentos']} pagamentos, {brl(hoje['juros_mensais'])} só de juros. "
                        "Trade-offs: " + " ".join(alvo["tradeoffs"]))
            try:
                texto = await self.explicador(pergunta, alvo["numeros_permitidos"] + hoje["numeros_permitidos"])
            except Exception as e:  # noqa: BLE001 — sem LLM, a explicação determinística basta
                log.warning("explicador indisponível: %s", e)
                registrar_metrica("zera.llm_indisponivel", 1, {"onde": "ask_why"})
        if self.state != "AWAITING_CONFIRMATION":
            self._ir("EXPLAINING")
        return _resposta(self.state, "TEXT", f"Por que “{alvo['label']}”?", texto or " ".join(criterios),
                         criteria=criterios, tradeoffs=alvo["tradeoffs"], option=alvo, llm=bool(texto),
                         allowed_actions=self._acoes_do_estado(), quick_replies=self._sugestoes_do_estado())

    # --- ASK_QUESTION: roteamento determinístico de intenção -> ação; senão LLM com fatos; senão orientação
    async def _ask_question(self, payload: dict) -> dict:
        texto = str(payload.get("text", "")).strip()
        if not texto:
            return self._orientar("Pode digitar sua pergunta ou escolher uma das opções abaixo.", motivo="pergunta_vazia")
        intencao, extra = self._intencao(texto)
        registrar_metrica("zera.intencao", 1, {"intencao": intencao, "estado": self.state})
        self.ctx.registrar_evento("pergunta_livre", {"intencao": intencao, "estado": self.state, "tamanho": len(texto)})
        if intencao == "ESCALATE":
            return self._escalate({"motivo": "pedido do cliente", "texto": texto})
        if intencao == "CANCEL":
            return self._cancel(texto_cliente=True)
        if intencao == "LGPD":
            return _resposta(self.state, "TEXT", "Você pode apagar o que a zera.ai guarda sobre você.",
                             "Isso remove memória, consentimentos e o acordo simulado desta demonstração. O extrato continua seguindo as regras de retenção do banco. Quer apagar?",
                             quick_replies=[{"id": "RESET", "label": "Apagar meus dados", "acao": "RESET"}, {"id": "GET", "label": "Manter", "acao": "GET"}],
                             allowed_actions=["RESET", "GET", "ASK_QUESTION"])
        if intencao == "CONDICAO_INEXISTENTE":
            return self._condicao_inexistente(texto)
        if intencao == "ANSWER_VALOR":
            return self._answer({"id": "YES", "valor_mensal": extra, "descricao": "gasto informado no chat"})
        if intencao == "ANSWER_NAO":
            return self._answer({"id": "NO"})
        if intencao == "SIM_CONFIRMAR":
            t = self._confirmacao()
            t["content"]["description"] = ("Entendi que você quer seguir. Por segurança, a contratação só acontece pelo botão "
                                           "“Confirmar contratação” abaixo — digitar “sim” não contrata nada. " + t["content"]["description"])
            return t
        if intencao == "CONTINUE":
            return self._continue()
        if intencao == "VIEW_OPTIONS":
            return self._view_options()
        if intencao == "ASK_WHY":
            return await self._ask_why({})
        if intencao == "SELECT_OPTION":
            r = self._select({"option_id": extra})
            if r["response_type"] != "ERROR":
                return r
        if intencao == "PRAZO":
            return self._pedido_de_prazo(int(extra))
        if intencao == "SAUDACAO":
            return self._orientar(f"Oi, {self._nome()}! Estou aqui para ajudar com as suas dívidas, sem pressa e sem pressão.", motivo="saudacao")
        # pergunta livre de verdade -> LLM com fatos do estado atual (atrás dos guardrails)
        resposta = ""
        if self.explicador:
            try:
                resposta = await self.explicador(self._prompt_pergunta(texto), self._numeros_permitidos())
            except Exception as e:  # noqa: BLE001
                log.warning("LLM indisponível: %s", e)
                registrar_metrica("zera.llm_indisponivel", 1, {"onde": "ask_question"})
        if resposta:
            return _resposta(self.state, "TEXT", "", resposta, llm=True, allowed_actions=self._acoes_do_estado(),
                             quick_replies=self._sugestoes_do_estado())
        return self._orientar("Não consegui responder isso agora, mas posso seguir por aqui:", motivo="llm_indisponivel")

    def _intencao(self, texto: str) -> tuple[str, object]:
        t = _normalizar(texto)
        st = self.state
        if RE_LGPD.search(t):
            return "LGPD", None
        if RE_ESCALAR.search(t):
            return "ESCALATE", None
        if RE_CANCELAR.search(t):
            return "CANCEL", None
        if st == "NEEDS_INFORMATION":
            valor = _numero_em(t)
            if valor is not None and valor > 0:
                return "ANSWER_VALOR", valor
            if RE_NAO.search(t):
                return "ANSWER_NAO", None
        if RE_CONDICAO_INEXISTENTE.search(t):
            return "CONDICAO_INEXISTENTE", None
        if st == "AWAITING_CONFIRMATION" and RE_SIM.search(t):
            return "SIM_CONFIRMAR", None
        if st == "REVIEWING" and RE_SIM.search(t):
            return "CONTINUE", None
        m = RE_PRAZO.search(t)
        if m and st in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING", "AWAITING_CONFIRMATION"):
            return "PRAZO", int(m.group(1))
        if RE_PORQUE.search(t) and st in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING", "AWAITING_CONFIRMATION"):
            return "ASK_WHY", None
        if st in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING"):
            for oid, padrao in RE_ROTULO.items():
                if padrao.search(t) and any(o["id"] == oid for o in self.exp.get("opcoes") or []):
                    return "SELECT_OPTION", oid
        if RE_OPCOES.search(t):
            return "VIEW_OPTIONS", None
        if st in ("IDLE", "COMPLETED") and RE_SIM.search(t) and not self.ctx.estado.get("acordo"):
            return "VIEW_OPTIONS", None
        if RE_SAUDACAO.search(t) and len(t) < 40:
            return "SAUDACAO", None
        return "LLM", None

    def _pedido_de_prazo(self, prazo: int) -> dict:
        opcoes = self.exp.get("opcoes") or []
        alvo = next((o for o in opcoes if o["term_months"] == prazo), None)
        if alvo:
            return self._select({"option_id": alvo["id"]})
        prazos = sorted({o["term_months"] for o in opcoes})
        if prazo in (self.ctx.politica.get("prazos_oferecidos") or []):
            desc = (f"Em {prazo}x a parcela passaria do que cabe no seu mês (parcela máxima de {brl(self.ctx.capacidade.parcela_maxima)}). "
                    f"Os prazos que cabem hoje são: {', '.join(f'{p}x' for p in prazos)}.")
        else:
            desc = (f"{prazo}x não é um prazo disponível. Os prazos elegíveis vão de {min(self.ctx.politica['prazos_oferecidos'])}x a "
                    f"{max(self.ctx.politica['prazos_oferecidos'])}x, e os que cabem no seu mês são: {', '.join(f'{p}x' for p in prazos)}.")
        return _resposta(self.state, "TEXT", "Sobre o prazo", desc, allowed_actions=self._acoes_do_estado(), quick_replies=self._sugestoes_do_estado())

    def _condicao_inexistente(self, texto: str) -> dict:
        pol = self.ctx.politica
        desc = (f"Eu não tenho desconto no saldo devedor nem juros zero — não posso inventar condição. O que existe aqui é: "
                f"taxa de {pol['taxa_mensal_renegociacao']*100:.1f}% ao mês (bem abaixo do rotativo), prazos de "
                f"{min(pol['prazos_oferecidos'])}x a {max(pol['prazos_oferecidos'])}x e, se entrar dinheiro extra, usá-lo como entrada para diminuir a parcela. "
                "As dívidas em atraso saem do atraso quando o acordo é contratado. Uma pessoa do time pode avaliar condições que eu não tenho.")
        return _resposta(self.state, "TEXT", "Sobre descontos e condições", desc, allowed_actions=self._acoes_do_estado() + ["ESCALATE"],
                         quick_replies=self._sugestoes_do_estado() + [{"id": "ESCALATE", "label": "Falar com uma pessoa", "acao": "ESCALATE"}])

    def _prompt_pergunta(self, texto: str) -> str:
        hoje = self.exp.get("hoje") or situacao_hoje(self.ctx.perfil, self.ctx.politica)
        fatos = [f"Estado da jornada: {self.state}.",
                 f"Hoje: {brl(hoje['pagamento_mensal'])} por mês em {hoje['qtd_pagamentos']} pagamentos; saldo devedor {brl(hoje['saldo_devedor'])}; "
                 f"{brl(hoje['juros_mensais'])} por mês só de juros; taxa de até {hoje['taxa_maxima_pct']:.1f}% ao mês"
                 + ("; rotativo/cheque sem data para acabar." if hoje.get("prazo_indefinido") else ".")]
        for o in (self.exp.get("opcoes") or [])[:6]:
            fatos.append(f"Opção {o['label']}{' (recomendada)' if o['recommended'] else ''}: {brl(o['monthly_payment'])} por mês, {o['term_months']} meses, "
                         f"total {brl(o['total_cost'])} = saldo {brl(o['principal'])} + juros {brl(o['interest_total'])} a {o['rate_monthly_pct']:.1f}% ao mês"
                         + (f", entrada {brl(o['down_payment'])}" if o['down_payment'] else "") + ".")
        sel = self._opcao_selecionada()
        if sel:
            fatos.append(f"Opção selecionada: {sel['label']}.")
        fatos.append(f"Parcela máxima que cabe: {brl(self.ctx.capacidade.parcela_maxima)}; parcela de conforto: {brl(self.exp.get('parcela_conforto') or self.ctx.capacidade.parcela_maxima)}.")
        return ("Responda à pergunta da cliente em até 4 frases curtas, linguagem simples, sem pressão e sem promessas, usando SOMENTE os fatos "
                "abaixo (não invente taxas, descontos, prazos ou datas; se não souber, diga que uma pessoa do time pode ajudar). "
                "Se ela pedir para contratar, explique que só o botão Confirmar contrata.\nFATOS: " + " ".join(fatos) + f"\nPERGUNTA: {texto}")

    def _numeros_permitidos(self) -> list[float]:
        return sorted({n for o in self.exp.get("opcoes", []) for n in o["numeros_permitidos"]}
                      | set((self.exp.get("hoje") or {}).get("numeros_permitidos", []))
                      | {self.ctx.capacidade.parcela_maxima, float(self.exp.get("parcela_conforto") or 0)})

    def _acoes_do_estado(self) -> list[str]:
        return {"IDLE": ["START", "ASK_QUESTION", "DISMISS"],
                "EVALUATING": ["START", "ASK_QUESTION"],
                "NEEDS_INFORMATION": ["ANSWER", "ASK_QUESTION", "CANCEL"],
                "CALCULATING": ["RETRY", "ASK_QUESTION"],
                "SHOWING_OPTIONS": ["SELECT_OPTION", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION", "ADJUST", "CANCEL"],
                "EXPLAINING": ["SELECT_OPTION", "VIEW_OPTIONS", "ASK_QUESTION", "CANCEL"],
                "REVIEWING": ["CONTINUE", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION", "CANCEL"],
                "AWAITING_CONFIRMATION": ["CONFIRM", "CANCEL", "ASK_QUESTION"],
                "EXECUTING": ["GET"],
                "COMPLETED": ["ASK_QUESTION", "HOME"],
                "NO_SUITABLE_OPTION": ["ADJUST", "ESCALATE", "RETRY", "ASK_QUESTION", "HOME"],
                "ERROR": ["RETRY", "ESCALATE", "ASK_QUESTION", "HOME"]}.get(self.state, ["START", "ASK_QUESTION"])

    def _sugestoes_do_estado(self) -> list[dict]:
        st = self.state
        sel = self._opcao_selecionada()
        if st in ("SHOWING_OPTIONS", "EXPLAINING"):
            rec = next((o for o in self.exp.get("opcoes") or [] if o["recommended"]), None)
            s = [{"id": "VIEW_OPTIONS", "label": "Ver outras opções", "acao": "VIEW_OPTIONS"}]
            if rec:
                s.append({"id": "SELECT", "label": f"Seguir com “{rec['label']}”", "acao": "SELECT_OPTION", "payload": {"option_id": rec["id"]}})
            s.append({"id": "ASK_WHY", "label": "Por que essa opção?", "acao": "ASK_WHY"})
            return s
        if st == "REVIEWING":
            return [{"id": "CONTINUE", "label": "Continuar", "acao": "CONTINUE"}, {"id": "VIEW_OPTIONS", "label": "Ver outras opções", "acao": "VIEW_OPTIONS"}]
        if st == "AWAITING_CONFIRMATION":
            return [{"id": "GET", "label": "Voltar à confirmação", "acao": "GET"}, {"id": "CANCEL", "label": "Revisar os termos", "acao": "CANCEL"}]
        if st == "NEEDS_INFORMATION":
            return [{"id": "GET", "label": "Voltar à pergunta", "acao": "GET"}]
        if st == "NO_SUITABLE_OPTION":
            return [{"id": "ESCALATE", "label": "Falar com uma pessoa", "acao": "ESCALATE"}, {"id": "RETRY", "label": "Calcular de novo", "acao": "RETRY"}]
        if st == "COMPLETED" and self.ctx.estado.get("acordo"):
            return [{"id": "Q_STATUS", "label": "Como está meu acordo?", "text": "Como está meu acordo?"}]
        if sel:
            return [{"id": "GET", "label": "Continuar de onde parei", "acao": "GET"}]
        return [{"id": "START", "label": "Ver o que cabe no meu bolso", "acao": "START"},
                {"id": "ESCALATE", "label": "Falar com uma pessoa", "acao": "ESCALATE"}]

    def _orientar(self, texto: str, motivo: str = "") -> dict:
        """Nunca um beco sem saída: texto curto + ações reais do estado atual."""
        return _resposta(self.state, "TEXT", "", texto, reason=motivo, allowed_actions=self._acoes_do_estado(),
                         quick_replies=self._sugestoes_do_estado())

    # --- REVIEWING: termos -> débito automático -> AWAITING_CONFIRMATION
    def _select(self, payload: dict) -> dict:
        if self.state not in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING") or not self.exp.get("opcoes"):
            if self.state == "NO_SUITABLE_OPTION":
                return self._sem_opcao()
            if self.state == "AWAITING_CONFIRMATION":
                return self._confirmacao()
            return self._orientar("Primeiro vou calcular as opções que cabem no seu mês.", motivo="selecao_fora_de_hora")
        oid = str(payload.get("option_id", "")).lower()
        opcao = next((o for o in (self.exp.get("opcoes") or []) if o["id"] == oid or o["cenario_id"].lower() == oid), None)
        if not opcao:
            return self._orientar(f"Não encontrei a opção “{oid}”. Escolha uma das opções calculadas.", motivo="opcao_inexistente")
        self.exp["selected_option"] = opcao["id"]
        self.exp["autopay"] = None
        self._ir("REVIEWING")
        self.ctx.registrar_evento("opcao_selecionada", {"opcao": opcao["id"]})
        registrar_metrica("zera.opcao_selecionada", 1, {"opcao": opcao["id"]})
        return self._termos(autopay=None)

    def _opcao_selecionada(self) -> dict | None:
        return next((o for o in (self.exp.get("opcoes") or []) if o["id"] == self.exp.get("selected_option")), None)

    def _termos(self, autopay: bool | None) -> dict:
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._view_options()
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        t = termos(cen, self.ctx.perfil, self.ctx.hoje, bool(autopay), self.ctx.politica)
        hoje = self.exp["hoje"]
        return _resposta("REVIEWING", "TERMS_REVIEW", "Revise os termos da sua nova opção",
                         "Verifique as informações antes de continuar. Esta opção reúne suas dívidas em um único pagamento, com data para terminar.",
                         option=opcao, terms=t, current=hoje, tradeoffs=opcao["tradeoffs"], autopay=autopay,
                         allowed_actions=["CONTINUE", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION", "CANCEL"], cta="Continuar",
                         notice="Você sempre decide. Esta contratação só será concluída com a sua confirmação.",
                         numeros_permitidos=t["numeros_permitidos"])

    def _continue(self) -> dict:
        if self.state != "REVIEWING":
            if self.state == "AWAITING_CONFIRMATION":
                return self._confirmacao()
            if self.state in ("SHOWING_OPTIONS", "EXPLAINING"):
                rec = next((o for o in self.exp.get("opcoes") or [] if o["recommended"]), None)
                return self._select({"option_id": rec["id"]}) if rec else self._view_options()
            return self._orientar("Nada para continuar agora.", motivo="continue_fora_de_hora")
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._view_options()
        if self.exp.get("autopay") is None:  # §16: oferecer débito automático se houver condição real
            da = opcao["autopay"]
            if da["desconto_mensal"] > 0:
                return _resposta("REVIEWING", "QUESTION", "Economize mais com débito automático",
                                 "Ative o débito automático e reduza sua parcela. Você continua no controle e pode cancelar quando quiser.",
                                 question="autopay",
                                 benefit={"benefit_type": "AUTOPAY_DISCOUNT", "regular_payment": opcao["monthly_payment"],
                                          "autopay_payment": da["parcela_com_desconto"], "monthly_discount": da["desconto_mensal"]},
                                 quick_replies=[{"id": "AUTOPAY_YES", "label": f"Quero pagar {brl(da['parcela_com_desconto'])}/mês com débito automático",
                                                 "hint": f"{brl(da['desconto_mensal'])} de desconto por mês"},
                                                {"id": "AUTOPAY_NO", "label": f"Prefiro pagar {brl(opcao['monthly_payment'])}/mês por conta própria",
                                                 "hint": "Você recebe o boleto todo mês e escolhe como quer pagar."}],
                                 allowed_actions=["SET_AUTOPAY", "CANCEL", "ASK_QUESTION"], option=opcao)
            self.exp["autopay"] = False
        return self._confirmacao()

    def _set_autopay(self, payload: dict) -> dict:
        if self.state != "REVIEWING":
            return self._orientar("O débito automático é escolhido na revisão dos termos.", motivo="autopay_fora_de_hora")
        self.exp["autopay"] = bool(payload.get("autopay", str(payload.get("id", "")).upper() == "AUTOPAY_YES"))
        self._salvar()
        return self._confirmacao()

    def _confirmacao(self) -> dict:
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._view_options()
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        autopay = bool(self.exp.get("autopay"))
        t = termos(cen, self.ctx.perfil, self.ctx.hoje, autopay, self.ctx.politica)  # recalcula tudo antes de confirmar (§16)
        hoje = self.exp["hoje"]
        beneficios = validar_beneficios(hoje, {"parcela_mensal": t["parcela_mensal"], "total_a_pagar": t["total_a_pagar"],
                                               "prazo_meses": t["prazo_meses"], "qtd_pagamentos": 1 + len(t["mantidas"]),
                                               "resolve_negativacao": opcao["resolve_negativacao"], "taxa_mensal": cen["taxa_mensal"]})
        self._ir("AWAITING_CONFIRMATION")
        return _resposta("AWAITING_CONFIRMATION", "CONFIRMATION_REQUEST", "Confirme sua contratação",
                         "Revise as informações finais para concluir." + (" Com o débito automático, você garante "
                         f"{brl(t['desconto_debito_automatico'])} de desconto por mês." if autopay else ""),
                         requires_confirmation=True, selected_option=opcao, final_terms=t, benefits=beneficios, claims=claims(beneficios),
                         account={"banco": "Itaú", "agencia": "1234", "conta": "56789-0"} if autopay else None,
                         allowed_actions=["CONFIRM", "CANCEL", "ASK_QUESTION"], cta="Confirmar contratação",
                         notice="Ao confirmar, você aceita os termos e condições da contratação" + (" e autoriza o débito automático na conta selecionada." if autopay else "."),
                         numeros_permitidos=t["numeros_permitidos"])

    # --- EXECUTING -> COMPLETED (sistema transacional = motor.criar_acordo_de_cenario)
    def _confirm(self, payload: dict) -> dict:
        if self.state != "AWAITING_CONFIRMATION":
            if self.state == "COMPLETED" and self.ctx.estado.get("acordo"):
                return self._entrada()
            r = self._orientar("A contratação só acontece depois de revisar os termos e chegar à tela de confirmação.", motivo="confirm_fora_de_hora")
            r["response_type"] = "ERROR"
            r["content"]["title"] = "Confirmação fora de hora"
            r["error"] = "confirm_fora_de_hora"
            return r
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._view_options()
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        autopay = bool(self.exp.get("autopay"))
        self._ir("EXECUTING")
        with medir("motor.criar_acordo", {"cliente": self.ctx.cliente_id}):
            t = termos(cen, self.ctx.perfil, self.ctx.hoje, autopay, self.ctx.politica)
            consentimento = {"acao": "fechar_acordo", "frase_cliente": str(payload.get("frase", "Confirmar contratação")),
                             "versao_termo": "demo-v1", "timestamp": datetime.now().isoformat(timespec="seconds"),
                             "data_simulada": self.ctx.estado["hoje"], "debito_automatico": autopay, "opcao": opcao["id"],
                             "jornada_id": self.exp.get("jornada_id")}
            self.ctx.estado.setdefault("consentimentos", []).append(consentimento)
            acordo = criar_acordo_de_cenario(self.ctx.perfil, cen, self.ctx.hoje, self.ctx.politica)
            if autopay and t["desconto_debito_automatico"] > 0:
                pct = self.ctx.politica["desconto_debito_automatico_pct"]
                for comp in acordo.componentes:
                    comp["parcela"] = r2(comp["parcela"] * (1 - pct))
                acordo.parcela = t["parcela_acordo"]
                acordo.historico.append({"data": self.ctx.estado["hoje"], "evento": "debito_automatico_ativado", "desconto_mensal": t["desconto_debito_automatico"]})
            self.ctx.estado["gatilhos_pendentes"] = []
            self.ctx.estado["debito_automatico"] = autopay
            self.exp["proativa_ativa"] = None
            self.ctx.salvar(acordo)
        hoje = self.exp["hoje"]
        reducao = r2(hoje["pagamento_mensal"] - t["parcela_mensal"])
        self.exp["termos_finais"] = {**t, "reducao_mensal": reducao, "pagamento_antes": hoje["pagamento_mensal"]}
        self._ir("COMPLETED")
        self.ctx.registrar_evento("acordo_fechado", {"origem": "experiencia", "opcao": opcao["id"], "parcela": acordo.parcela,
                                                     "prazo": acordo.prazo, "debito_automatico": autopay, "jornada_id": self.exp.get("jornada_id")})
        registrar_metrica("zera.acordo_fechado", 1, {"opcao": opcao["id"], "autopay": str(autopay)})
        registrar_metrica("zera.valor_recuperado", t["total_a_pagar"], {})
        titulo = f"Pronto! Você reduziu suas parcelas em {brl(reducao)} por mês" if reducao > 0 else "Pronto! Suas dívidas foram reunidas"
        return _resposta("COMPLETED", "SUCCESS", titulo,
                         f"Suas dívidas foram reunidas em uma parcela de {brl(t['parcela_mensal'])}" + (", com débito automático." if autopay else "."),
                         status=STATUS_EXECUCAO, agreement=acordo.to_dict(), final_terms=t,
                         result={"new_monthly_payment": t["parcela_mensal"], "first_due_date": t["primeiro_vencimento"],
                                 "last_due_date": t["ultimo_vencimento"], "monthly_reduction": reducao if reducao > 0 else 0.0},
                         next_steps=["Suas dívidas foram reunidas — você paga todas em uma única parcela.",
                                     "O débito automático já está ativo — as próximas parcelas serão pagas automaticamente." if autopay else "Você recebe o boleto todo mês e escolhe como pagar.",
                                     "Se um mês apertar, você pode usar um respiro: a parcela vai para o fim, sem juros.",
                                     "Você continua no controle — pode acompanhar e cancelar quando quiser."],
                         allowed_actions=["FOLLOW", "HOME", "ASK_QUESTION"], cta="Acompanhar minha nova opção", numeros_permitidos=t["numeros_permitidos"])

    def _cancel(self, texto_cliente: bool = False) -> dict:
        st = self.state
        if st == "AWAITING_CONFIRMATION" and not texto_cliente:
            self._ir("REVIEWING")
            return self._termos(self.exp.get("autopay"))
        if st in ("REVIEWING", "EXPLAINING") and self.exp.get("opcoes") and not texto_cliente:
            self.exp["selected_option"] = None
            self._ir("SHOWING_OPTIONS")
            return self._showing(comparacao=True)
        self.exp["selected_option"] = None
        self._ir("IDLE")
        self.ctx.registrar_evento("jornada_pausada", {"de": st})
        r = self._entrada()
        if texto_cliente:
            r["content"]["title"] = "Tudo bem, sem pressa."
            r["content"]["description"] = "Quando quiser retomar, é só me chamar — suas informações continuam aqui e nada foi contratado."
        return r

    # --- ESCALATE / ADJUST / RETRY
    def _escalate(self, payload: dict) -> dict:
        protocolo = f"ZR-{uuid4().hex[:6].upper()}"
        registro = {"protocolo": protocolo, "motivo": str(payload.get("motivo") or self.state), "data": self.ctx.estado["hoje"],
                    "estado": self.state, "previsao_contato": "até 1 dia útil"}
        self.ctx.estado.setdefault("escalonamentos", []).append(registro)
        self.exp["escalado"] = registro
        self._salvar()
        self.ctx.registrar_evento("escalado_humano", registro)
        registrar_metrica("zera.escalado", 1, {"estado": self.state})
        return self._tela_escalado()

    def _tela_escalado(self) -> dict:
        e = self.exp.get("escalado") or {}
        return _resposta(self.state, "TEXT", "Uma pessoa do time vai falar com você.",
                         f"Registrei seu pedido (protocolo {e.get('protocolo', '—')}). O contato acontece em {e.get('previsao_contato', 'até 1 dia útil')} "
                         "e nenhuma ação é executada até lá. Se preferir, continuo por aqui.",
                         escalation=e, allowed_actions=["HOME", "ASK_QUESTION", "RETRY"],
                         quick_replies=[{"id": "HOME", "label": "Voltar para o início", "acao": "HOME"},
                                        {"id": "RETRY", "label": "Ver as opções de novo", "acao": "RETRY"}])

    def _adjust(self, payload: dict) -> dict:
        tipo = str(payload.get("tipo", "gasto"))
        valor = float(payload.get("valor") or payload.get("valor_mensal") or 0)
        if tipo == "dinheiro_extra":
            if valor <= 0:
                return self._orientar("Informe quanto entrou para eu recalcular com entrada.", motivo="valor_invalido")
            self.exp["valor_extra"] = valor
            self.ctx.registrar_evento("dinheiro_extra_informado", {"valor": valor})
        elif tipo == "remover_gasto":
            self.ctx.remover_compromissos()
            self.exp["perguntas_feitas"] = [p for p in self.exp["perguntas_feitas"] if p != "gasto_recorrente"]
            self._ir("EVALUATING")
            return self._start()
        else:  # gasto mensal a considerar (substitui o informado antes)
            if valor <= 0:
                return self._orientar("Informe o valor mensal do gasto para eu recalcular.", motivo="valor_invalido")
            self.ctx.remover_compromissos()
            self.ctx.adicionar_compromisso(str(payload.get("descricao") or "gasto informado"), valor)
            if "gasto_recorrente" not in self.exp["perguntas_feitas"]:
                self.exp["perguntas_feitas"].append("gasto_recorrente")
        if self.ctx.perfil.renda_desconhecida:
            self._ir("NEEDS_INFORMATION")
            return self._pergunta_pendente()
        self._ir("EVALUATING")
        return self._calculating()

    def _retry(self) -> dict:
        self.exp["escalado"] = None
        if self.state in ("NO_SUITABLE_OPTION", "ERROR", "CALCULATING", "EVALUATING") or not self.exp.get("opcoes"):
            if self._proxima_pergunta():
                self._ir("NEEDS_INFORMATION")
                return self._pergunta_pendente()
            self._ir("EVALUATING")
            return self._calculating()
        return self.resposta_atual()

    def _erro(self, detalhe: str) -> dict:
        anterior = self.state
        self.exp["state"] = "ERROR"
        self._salvar()
        self.ctx.registrar_evento("erro_experiencia", {"detalhe": detalhe[:200], "estado_anterior": anterior})
        registrar_metrica("zera.erro", 1, {"estado": anterior})
        self.exp["state"] = anterior if anterior not in ("EXECUTING", "CALCULATING") else "IDLE"
        self._salvar()
        return _resposta("ERROR", "ERROR", "Não consegui concluir esta etapa agora.",
                         "Não vou inventar nenhum valor. Você pode tentar de novo em instantes ou falar com uma pessoa do time.",
                         error=detalhe, allowed_actions=["RETRY", "ESCALATE", "ASK_QUESTION", "HOME"],
                         quick_replies=[{"id": "RETRY", "label": "Tentar de novo", "acao": "RETRY"},
                                        {"id": "ESCALATE", "label": "Falar com uma pessoa", "acao": "ESCALATE"}])
