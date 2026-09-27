"""Pacote do agente zera.ai.

Carrega `zera_agent/.env` (o mesmo arquivo que o `adk web` lê) também para uvicorn, pytest e scripts — sem isso o SDK do
Gemini cai no modo "API key" e o agente não responde fora do `adk web`. Variáveis já exportadas no shell têm precedência
(padrão dotenv), como no Cloud Run, onde a configuração vem do serviço; se uma delas divergir do .env, avisa no stderr
(caso clássico: GOOGLE_CLOUD_LOCATION=us-central1 no .zshrc quebra o gemini-3.x, servido em `global`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV = Path(__file__).resolve().parent / ".env"
if _ENV.exists():
    try:
        from dotenv import dotenv_values, load_dotenv

        load_dotenv(_ENV, override=False)
        for chave, valor in (dotenv_values(_ENV) or {}).items():
            if chave.startswith("GOOGLE_") and valor is not None and os.environ.get(chave, valor) != valor:
                print(f"[zera] aviso: {chave}={os.environ[chave]!r} exportada no shell difere do .env ({valor!r}); "
                      f"rode `unset {chave}` se quiser usar o .env", file=sys.stderr)
    except ImportError:  # python-dotenv vem com o google-adk; sem ele, a configuração precisa vir do ambiente
        pass

from . import agent  # noqa: E402,F401  (padrão do ADK: expõe root_agent)
