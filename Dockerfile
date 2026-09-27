# zera.ai — um único serviço no Cloud Run: API (FastAPI + ADK + Gemini) servindo a UI (Vite build)
# Build multi-stage; imagem final enxuta, usuário sem privilégio, 1 worker (cache de contexto em processo) e uvicorn atrás do proxy do Cloud Run.
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 \
    ZERA_LOG_JSON=1 ZERA_AMBIENTE=producao PORT=8080
RUN adduser --disabled-password --gecos "" --uid 10001 zera
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY motor/ motor/
COPY dados/ dados/
COPY zera_agent/ zera_agent/
COPY api/ api/
COPY --from=ui /ui/dist ui/dist
RUN mkdir -p /app/.zera_state && chown -R zera:zera /app
USER zera
EXPOSE 8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
