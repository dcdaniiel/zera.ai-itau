"""Guardrails em código (callbacks do ADK).

- antes_do_modelo      : redige PII, detecta vulnerabilidade, injeta memória e gatilhos pendentes
- exigir_consentimento : bloqueia ações com efeito sem consentimento registrado nesta sessão
- registrar_numeros    : acumula os números permitidos das tools (after_tool)
- checar_numeros       : valida todo valor da resposta contra os números das tools (after_model)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from zera_agent.contexto import Contexto

log = logging.getLogger("zera.guardrails")

ACOES_COM_CONSENTIMENTO = {"fechar_acordo", "acionar_respiro", "amortizar"}

PADRAO_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PADRAO_TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")
PADRAO_CARTAO = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PADRAO_VULNERABILIDADE = re.compile(
    r"(n[ãa]o aguento|desesper|acabar com tudo|me matar|suic|depress|doen[çc]a grave|c[âa]ncer|internad|"
    r"luto|faleceu|morreu|amea[çc]a|agiota|violen|n[ãa]o tenho o que comer|fome)",
    re.IGNORECASE,
)
# R$ 1.234,56 | R$1234 | 1.234,56 reais | 12x | 1,5%
PADRAO_DINHEIRO = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")
PADRAO_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
PADRAO_PRAZO = re.compile(r"\b(\d{1,3})\s?x\b", re.IGNORECASE)


def _para_float(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


# ---------- before_model ----------

def antes_do_modelo(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    cliente_id = callback_context.state.get("cliente_id", "cli_001")
    ctx = Contexto.para(cliente_id)

    # 1) PII: redige CPF/telefone/cartão no que o cliente digitou (P1: Sensitive Data Protection API)
    for content in llm_request.contents or []:
        if content.role != "user":
            continue
        for part in content.parts or []:
            if part.text:
                novo = PADRAO_CPF.sub("[CPF removido]", part.text)
                novo = PADRAO_CARTAO.sub("[número removido]", novo)
                novo = PADRAO_TELEFONE.sub("[telefone removido]", novo)
                if novo != part.text:
                    callback_context.state["pii_redigida"] = callback_context.state.get("pii_redigida", 0) + 1
                    part.text = novo

    # 2) vulnerabilidade: muda o tom e pede escalonamento
    ultima = ""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            ultima = " ".join(p.text or "" for p in content.parts)
            break
    instrucoes: list[str] = []
    if PADRAO_VULNERABILIDADE.search(ultima):
        callback_context.state["vulneravel"] = True
        instrucoes.append(
            "ATENÇÃO: o cliente demonstrou sinal de vulnerabilidade. Acolha em uma frase, NÃO negocie, "
            "não apresente planos, e ofereça falar com uma pessoa chamando escalar_humano."
        )

    # 3) contexto: data simulada, memória e gatilhos pendentes
    instrucoes.append(f"DATA DE HOJE (simulada): {ctx.estado['hoje']}. Cliente: {ctx.perfil.nome} (id {cliente_id}).")
    memoria = ctx.estado.get("memoria") or {}
    if memoria:
        instrucoes.append("MEMÓRIA DO CLIENTE: " + "; ".join(f"{k}={v}" for k, v in memoria.items()))
    if ctx.estado.get("acordo"):
        a = ctx.estado["acordo"]
        instrucoes.append(f"ACORDO ATIVO: {a['status']}, {a['pagas']} parcelas pagas de {a['prazo']}, "
                          f"parcela {a['parcela']:.2f}, próximo vencimento {a['proximo_vencimento']}, "
                          f"respiros usados {a['respiros_usados']} de {a['respiros_max']}.")
    gatilhos = ctx.estado.get("gatilhos_pendentes") or []
    if gatilhos:
        linhas = "; ".join(f"{g['tipo']}: {g['mensagem']}" for g in gatilhos)
        instrucoes.append(
            "GATILHO PENDENTE — você deve INICIAR a conversa explicando o que viu e propondo UMA ação, "
            "pedindo confirmação: " + linhas + ". Use as tools para citar números."
        )
        callback_context.state["gatilho"] = gatilhos
    if instrucoes:
        llm_request.append_instructions(instrucoes)
    return None


# ---------- before_tool ----------

def exigir_consentimento(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    nome = tool.name
    if nome == "amortizar" and not args.get("aplicar"):
        return None  # simulação não precisa de consentimento
    if nome in ACOES_COM_CONSENTIMENTO:
        consentimentos = tool_context.state.get("consentimento") or {}
        if not consentimentos.get(nome):
            tool_context.state["bloqueios_consentimento"] = tool_context.state.get("bloqueios_consentimento", 0) + 1
            return {
                "erro": "consentimento_ausente",
                "acao": nome,
                "instrucao": ("Antes de executar, pergunte ao cliente se ele confirma, espere a resposta, "
                              "chame registrar_consentimento(acao, frase_cliente) e só então chame esta ação."),
            }
    return None


# ---------- after_tool ----------

def registrar_numeros(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict) -> dict | None:
    permitidos = set(tool_context.state.get("ultimos_numeros") or [])
    if isinstance(tool_response, dict):
        permitidos.update(float(x) for x in tool_response.get("numeros_permitidos", []))
    tool_context.state["ultimos_numeros"] = sorted(permitidos)[-400:]
    # consentimento é de uso único: consumido pela ação
    if tool.name in ACOES_COM_CONSENTIMENTO and isinstance(tool_response, dict) and tool_response.get("ok"):
        consentimentos = dict(tool_context.state.get("consentimento") or {})
        consentimentos.pop(tool.name, None)
        tool_context.state["consentimento"] = consentimentos
    # gatilho tratado quando o agente age sobre ele
    if tool.name in {"acionar_respiro", "amortizar", "fechar_acordo", "escalar_humano"}:
        Contexto.para(tool_context.state.get("cliente_id", "cli_001")).consumir_gatilhos()
        tool_context.state["gatilho"] = []
    return None


# ---------- after_model ----------

def _valores_na_resposta(texto: str) -> dict[str, list[float]]:
    return {
        "dinheiro": [_para_float(m) for m in PADRAO_DINHEIRO.findall(texto)],
        "pct": [_para_float(m) for m in PADRAO_PCT.findall(texto)],
        "prazo": [float(m) for m in PADRAO_PRAZO.findall(texto)],
    }


def _permitido(valor: float, permitidos: list[float], tolerancia: float = 0.6) -> bool:
    return any(abs(valor - p) <= tolerancia for p in permitidos)


def checar_numeros(callback_context: CallbackContext, llm_response: LlmResponse) -> LlmResponse | None:
    if not llm_response.content or not llm_response.content.parts:
        return None
    texto = "".join(p.text or "" for p in llm_response.content.parts if p.text)
    if not texto:
        return None
    permitidos = [float(x) for x in (callback_context.state.get("ultimos_numeros") or [])]
    achados = _valores_na_resposta(texto)
    estranhos = [v for grupo in ("dinheiro", "pct", "prazo") for v in achados[grupo] if not _permitido(v, permitidos)]
    if not estranhos:
        return None
    total = callback_context.state.get("alucinacao_numerica", 0) + len(estranhos)
    callback_context.state["alucinacao_numerica"] = total
    log.warning("números fora das tools na resposta: %s", estranhos)
    if os.getenv("ZERA_STRICT_NUMEROS") == "1":
        novo = texto
        for m in list(PADRAO_DINHEIRO.finditer(texto))[::-1]:
            if not _permitido(_para_float(m.group(1)), permitidos):
                novo = novo[:m.start()] + "[valor a confirmar]" + novo[m.end():]
        novo += "\n\n(Alguns valores acima precisam ser confirmados; vou verificar com a calculadora.)"
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=novo)]))
    return None
