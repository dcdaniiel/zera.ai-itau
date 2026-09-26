"""Modelo falso e roteirizado para testar o fluxo do agente sem Gemini/credenciais.

Cada turno do usuário vira uma lista de "passos": function calls e, no fim, um texto.
Serve para validar tools, callbacks (consentimento, números) e estado — não a qualidade da conversa.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.models import LlmRequest, LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.genai import types


class FakeLlm(BaseLlm):
    """roteiro: {texto_do_usuario: [("call", nome, args) | ("text", texto)]}"""

    model: str = "fake"
    roteiro: dict = {}
    chamadas: list = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        # último texto do usuário
        ultimo_usuario = ""
        for c in reversed(contents):
            if c.role == "user" and c.parts and any(p.text for p in c.parts):
                ultimo_usuario = " ".join(p.text or "" for p in c.parts)
                break
        passos = self.roteiro.get(ultimo_usuario.strip(), [("text", "Não sei o que fazer com isso.")])
        # quantos function responses já existem desde o último texto do usuário -> índice do passo
        feitos = 0
        for c in contents:
            if c.role == "user" and c.parts and any(p.text == ultimo_usuario for p in c.parts):
                feitos = 0
            elif c.parts and any(p.function_response for p in c.parts):
                feitos += sum(1 for p in c.parts if p.function_response)
        passo = passos[min(feitos, len(passos) - 1)]
        self.chamadas.append(passo)
        if passo[0] == "call":
            part = types.Part(function_call=types.FunctionCall(name=passo[1], args=passo[2]))
        else:
            part = types.Part(text=passo[1])
        yield LlmResponse(content=types.Content(role="model", parts=[part]))
