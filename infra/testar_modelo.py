"""Descobre qual Gemini o projeto consegue chamar e em que location (roda com ADC: gcloud auth application-default login).

    uv run python infra/testar_modelo.py
"""

import os

from google import genai

PROJETO = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
MODELOS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash"]
LOCATIONS = ["global", "us-central1"]

for loc in LOCATIONS:
    client = genai.Client(vertexai=True, project=PROJETO, location=loc)
    for m in MODELOS:
        try:
            r = client.models.generate_content(model=m, contents="Responda só: ok")
            print(f"OK   {loc:12s} {m:20s} -> {r.text.strip()[:20]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {loc:12s} {m:20s} -> {str(e)[:90]}")
