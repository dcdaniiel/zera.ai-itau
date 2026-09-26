# Zera — renegociação que cabe no mês do cliente

Agente conversacional (ADK + Gemini no Vertex AI) para a **Batalha de Agentes Itaú × Google**.
Transforma várias dívidas em um único plano dimensionado pela sobra real do cliente, com respiro previsto e
acompanhamento até limpar o nome. PRD e arquitetura: [`docs/PRD-MVP.md`](docs/PRD-MVP.md).

```
motor/        cálculo determinístico: capacidade, priorização, simulação (Price), respiro, amortização, gatilhos
dados/        extrato sintético da persona (Cleide), loader CSV/BigQuery, SQL de features e eventos
zera_agent/   agente ADK: prompt, tools, guardrails (callbacks), contexto/relógio de simulação
api/          FastAPI: /chat, /simular_tempo, /gatilhos (para a UI com cards)
tests/        motor + fluxo do agente com modelo falso (roda sem credenciais)
infra/        setup do projeto GCP e deploy (Agent Engine / Cloud Run)
```

## Rodar local (P0)

```bash
uv sync                                  # ou: pip install -e .
cp zera_agent/.env.example zera_agent/.env
gcloud auth application-default login    # projeto batalha-time-03-vhxk
python -m dados.gerar_cleide             # (re)gera dados/cleide_12m.csv
uv run pytest -q                         # 15 testes, sem rede
uv run adk web                           # UI de dev -> escolha "zera_agent"
```

Roteiro na `adk web`: `quanto eu devo?` → planos → `quero o plano C` → `sim, confirmo` → em outro terminal
`python -c "from zera_agent.contexto import Contexto; from datetime import date; print(Contexto.para('cli_001').avancar_tempo(date(2027,1,7)))"`
→ volte ao chat e mande `oi` (o agente inicia pelo gatilho `risco_parcela`) → `quero sim` → avance para `2027-05-12`
→ `oi` (gatilho `dinheiro_extra`) → aceite a amortização.

API para a UI: `uv run uvicorn api.main:app --port 8080` (`POST /chat`, `POST /simular_tempo`, `GET /gatilhos/cli_001`, `POST /reset/cli_001`).

## GCP (P1)

```bash
infra/setup_gcp.sh              # APIs, Firestore, dataset zera, bucket
infra/deploy_agent_engine.sh    # Vertex AI Agent Engine (Sessions + Memory Bank)
infra/deploy_cloud_run.sh       # fallback
```

Variáveis (ver `zera_agent/.env.example`): `ZERA_MODEL`, `ZERA_FONTE=csv|bigquery`, `ZERA_FIRESTORE=1`,
`ZERA_MULTIAGENTE=1`, `ZERA_STRICT_NUMEROS=1`, `ZERA_HOJE`.

## Guardrails em código

- **Números só das tools** — `after_model_callback` valida todo `R$`, `%` e `Nx` da resposta contra `numeros_permitidos`.
- **Consentimento por ação** — `before_tool_callback` bloqueia `fechar_acordo`, `acionar_respiro`, `amortizar(aplicar=true)` sem `registrar_consentimento` na sessão; consentimento é de uso único.
- **Parcela ≤ parcela máxima por construção** — o motor não devolve plano que viole; sem plano → `escalar_humano`.
- **PII e vulnerabilidade** — `before_model_callback` redige CPF/telefone/cartão e muda o tom + escala em sinais de sofrimento.
- **Direito de esquecer** — `revogar_consentimento` apaga memória e estado.
