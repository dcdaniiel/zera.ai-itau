"""Testes rodam com o fixture sintético (ZERA_FONTE=fixture) — nunca com dados da aplicação.
Testes que exercitam a amostra real ou o BigQuery (stubado) sobrescrevem a env explicitamente."""

import os

os.environ.setdefault("ZERA_FONTE", "fixture")
os.environ.setdefault("ZERA_LOG_LEVEL", "ERROR")
os.environ.setdefault("ZERA_LOG_JSON", "0")
