"""Observabilidade e FinOps do zera.ai — uma camada, quatro saídas.

    1. OpenTelemetry: spans do ADK (invocation, agent, call_llm, execute_tool) + spans próprios (motor, experiência, HTTP)
       -> `telemetry.googleapis.com` (Cloud Trace / Cloud Monitoring / Cloud Logging) quando ZERA_OTEL_GCP=1,
          ou qualquer coletor OTLP via OTEL_EXPORTER_OTLP_ENDPOINT (ADK `maybe_set_otel_providers`).
    2. Logs estruturados (JSON no stdout): no Cloud Run viram entradas do Cloud Logging com severity, trace e labels
       -> métricas baseadas em logs (infra/observabilidade.sh) e alertas.
    3. Registro em memória (contadores, histogramas p50/p95) -> GET /metrics (JSON) para smoke e dashboards.
    4. BigQuery `zera.telemetria` (append, best-effort, em lote) -> Looker Studio: custo por jornada, tokens, latência,
       funil de estados, bloqueios de guardrail.

FinOps: cada chamada ao Gemini registra tokens (usage_metadata do ADK) × tabela de preços (env) = custo em USD por
chamada; somado por `jornada_id` dá o custo por jornada. O núcleo determinístico custa zero tokens — e esse é o ponto:
o LLM entra em 2 das 10 telas (explicar e responder), tudo o mais é motor.

Nada aqui derruba a conversa: toda exportação é best-effort e silenciosa em caso de falha.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

log = logging.getLogger("zera.observabilidade")
_metricas_log = logging.getLogger("zera.metricas")

SERVICO = os.getenv("ZERA_SERVICO", "zera")
VERSAO = os.getenv("ZERA_VERSAO", os.getenv("K_REVISION", "local"))
_INICIO = time.time()

# --- tabela de preços (USD por 1M tokens). Valores de referência da classe "Flash"; confirme na tabela oficial do
# modelo em uso (ZERA_MODEL) e sobrescreva por env. Só serve para ESTIMAR custo por chamada/jornada.
PRECO_ENTRADA = float(os.getenv("ZERA_PRECO_ENTRADA_USD_1M", "0.30"))
PRECO_SAIDA = float(os.getenv("ZERA_PRECO_SAIDA_USD_1M", "2.50"))
PRECO_CACHE = float(os.getenv("ZERA_PRECO_CACHE_USD_1M", "0.075"))
PRECO_PENSAMENTO = float(os.getenv("ZERA_PRECO_PENSAMENTO_USD_1M", os.getenv("ZERA_PRECO_SAIDA_USD_1M", "2.50")))


# ======================================================================
# Logs estruturados
# ======================================================================

class FormatoJson(logging.Formatter):
    """Uma linha JSON por log — o Cloud Logging entende `severity`, `message`, `logging.googleapis.com/trace`."""

    NIVEIS = {"DEBUG": "DEBUG", "INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "CRITICAL"}

    def format(self, record: logging.LogRecord) -> str:
        item: dict[str, Any] = {
            "severity": self.NIVEIS.get(record.levelname, "DEFAULT"), "message": record.getMessage(),
            "logger": record.name, "servico": SERVICO, "versao": VERSAO,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        extra = getattr(record, "zera", None)
        if isinstance(extra, dict):
            item.update(extra)
        trace_id = _trace_id_atual()
        if trace_id and os.getenv("GOOGLE_CLOUD_PROJECT"):
            item["logging.googleapis.com/trace"] = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}/traces/{trace_id}"
        if record.exc_info:
            item["exception"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(item, ensure_ascii=False, default=str)


def _trace_id_atual() -> str | None:
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001
        pass
    return None


def configurar_logs() -> None:
    raiz = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, FormatoJson) for h in raiz.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("ZERA_LOG_JSON", "1") == "1":
        handler.setFormatter(FormatoJson())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz.handlers = [handler]
    raiz.setLevel(getattr(logging, os.getenv("ZERA_LOG_LEVEL", "INFO").upper(), logging.INFO))
    for barulhento in ("httpx", "httpcore", "google_genai", "google_adk", "urllib3", "uvicorn.access"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)


# ======================================================================
# OpenTelemetry (ADK + spans próprios)
# ======================================================================

_tracer = None
_otel_ativo = False


def configurar_otel() -> dict:
    """Liga a exportação OTel. ZERA_OTEL_GCP=1 -> telemetry.googleapis.com (Trace/Monitoring/Logging);
    OTEL_EXPORTER_OTLP_ENDPOINT -> coletor genérico. Sem nenhum dos dois, os spans existem só em processo."""
    global _tracer, _otel_ativo
    info = {"gcp": False, "otlp": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")), "erro": None}
    try:
        from opentelemetry import trace

        os.environ.setdefault("OTEL_SERVICE_NAME", SERVICO)
        os.environ.setdefault("OTEL_RESOURCE_ATTRIBUTES", f"service.version={VERSAO},deployment.environment={os.getenv('ZERA_AMBIENTE', 'demo')}")
        from google.adk.telemetry.setup import maybe_set_otel_providers

        hooks = []
        if os.getenv("ZERA_OTEL_GCP") == "1":
            from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource

            hooks.append(get_gcp_exporters(enable_cloud_tracing=True, enable_cloud_metrics=True,
                                           enable_cloud_logging=os.getenv("ZERA_OTEL_GCP_LOGS", "0") == "1"))
            maybe_set_otel_providers(hooks, get_gcp_resource())
            info["gcp"] = True
        elif info["otlp"]:
            maybe_set_otel_providers(hooks)
        _tracer = trace.get_tracer("zera", VERSAO)
        _otel_ativo = info["gcp"] or info["otlp"]
    except Exception as e:  # noqa: BLE001 — telemetria nunca derruba o serviço
        info["erro"] = str(e)[:200]
        log.warning("OTel não configurado: %s", e)
    return info


@contextmanager
def medir(nome: str, atributos: dict[str, Any] | None = None) -> Iterator[dict]:
    """Span + histograma de latência + log estruturado para uma etapa (motor, experiência, tool, HTTP)."""
    atributos = {k: str(v) for k, v in (atributos or {}).items()}
    inicio = time.perf_counter()
    resultado: dict[str, Any] = {"ok": True}
    span_cm = _tracer.start_as_current_span(nome) if _tracer else None
    span = span_cm.__enter__() if span_cm else None
    try:
        if span:
            for k, v in atributos.items():
                span.set_attribute(f"zera.{k}", v)
        yield resultado
    except Exception as e:
        resultado["ok"] = False
        if span:
            span.record_exception(e)
        raise
    finally:
        dur = (time.perf_counter() - inicio) * 1000
        if span_cm:
            span_cm.__exit__(None, None, None)
        registrar_metrica(f"{nome}.latencia_ms", dur, {**atributos, "ok": str(resultado["ok"])})


# ======================================================================
# Métricas em memória (+ OTel + logs + BigQuery)
# ======================================================================

class _Serie:
    __slots__ = ("count", "soma", "minimo", "maximo", "amostras")

    def __init__(self):
        self.count, self.soma, self.minimo, self.maximo = 0, 0.0, None, None
        self.amostras: deque[float] = deque(maxlen=2000)

    def add(self, v: float) -> None:
        self.count += 1
        self.soma += v
        self.minimo = v if self.minimo is None else min(self.minimo, v)
        self.maximo = v if self.maximo is None else max(self.maximo, v)
        self.amostras.append(v)

    def resumo(self) -> dict:
        a = sorted(self.amostras)
        pct = (lambda p: a[min(len(a) - 1, int(round((len(a) - 1) * p)))]) if a else (lambda p: None)
        return {"count": self.count, "soma": round(self.soma, 4), "media": round(self.soma / self.count, 4) if self.count else None,
                "min": self.minimo, "max": self.maximo, "p50": pct(0.5), "p95": pct(0.95)}


_series: dict[str, _Serie] = defaultdict(_Serie)
_por_atributo: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_lock = threading.Lock()
_instrumentos: dict[str, Any] = {}
_fila_bq: list[dict] = []


def registrar_metrica(nome: str, valor: float, atributos: dict[str, Any] | None = None) -> None:
    atributos = {k: str(v) for k, v in (atributos or {}).items()}
    with _lock:
        _series[nome].add(float(valor))
        chave = ",".join(f"{k}={v}" for k, v in sorted(atributos.items()))
        if chave:
            _por_atributo[nome][chave] += 1
    # cada métrica vira linha de log só se ZERA_LOG_METRICAS=1 (custo de ingestão no Cloud Logging — FinOps);
    # os eventos de negócio (http, chamada_llm, transições) já são logados explicitamente.
    _metricas_log.log(logging.INFO if os.getenv("ZERA_LOG_METRICAS") == "1" else logging.DEBUG, "metrica",
                      extra={"zera": {"metrica": nome, "valor": round(float(valor), 4), **atributos}})
    _otel_metrica(nome, valor, atributos)
    _enfileirar_bq({"tipo": "metrica", "nome": nome, "valor": float(valor), "atributos": atributos})


def _otel_metrica(nome: str, valor: float, atributos: dict[str, str]) -> None:
    if not _otel_ativo:
        return
    try:
        from opentelemetry import metrics

        inst = _instrumentos.get(nome)
        if inst is None:
            meter = metrics.get_meter("zera", VERSAO)
            inst = meter.create_histogram(nome, unit="ms") if nome.endswith("_ms") else meter.create_counter(nome)
            _instrumentos[nome] = inst
        if nome.endswith("_ms"):
            inst.record(valor, attributes=atributos)
        else:
            inst.add(valor, attributes=atributos)
    except Exception:  # noqa: BLE001
        pass


# ======================================================================
# FinOps: tokens e custo por chamada / por jornada
# ======================================================================

_custos_jornada: dict[str, dict[str, float]] = defaultdict(lambda: {"chamadas": 0, "tokens_entrada": 0, "tokens_saida": 0, "tokens_cache": 0, "tokens_pensamento": 0, "custo_usd": 0.0})


def custo_usd(entrada: int, saida: int, cache: int = 0, pensamento: int = 0) -> float:
    return round((max(entrada - cache, 0) * PRECO_ENTRADA + cache * PRECO_CACHE + saida * PRECO_SAIDA + pensamento * PRECO_PENSAMENTO) / 1e6, 6)


def registrar_llm(usage: Any, modelo: str, jornada_id: str | None, onde: str, latencia_ms: float | None = None) -> dict:
    """Recebe `event.usage_metadata` do ADK (GenerateContentResponseUsageMetadata) e contabiliza tokens e custo."""
    g = lambda k: int(getattr(usage, k, 0) or 0) if usage is not None else 0  # noqa: E731
    entrada, saida = g("prompt_token_count"), g("candidates_token_count")
    cache, pensamento = g("cached_content_token_count"), g("thoughts_token_count")
    custo = custo_usd(entrada, saida, cache, pensamento)
    j = _custos_jornada[jornada_id or "sem_jornada"]
    j["chamadas"] += 1
    j["tokens_entrada"] += entrada
    j["tokens_saida"] += saida
    j["tokens_cache"] += cache
    j["tokens_pensamento"] += pensamento
    j["custo_usd"] = round(j["custo_usd"] + custo, 6)
    registrar_metrica("zera.llm.chamadas", 1, {"modelo": modelo, "onde": onde})
    registrar_metrica("zera.llm.tokens_entrada", entrada, {"modelo": modelo})
    registrar_metrica("zera.llm.tokens_saida", saida, {"modelo": modelo})
    registrar_metrica("zera.llm.custo_usd", custo, {"modelo": modelo, "onde": onde})
    if latencia_ms is not None:
        registrar_metrica("zera.llm.latencia_ms", latencia_ms, {"modelo": modelo, "onde": onde})
    item = {"modelo": modelo, "onde": onde, "jornada_id": jornada_id, "tokens_entrada": entrada, "tokens_saida": saida,
            "tokens_cache": cache, "tokens_pensamento": pensamento, "custo_usd": custo, "latencia_ms": latencia_ms}
    log.info("chamada_llm", extra={"zera": item})
    _enfileirar_bq({"tipo": "llm", "nome": onde, "valor": custo, "atributos": {k: str(v) for k, v in item.items()}})
    return item


def custo_da_jornada(jornada_id: str | None) -> dict:
    return dict(_custos_jornada.get(jornada_id or "", {"chamadas": 0, "tokens_entrada": 0, "tokens_saida": 0, "custo_usd": 0.0}))


# ======================================================================
# BigQuery `zera.telemetria` (best-effort, em lote)
# ======================================================================

def _enfileirar_bq(item: dict) -> None:
    if os.getenv("ZERA_TELEMETRIA_BQ") != "1":
        return
    with _lock:
        _fila_bq.append({"timestamp": datetime.now(timezone.utc).isoformat(), "servico": SERVICO, "versao": VERSAO,
                         "tipo": item["tipo"], "nome": item["nome"], "valor": item["valor"],
                         "atributos": json.dumps(item["atributos"], ensure_ascii=False)})
        if len(_fila_bq) >= int(os.getenv("ZERA_TELEMETRIA_LOTE", "50")):
            lote, _fila_bq[:] = list(_fila_bq), []
            threading.Thread(target=_gravar_bq, args=(lote,), daemon=True).start()


def _gravar_bq(lote: list[dict]) -> None:
    try:
        from google.cloud import bigquery

        projeto = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
        dataset = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")
        erros = bigquery.Client(project=projeto).insert_rows_json(f"{projeto}.{dataset}.telemetria", lote)
        if erros:
            log.warning("telemetria BigQuery com erros: %s", str(erros)[:300])
    except Exception as e:  # noqa: BLE001
        log.warning("telemetria BigQuery indisponível: %s", str(e)[:200])


def descarregar_bq() -> None:
    with _lock:
        lote, _fila_bq[:] = list(_fila_bq), []
    if lote:
        _gravar_bq(lote)


# ======================================================================
# Resumo para /metrics
# ======================================================================

def resumo() -> dict:
    with _lock:
        series = {n: s.resumo() for n, s in _series.items()}
        por_attr = {n: dict(v) for n, v in _por_atributo.items()}
    llm_custo = series.get("zera.llm.custo_usd", {}).get("soma", 0.0) or 0.0
    acordos = series.get("zera.acordo_fechado", {}).get("count", 0)
    jornadas = {k: v for k, v in _custos_jornada.items()}
    return {
        "servico": SERVICO, "versao": VERSAO, "uptime_s": round(time.time() - _INICIO, 1), "otel_ativo": _otel_ativo,
        "precos_usd_1m": {"entrada": PRECO_ENTRADA, "saida": PRECO_SAIDA, "cache": PRECO_CACHE},
        "finops": {"custo_llm_total_usd": round(llm_custo, 6), "chamadas_llm": series.get("zera.llm.chamadas", {}).get("count", 0),
                   "tokens_entrada": series.get("zera.llm.tokens_entrada", {}).get("soma", 0), "tokens_saida": series.get("zera.llm.tokens_saida", {}).get("soma", 0),
                   "acordos_fechados": acordos, "custo_medio_por_acordo_usd": round(llm_custo / acordos, 6) if acordos else None,
                   "jornadas": len(jornadas), "custo_medio_por_jornada_usd": round(sum(j["custo_usd"] for j in jornadas.values()) / len(jornadas), 6) if jornadas else None},
        "metricas": series, "por_atributo": por_attr,
    }


def reiniciar() -> None:
    with _lock:
        _series.clear()
        _por_atributo.clear()
        _custos_jornada.clear()
        _fila_bq.clear()
