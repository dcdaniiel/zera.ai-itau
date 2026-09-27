"""Orquestrador determinístico da experiência zera.ai (spec "Agent Behavior & Content Specification v1").

Máquina de estados + decision engine (ASK / TOOL / CONFIRM / RESPOND) + contrato de resposta estruturado.
O LLM NÃO decide o fluxo: entra só para explicar (EXPLAINING) e para perguntas livres (ASK_QUESTION),
sempre atrás dos guardrails. Todo número vem do núcleo determinístico (`motor/`).

    IDLE -> EVALUATING -> NEEDS_INFORMATION -> EVALUATING -> CALCULATING -> SHOWING_OPTIONS
         -> EXPLAINING / REVIEWING -> AWAITING_CONFIRMATION -> EXECUTING -> COMPLETED | ERROR | NO_SUITABLE_OPTION
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Awaitable, Callable

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

log = logging.getLogger("zera.experiencia")

ESTADOS = ["IDLE", "EVALUATING", "NEEDS_INFORMATION", "CALCULATING", "SHOWING_OPTIONS", "EXPLAINING", "REVIEWING",
           "AWAITING_CONFIRMATION", "EXECUTING", "COMPLETED", "NO_SUITABLE_OPTION", "ERROR"]
ACOES_SENSIVEIS = {"CONFIRM"}
PREFERENCIAS_PADRAO = {"analisar": True, "momentos": True, "recomendar": True, "avisar": True, "open_finance": False}
DISCLAIMER = "Resposta gerada por IA e pode ter informações imprecisas."
STATUS_CALCULO = {"title": "Buscando uma parcela que cabe no seu bolso...",
                  "steps": ["Considerando seus gastos do mês", "Comparando suas dívidas", "Calculando opções"]}
STATUS_EXECUCAO = {"title": "Finalizando sua contratação...",
                   "steps": ["Validando suas informações", "Formalizando a contratação", "Configurando o débito automático",
                             "Reunindo suas dívidas", "Confirmando a conclusão"]}

Explicador = Callable[[str, list[float]], Awaitable[str]]  # (pergunta, numeros_permitidos) -> texto do LLM


def _resposta(state: str, response_type: str, title: str, description: str = "", **extra) -> dict:
    base = {"state": state, "response_type": response_type, "content": {"title": title, "description": description},
            "options": [], "quick_replies": [], "allowed_actions": [], "requires_confirmation": False,
            "disclaimer": DISCLAIMER}
    base.update(extra)
    return base


class Experiencia:
    """Uma instância por cliente. Estado persistido em `estado['experiencia']` (JSON local ou BigQuery)."""

    def __init__(self, ctx: Contexto, explicador: Explicador | None = None):
        self.ctx = ctx
        self.explicador = explicador
        self.exp = ctx.estado.setdefault("experiencia", {"state": "IDLE", "perguntas_feitas": [], "selected_option": None,
                                                          "autopay": None, "valor_extra": 0.0, "opcoes": [], "cenarios": {},
                                                          "hoje": None, "contatos_proativos": []})
        ctx.estado.setdefault("preferencias", dict(PREFERENCIAS_PADRAO))

    # ------------------------------------------------------------------ util
    @property
    def state(self) -> str:
        return self.exp["state"]

    def _ir(self, novo: str) -> None:
        log.info("experiencia %s: %s -> %s", self.ctx.cliente_id, self.exp["state"], novo)
        self.exp["state"] = novo
        self.ctx.salvar()

    def _salvar(self) -> None:
        self.ctx.salvar()

    def _valor_extra(self) -> float:
        g = next((g for g in self.ctx.estado.get("gatilhos_pendentes", []) if g.get("tipo") == "dinheiro_extra"), None)
        return float(g.get("valor", 0.0)) if g else float(self.exp.get("valor_extra") or 0.0)

    # ------------------------------------------------------------------ cálculo (TOOL -> núcleo determinístico)
    def _calcular(self) -> tuple[dict, list[dict], dict]:
        """Hoje vs opções, com benefícios validados por opção. Levanta exceção se a fonte falhar (AT09)."""
        c = self.ctx
        hoje = situacao_hoje(c.perfil, c.politica)
        r = montar_cenarios(c.perfil, c.capacidade, valor_extra=self._valor_extra(), politica=c.politica)
        opcoes = []
        for cen in r.get("cenarios", []):
            rc = resumo_cenario(cen, hoje, c.politica)
            objetivo, label, desc = objetivo_de(cen.get("rotulos", []))
            beneficios = validar_beneficios(hoje, rc)
            opcoes.append({
                "id": objetivo.lower(), "cenario_id": cen["id"], "objective": objetivo, "label": label, "description": desc,
                "recommended": "recomendado" in cen.get("rotulos", []),
                "monthly_payment": rc["parcela_mensal"], "term_months": rc["prazo_meses"], "total_cost": rc["total_a_pagar"],
                "payments_count": 1, "reserve": rc["reserva"], "uses_cash": cen.get("usa_caixa", 0.0),
                "benefits": beneficios, "claims": claims(beneficios), "tradeoffs": tradeoffs(hoje, {**rc, "usa_caixa": cen.get("usa_caixa", 0.0)}),
                "actions": cen["acoes"], "resolve_negativacao": cen.get("resolve_negativacao", False),
                "autopay": rc["debito_automatico"],
                "numeros_permitidos": rc["numeros_permitidos"],
            })
        opcoes.sort(key=lambda o: ORDEM_OBJETIVOS.index(o["objective"]) if o["objective"] in ORDEM_OBJETIVOS else 9)
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
        if not (checks["proactive_permission"] and checks["trigger_present"]):
            return {"silent": True, "checks": checks, "reason": "sem permissão ou sem gatilho"}
        if self.ctx.estado.get("acordo") and self.ctx.acordo and self.ctx.acordo.status == "ativo" \
                and gatilhos[0].get("tipo") == "dinheiro_extra":
            checks["action_available"] = False
            return {"silent": True, "checks": checks, "reason": "acordo ativo: dinheiro extra segue outro fluxo (amortização)"}
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
        self.exp["contatos_proativos"] = (ultimos + [hoje_sim])[-30:]
        self.exp["hoje"] = hoje
        msg = _resposta("IDLE", "PROACTIVE_MESSAGE", "Diminua suas parcelas",
                        "Reúna suas dívidas em uma parcela que cabe no seu bolso.",
                        cta="Diminuir parcelas", benefit=principal, trigger=gatilhos[0]["tipo"], checks=checks,
                        allowed_actions=["START", "DISMISS"], silent=False)
        self.exp["proativa_ativa"] = msg
        self._salvar()
        self.ctx.registrar_evento("proativa_enviada", {"benefit": principal["benefit_type"], "gatilho": gatilhos[0]["tipo"]})
        return msg

    # ------------------------------------------------------------------ eventos do usuário
    async def evento(self, acao: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        try:
            if acao == "RESET":
                self.ctx.resetar()
                self.__init__(self.ctx, self.explicador)
                return self.resposta_atual()
            if acao == "GET":
                return self.resposta_atual()
            if acao == "START":
                return self._start()
            if acao == "ANSWER":
                return self._answer(payload)
            if acao == "VIEW_OPTIONS":
                return self._showing(comparacao=True)
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
                self._ir("IDLE")
                return self.resposta_atual()
            return self._erro(f"ação desconhecida: {acao}")
        except Exception as e:  # noqa: BLE001 — falha de tool/dado: nunca inventar (AT09)
            log.exception("erro na experiência")
            return self._erro(str(e))

    # --- IDLE / entrada
    def resposta_atual(self) -> dict:
        st = self.state
        if st in ("IDLE", "COMPLETED", "ERROR", "NO_SUITABLE_OPTION"):
            return self._entrada()
        if st == "NEEDS_INFORMATION":
            return self._pergunta_gasto()
        if st in ("SHOWING_OPTIONS", "EXPLAINING", "CALCULATING"):
            return self._showing()
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
        if acordo and acordo.get("status") == "ativo":
            return _resposta(self.state, "SUMMARY", "Seu acordo está em dia.",
                             f"Você paga {brl(acordo['parcela'])} por mês; próximo vencimento em {acordo['proximo_vencimento']}.",
                             summary=hoje, agreement=acordo, allowed_actions=["ASK_QUESTION"], numeros_permitidos=hoje["numeros_permitidos"])
        return _resposta(self.state if self.state != "COMPLETED" else "IDLE", "SUMMARY",
                         "Encontrei uma forma de aliviar seus pagamentos mensais.",
                         f"Hoje, você tem dívidas que comprometem {brl(hoje['pagamento_mensal'])} por mês. "
                         "Posso buscar uma forma de reuni-las e diminuir esse valor.",
                         summary=hoje, cta="Encontrar uma opção", allowed_actions=["START", "ASK_QUESTION"],
                         numeros_permitidos=hoje["numeros_permitidos"])

    # --- EVALUATING -> NEEDS_INFORMATION | CALCULATING
    def _start(self) -> dict:
        self._ir("EVALUATING")
        # 5.1 contexto suficiente? renda e dívidas vêm do extrato (nunca perguntar de novo — AT01).
        # Inferência crítica: gastos fixos fora do extrato mudam "quanto cabe" -> perguntar uma vez (AT02, 5.3).
        if "gasto_recorrente" not in self.exp["perguntas_feitas"]:
            self._ir("NEEDS_INFORMATION")
            return self._pergunta_gasto()
        return self._calculating()

    def _pergunta_gasto(self) -> dict:
        return _resposta("NEEDS_INFORMATION", "QUESTION", "Antes de calcular, preciso confirmar uma coisa.",
                         "Você tem algum gasto importante todo mês que não aparece nas suas contas?",
                         quick_replies=[{"id": "NO", "label": "Não", "hint": "Seguir com as informações que já tenho"},
                                        {"id": "YES", "label": "Sim", "hint": "Quero incluir um gasto", "input": {"campo": "valor_mensal", "tipo": "moeda"}}],
                         allowed_actions=["ANSWER", "ASK_QUESTION"])

    def _answer(self, payload: dict) -> dict:
        if self.state != "NEEDS_INFORMATION":
            return self._erro("não há pergunta pendente")
        resposta = str(payload.get("id", "NO")).upper()
        if resposta == "YES":
            valor = float(payload.get("valor_mensal") or 0)
            if valor > 0:
                self.ctx.adicionar_compromisso(str(payload.get("descricao") or "gasto importante"), valor)
        self.exp["perguntas_feitas"].append("gasto_recorrente")
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
        validas = [o for o in opcoes if o["benefits"]]
        if r.get("nenhum_cenario_cabe") or not validas:
            self._ir("NO_SUITABLE_OPTION")
            self.ctx.registrar_evento("nenhuma_opcao_adequada", {"motivo": r.get("motivo")})
            return _resposta("NO_SUITABLE_OPTION", "TEXT", "Não encontrei uma opção que caiba no seu bolso agora.",
                             "Não vou te empurrar uma opção que não cabe. Posso te colocar com uma pessoa do time para olhar seu caso com calma.",
                             allowed_actions=["ESCALATE", "ASK_QUESTION"], quick_replies=[{"id": "ESCALATE", "label": "Falar com uma pessoa"}])
        self._ir("SHOWING_OPTIONS")
        self.ctx.registrar_evento("opcoes_apresentadas", {"qtd": len(validas), "recomendada": next((o["id"] for o in validas if o["recommended"]), None)})
        return self._showing(status=STATUS_CALCULO)

    def _showing(self, comparacao: bool = False, status: dict | None = None) -> dict:
        opcoes = self.exp.get("opcoes") or []
        hoje = self.exp.get("hoje") or situacao_hoje(self.ctx.perfil, self.ctx.politica)
        rec = next((o for o in opcoes if o["recommended"]), opcoes[0] if opcoes else None)
        if rec is None:
            return self._erro("sem opções calculadas")
        if comparacao:
            return _resposta("SHOWING_OPTIONS", "OPTIONS_COMPARISON", f"Encontrei {len(opcoes)} formas de diminuir suas parcelas.",
                             "Compare o que muda em cada uma.", options=opcoes, current=hoje,
                             allowed_actions=["SELECT_OPTION", "ASK_WHY", "ASK_QUESTION"],
                             quick_replies=[{"id": "ADJUST", "label": "Precisa de um valor diferente? Posso ajustar as opções."}],
                             numeros_permitidos=sorted({n for o in opcoes for n in o["numeros_permitidos"]} | set(hoje["numeros_permitidos"])))
        principal = beneficio_principal(rec["benefits"])
        titulo = (f"Você pode liberar {brl(principal['monthly_difference'])} por mês" if principal and principal["benefit_type"] == "LOWER_MONTHLY_PAYMENT"
                  else "Encontrei uma opção para reunir suas dívidas")
        return _resposta("SHOWING_OPTIONS", "OPTION_DETAIL", titulo,
                         "Encontrei uma opção para reunir suas dívidas e diminuir o valor dos seus pagamentos mensais.",
                         option=rec, current=hoje, benefit=principal, claims=rec["claims"], tradeoffs=rec["tradeoffs"],
                         status=status, allowed_actions=["SELECT_OPTION", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION"],
                         cta="Continuar com esta opção", numeros_permitidos=rec["numeros_permitidos"] + hoje["numeros_permitidos"])

    # --- EXPLAINING (critério determinístico + LLM opcional)
    async def _ask_why(self, payload: dict) -> dict:
        if self.state not in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING"):
            return self._erro("nada para explicar ainda")
        opcoes = self.exp.get("opcoes") or []
        alvo = next((o for o in opcoes if o["id"] == str(payload.get("option_id", "")).lower()), None) \
            or next((o for o in opcoes if o["recommended"]), opcoes[0])
        criterios = criterio_recomendacao(alvo | {"parcela_mensal": alvo["monthly_payment"], "reserva": alvo["reserve"]},
                                          self.exp.get("parcela_conforto") or self.ctx.capacidade.parcela_maxima,
                                          self.exp.get("perfil_risco", "renda_estavel"))
        texto = ""
        if self.explicador:
            hoje = self.exp["hoje"]
            pergunta = ("Explique em até 4 frases curtas, em linguagem cotidiana e sem pressão, por que esta opção foi destacada, "
                        "usando apenas estes fatos e números: " + " ".join(criterios) +
                        f" Parcela {brl(alvo['monthly_payment'])} por mês, prazo {alvo['term_months']} meses, total {brl(alvo['total_cost'])}; "
                        f"hoje {brl(hoje['pagamento_mensal'])} por mês em {hoje['qtd_pagamentos']} pagamentos. Trade-offs: " + " ".join(alvo["tradeoffs"]))
            try:
                texto = await self.explicador(pergunta, alvo["numeros_permitidos"] + hoje["numeros_permitidos"])
            except Exception as e:  # noqa: BLE001 — sem LLM, a explicação determinística basta
                log.warning("explicador indisponível: %s", e)
        self._ir("EXPLAINING")
        return _resposta("EXPLAINING", "TEXT", f"Por que “{alvo['label']}”?", texto or " ".join(criterios),
                         criteria=criterios, tradeoffs=alvo["tradeoffs"], option=alvo,
                         allowed_actions=["SELECT_OPTION", "VIEW_OPTIONS", "ASK_QUESTION"])

    async def _ask_question(self, payload: dict) -> dict:
        texto = str(payload.get("text", "")).strip()
        if not texto:
            return self._erro("pergunta vazia")
        resposta = ""
        if self.explicador:
            try:
                permitidos = sorted({n for o in self.exp.get("opcoes", []) for n in o["numeros_permitidos"]} | set((self.exp.get("hoje") or {}).get("numeros_permitidos", [])))
                resposta = await self.explicador(texto, permitidos)
            except Exception as e:  # noqa: BLE001
                log.warning("LLM indisponível: %s", e)
        if not resposta:
            resposta = "Não consegui responder isso agora. Posso te mostrar as opções calculadas ou te colocar com uma pessoa do time."
        return _resposta(self.state, "TEXT", "", resposta, allowed_actions=self._acoes_do_estado())

    def _acoes_do_estado(self) -> list[str]:
        return {"SHOWING_OPTIONS": ["SELECT_OPTION", "VIEW_OPTIONS", "ASK_WHY", "ASK_QUESTION"],
                "EXPLAINING": ["SELECT_OPTION", "VIEW_OPTIONS", "ASK_QUESTION"],
                "REVIEWING": ["CONTINUE", "CANCEL", "ASK_QUESTION"],
                "AWAITING_CONFIRMATION": ["CONFIRM", "CANCEL"]}.get(self.state, ["START", "ASK_QUESTION"])

    # --- REVIEWING: termos -> débito automático -> AWAITING_CONFIRMATION
    def _select(self, payload: dict) -> dict:
        if self.state not in ("SHOWING_OPTIONS", "EXPLAINING", "REVIEWING"):
            return self._erro("selecione uma opção depois de ver as opções")
        oid = str(payload.get("option_id", "")).lower()
        opcao = next((o for o in (self.exp.get("opcoes") or []) if o["id"] == oid or o["cenario_id"].lower() == oid), None)
        if not opcao:
            return self._erro(f"opção {oid} não existe")
        self.exp["selected_option"] = opcao["id"]
        self.exp["autopay"] = None
        self._ir("REVIEWING")
        self.ctx.registrar_evento("opcao_selecionada", {"opcao": opcao["id"]})
        return self._termos(autopay=None)

    def _opcao_selecionada(self) -> dict | None:
        return next((o for o in (self.exp.get("opcoes") or []) if o["id"] == self.exp.get("selected_option")), None)

    def _termos(self, autopay: bool | None) -> dict:
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._erro("nenhuma opção selecionada")
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        t = termos(cen, self.ctx.perfil, self.ctx.hoje, bool(autopay), self.ctx.politica)
        hoje = self.exp["hoje"]
        return _resposta("REVIEWING", "TERMS_REVIEW", "Revise os termos da sua nova opção",
                         "Verifique as informações antes de continuar. Esta opção reúne suas dívidas em um único pagamento.",
                         option=opcao, terms=t, current=hoje, tradeoffs=opcao["tradeoffs"], autopay=autopay,
                         allowed_actions=["CONTINUE", "CANCEL", "ASK_QUESTION"], cta="Continuar",
                         notice="Você sempre decide. Esta contratação só será concluída com a sua confirmação.",
                         numeros_permitidos=t["numeros_permitidos"])

    def _continue(self) -> dict:
        if self.state != "REVIEWING":
            return self._erro("nada para continuar")
        opcao = self._opcao_selecionada()
        if self.exp.get("autopay") is None:  # §16: oferecer débito automático se houver condição real
            da = opcao["autopay"]
            if da["desconto_mensal"] > 0:
                return _resposta("REVIEWING", "QUESTION", "Economize mais com débito automático",
                                 "Ative o débito automático e reduza sua parcela. Você continua no controle e pode cancelar quando quiser.",
                                 benefit={"benefit_type": "AUTOPAY_DISCOUNT", "regular_payment": opcao["monthly_payment"],
                                          "autopay_payment": da["parcela_com_desconto"], "monthly_discount": da["desconto_mensal"]},
                                 quick_replies=[{"id": "AUTOPAY_YES", "label": f"Quero pagar {brl(da['parcela_com_desconto'])}/mês com débito automático",
                                                 "hint": f"{brl(da['desconto_mensal'])} de desconto por mês"},
                                                {"id": "AUTOPAY_NO", "label": f"Prefiro pagar {brl(opcao['monthly_payment'])}/mês por conta própria",
                                                 "hint": "Você recebe o boleto todo mês e escolhe como quer pagar."}],
                                 allowed_actions=["SET_AUTOPAY", "CANCEL"], option=opcao)
            self.exp["autopay"] = False
        return self._confirmacao()

    def _set_autopay(self, payload: dict) -> dict:
        if self.state != "REVIEWING":
            return self._erro("fora de hora para débito automático")
        self.exp["autopay"] = bool(payload.get("autopay", str(payload.get("id", "")).upper() == "AUTOPAY_YES"))
        self._salvar()
        return self._confirmacao()

    def _confirmacao(self) -> dict:
        opcao = self._opcao_selecionada()
        if not opcao:
            return self._erro("nenhuma opção selecionada")
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        autopay = bool(self.exp.get("autopay"))
        t = termos(cen, self.ctx.perfil, self.ctx.hoje, autopay, self.ctx.politica)  # recalcula tudo antes de confirmar (§16)
        hoje = self.exp["hoje"]
        beneficios = validar_beneficios(hoje, {"parcela_mensal": t["parcela_mensal"], "total_a_pagar": t["total_a_pagar"],
                                               "prazo_meses": t["prazo_meses"], "qtd_pagamentos": 1, "resolve_negativacao": opcao["resolve_negativacao"]})
        self._ir("AWAITING_CONFIRMATION")
        return _resposta("AWAITING_CONFIRMATION", "CONFIRMATION_REQUEST", "Confirme sua contratação",
                         "Revise as informações finais para concluir." + (" Com o débito automático, você garante "
                         f"{brl(t['desconto_debito_automatico'])} de desconto por mês." if autopay else ""),
                         requires_confirmation=True, selected_option=opcao, final_terms=t, benefits=beneficios, claims=claims(beneficios),
                         account={"banco": "Itaú", "agencia": "1234", "conta": "56789-0"} if autopay else None,
                         allowed_actions=["CONFIRM", "CANCEL"], cta="Confirmar contratação",
                         notice="Ao confirmar, você aceita os termos e condições da contratação" + (" e autoriza o débito automático na conta selecionada." if autopay else "."),
                         numeros_permitidos=t["numeros_permitidos"])

    # --- EXECUTING -> COMPLETED (sistema transacional = motor.criar_acordo_de_cenario)
    def _confirm(self, payload: dict) -> dict:
        if self.state != "AWAITING_CONFIRMATION":
            return self._erro("confirmação só vale depois de revisar os termos")
        opcao = self._opcao_selecionada()
        cen = self.exp["cenarios"][opcao["cenario_id"]]
        autopay = bool(self.exp.get("autopay"))
        self._ir("EXECUTING")
        t = termos(cen, self.ctx.perfil, self.ctx.hoje, autopay, self.ctx.politica)
        consentimento = {"acao": "fechar_acordo", "frase_cliente": str(payload.get("frase", "Confirmar contratação")),
                         "versao_termo": "demo-v1", "timestamp": datetime.now().isoformat(timespec="seconds"),
                         "data_simulada": self.ctx.estado["hoje"], "debito_automatico": autopay, "opcao": opcao["id"]}
        self.ctx.estado.setdefault("consentimentos", []).append(consentimento)
        acordo = criar_acordo_de_cenario(self.ctx.perfil, cen, self.ctx.hoje, self.ctx.politica)
        if autopay and t["desconto_debito_automatico"] > 0:
            pct = self.ctx.politica["desconto_debito_automatico_pct"]
            for comp in acordo.componentes:
                comp["parcela"] = r2(comp["parcela"] * (1 - pct))
            acordo.parcela = t["parcela_mensal"]
            acordo.historico.append({"data": self.ctx.estado["hoje"], "evento": "debito_automatico_ativado", "desconto_mensal": t["desconto_debito_automatico"]})
        self.ctx.estado["gatilhos_pendentes"] = []
        self.exp["proativa_ativa"] = None
        self.ctx.salvar(acordo)
        hoje = self.exp["hoje"]
        reducao = r2(hoje["pagamento_mensal"] - t["parcela_mensal"])
        self._ir("COMPLETED")
        self.ctx.registrar_evento("acordo_fechado", {"origem": "experiencia", "opcao": opcao["id"], "parcela": acordo.parcela,
                                                     "prazo": acordo.prazo, "debito_automatico": autopay})
        titulo = f"Pronto! Você reduziu suas parcelas em {brl(reducao)} por mês" if reducao > 0 else "Pronto! Suas dívidas foram reunidas"
        return _resposta("COMPLETED", "SUCCESS", titulo,
                         f"Suas dívidas foram reunidas em uma parcela de {brl(t['parcela_mensal'])}" + (", com débito automático." if autopay else "."),
                         status=STATUS_EXECUCAO, agreement=acordo.to_dict(), final_terms=t,
                         result={"new_monthly_payment": t["parcela_mensal"], "first_due_date": t["primeiro_vencimento"],
                                 "monthly_reduction": reducao if reducao > 0 else 0.0},
                         next_steps=["Suas dívidas foram reunidas — você paga todas em uma única parcela.",
                                     "O débito automático já está ativo — as próximas parcelas serão pagas automaticamente." if autopay else "Você recebe o boleto todo mês e escolhe como pagar.",
                                     "Você continua no controle — pode acompanhar e cancelar quando quiser."],
                         allowed_actions=["FOLLOW", "HOME"], cta="Acompanhar minha nova opção", numeros_permitidos=t["numeros_permitidos"])

    def _cancel(self) -> dict:
        if self.state == "AWAITING_CONFIRMATION":
            self._ir("REVIEWING")
            return self._termos(self.exp.get("autopay"))
        self.exp["selected_option"] = None
        self._ir("SHOWING_OPTIONS" if self.exp.get("opcoes") else "IDLE")
        return self.resposta_atual()

    def _erro(self, detalhe: str) -> dict:
        anterior = self.state
        self.exp["state"] = "ERROR"
        self._salvar()
        self.ctx.registrar_evento("erro_experiencia", {"detalhe": detalhe[:200], "estado_anterior": anterior})
        self.exp["state"] = anterior if anterior not in ("EXECUTING", "CALCULATING") else "IDLE"
        self._salvar()
        return _resposta("ERROR", "ERROR", "Não consegui concluir esta etapa agora.",
                         "Não vou inventar nenhum valor. Você pode tentar de novo em instantes ou falar com uma pessoa do time.",
                         error=detalhe, allowed_actions=["RETRY", "ESCALATE", "ASK_QUESTION"])
