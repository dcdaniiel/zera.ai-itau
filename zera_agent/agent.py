"""Zera — agente ADK (Gemini no Vertex AI).

Topologia:
- padrão (P0): um único LlmAgent com todas as tools (mais previsível na demo).
- ZERA_MULTIAGENTE=1 (P1): root Zera + sub-agentes Diagnóstico / Negociador / Acompanhamento.

Rodar local:  adk web   (na raiz do repo; selecione "zera_agent")
Deploy:       infra/deploy_agent_engine.sh  |  infra/deploy_cloud_run.sh
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# permite importar `motor` e `dados` tanto da raiz do repo (adk web) quanto de dentro do pacote
# (Agent Engine / Cloud Run: os scripts de deploy copiam motor/ e dados/ para zera_agent/)
AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
for _p in (RAIZ, AQUI):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from google.adk.agents import LlmAgent  # noqa: E402
from google.genai import types  # noqa: E402

from zera_agent import guardrails, prompts, tools  # noqa: E402

# Troque pelo Flash mais novo habilitado no projeto (ver Model Garden / quota). Ex.: gemini-3-flash-preview
MODEL = os.getenv("ZERA_MODEL", "gemini-3.8-flash")  # fallback estável: gemini-2.5-flash
CONFIG = types.GenerateContentConfig(temperature=float(os.getenv("ZERA_TEMPERATURA", "0.2")))

# Arquitetura de guardrails do workshop RAI: entrada (bloqueia) -> modelo -> saída (bloqueia)
CALLBACKS = dict(
    before_model_callback=guardrails.guardrail_entrada,
    before_tool_callback=guardrails.exigir_consentimento,
    after_tool_callback=guardrails.registrar_numeros,
    after_model_callback=guardrails.guardrail_saida,
)


def _multiagente() -> LlmAgent:
    diagnostico = LlmAgent(
        name="diagnostico", model=MODEL, instruction=prompts.DIAGNOSTICO,
        description="Consolida dívidas, renda e despesas; explica raio-X, prioridade e capacidade de pagamento.",
        tools=tools.TOOLS_DIAGNOSTICO, generate_content_config=CONFIG, **CALLBACKS,
    )
    negociador = LlmAgent(
        name="negociador", model=MODEL, instruction=prompts.NEGOCIADOR,
        description="Simula e recomenda planos de renegociação que cabem na sobra real do cliente.",
        tools=tools.TOOLS_NEGOCIADOR, generate_content_config=CONFIG, **CALLBACKS,
    )
    acompanhamento = LlmAgent(
        name="acompanhamento", model=MODEL, instruction=prompts.ACOMPANHAMENTO,
        description="Acompanha o acordo: status, respiro em mês apertado, amortização com dinheiro extra.",
        tools=tools.TOOLS_ACOMPANHAMENTO, generate_content_config=CONFIG, **CALLBACKS,
    )
    return LlmAgent(
        name="zera", model=MODEL, instruction=prompts.ROOT,
        description="Agente do Itaú para renegociação de dívidas que cabe no mês do cliente.",
        tools=tools.TOOLS_ROOT, sub_agents=[diagnostico, negociador, acompanhamento],
        generate_content_config=CONFIG, **CALLBACKS,
    )


def _agente_unico() -> LlmAgent:
    return LlmAgent(
        name="zera", model=MODEL, instruction=prompts.ROOT,
        description="Agente do Itaú para renegociação de dívidas que cabe no mês do cliente.",
        tools=tools.TODAS, generate_content_config=CONFIG, **CALLBACKS,
    )


root_agent = _multiagente() if os.getenv("ZERA_MULTIAGENTE") == "1" else _agente_unico()
