# Zera — um único serviço no Cloud Run: API (FastAPI + ADK + Gemini) servindo a UI (Vite build)
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY motor/ motor/
COPY dados/ dados/
COPY zera_agent/ zera_agent/
COPY api/ api/
COPY --from=ui /ui/dist ui/dist
ENV PORT=8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
