"""Estado do cliente + relógio de simulação (P0: JSON local; P1: BigQuery append-only — Firestore não está liberado).

O agente nunca toca o extrato bruto: ele só vê o que as tools devolvem a partir deste contexto.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from dados.loader import carregar_perfil
from motor import (
    Acordo,
    calcular_capacidade,
    carregar_politica,
    detectar_gatilhos,
    processar_vencimentos,
)
from motor.modelos import PerfilFinanceiro

RAIZ = Path(__file__).resolve().parent.parent
HOJE_INICIAL = os.getenv("ZERA_HOJE", "2026-09-26")


def pasta_estado() -> Path:
    return Path(os.getenv("ZERA_ESTADO_DIR", RAIZ / ".zera_state"))

# Roteiro da demo: eventos que o "avançar tempo" injeta (dinheiro extra etc.)
ROTEIRO_DEMO: list[dict] = [
    {"a_partir_de": "2027-05-01", "tipo": "credito", "valor": 1400.00, "descricao": "RESTITUICAO IRPF", "recorrente": False},
]


# ---------- persistência ----------

class RepositorioJson:
    def __init__(self, pasta: Path | None = None):
        self.pasta = pasta or pasta_estado()
        self.pasta.mkdir(parents=True, exist_ok=True)

    def ler(self, cliente_id: str) -> dict | None:
        p = self.pasta / f"{cliente_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def gravar(self, cliente_id: str, estado: dict) -> None:
        (self.pasta / f"{cliente_id}.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

    def apagar(self, cliente_id: str) -> None:
        p = self.pasta / f"{cliente_id}.json"
        if p.exists():
            p.unlink()


class RepositorioBigQuery:
    """Estado do cliente em BigQuery, append-only (Firestore não está liberado no projeto do evento).

    Tabela `zera.estado_cliente`: um snapshot JSON por gravação; leitura = último snapshot do cliente.
    "Apagar" (LGPD) grava um snapshot com apagado=true. Eventos vão para `zera.eventos` (streaming insert).
    """

    def __init__(self):
        from google.cloud import bigquery  # import tardio

        self.bq = bigquery
        self.projeto = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
        self.dataset = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")
        self.client = bigquery.Client(project=self.projeto)
        self.t_estado = f"{self.projeto}.{self.dataset}.estado_cliente"
        self.t_eventos = f"{self.projeto}.{self.dataset}.eventos"

    def ler(self, cliente_id: str) -> dict | None:
        sql = f"SELECT apagado, estado FROM `{self.t_estado}` WHERE cliente_id = @id ORDER BY gravado_em DESC LIMIT 1"
        job = self.client.query(sql, job_config=self.bq.QueryJobConfig(
            query_parameters=[self.bq.ScalarQueryParameter("id", "STRING", cliente_id)]))
        for row in job.result():
            return None if row["apagado"] else json.loads(row["estado"])
        return None

    def gravar(self, cliente_id: str, estado: dict) -> None:
        self._inserir(self.t_estado, [{"cliente_id": cliente_id, "gravado_em": _agora(), "apagado": False,
                                       "estado": json.dumps(estado, ensure_ascii=False, default=str)}])

    def apagar(self, cliente_id: str) -> None:
        self._inserir(self.t_estado, [{"cliente_id": cliente_id, "gravado_em": _agora(), "apagado": True, "estado": "{}"}])

    def gravar_evento(self, cliente_id: str, tipo: str, payload: dict, data_simulada: str) -> None:
        self._inserir(self.t_eventos, [{"evento_id": uuid4().hex, "cliente_id": cliente_id, "sessao_id": os.getenv("ZERA_SESSAO", "demo"),
                                        "tipo": tipo, "payload": json.dumps(payload, ensure_ascii=False, default=str),
                                        "variante_experimento": os.getenv("ZERA_VARIANTE", "A"),
                                        "data_simulada": data_simulada, "timestamp": _agora()}])

    def _inserir(self, tabela: str, linhas: list[dict]) -> None:
        erros = self.client.insert_rows_json(tabela, linhas)
        if erros:
            raise RuntimeError(f"BigQuery insert falhou: {erros}")


def _agora() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def repositorio():
    return RepositorioBigQuery() if os.getenv("ZERA_ESTADO", "json") == "bigquery" else RepositorioJson()


# ---------- contexto ----------

class Contexto:
    """Tudo que o Zera sabe sobre um cliente: perfil (derivado do extrato), acordo, consentimentos, gatilhos, memória."""

    _cache: dict[str, "Contexto"] = {}

    def __init__(self, cliente_id: str):
        self.cliente_id = cliente_id
        self.repo = repositorio()
        self.politica = carregar_politica()
        self.perfil, self._df = carregar_perfil(cliente_id)
        self.capacidade = calcular_capacidade(self.perfil, self.politica)
        self.estado: dict[str, Any] = self.repo.ler(cliente_id) or self._estado_inicial()

    @classmethod
    def para(cls, cliente_id: str) -> "Contexto":
        if cliente_id not in cls._cache:
            cls._cache[cliente_id] = cls(cliente_id)
        return cls._cache[cliente_id]

    @classmethod
    def limpar_cache(cls) -> None:
        cls._cache.clear()

    def _estado_inicial(self) -> dict:
        return {
            "hoje": HOJE_INICIAL,
            "acordo": None,
            "consentimentos": [],
            "gatilhos_pendentes": [],
            "eventos": [],
            "creditos_recentes": [],
            "sobra_prevista_mes": None,
            "memoria": {"dia_pagamento_preferido": self.perfil.dia_pagamento_preferido, "canal": "app"},
            "escalonamentos": [],
        }

    # --- propriedades ---
    @property
    def hoje(self) -> date:
        return date.fromisoformat(self.estado["hoje"])

    @property
    def acordo(self) -> Acordo | None:
        a = self.estado.get("acordo")
        return Acordo(**a) if a else None

    def salvar(self, acordo: Acordo | None = None) -> None:
        if acordo is not None:
            self.estado["acordo"] = asdict(acordo)
        self.repo.gravar(self.cliente_id, self.estado)

    def registrar_evento(self, tipo: str, payload: dict | None = None) -> None:
        self.estado["eventos"].append({"data": self.estado["hoje"], "tipo": tipo, "payload": payload or {}})
        self.estado["eventos"] = self.estado["eventos"][-200:]
        self.salvar()
        gravar_evento = getattr(self.repo, "gravar_evento", None)
        if gravar_evento:
            try:
                gravar_evento(self.cliente_id, tipo, payload or {}, self.estado["hoje"])
            except Exception:  # métrica é best-effort; nunca derruba a conversa
                pass

    def resetar(self) -> None:
        self.repo.apagar(self.cliente_id)
        self.estado = self._estado_inicial()
        self.salvar()

    # --- relógio de simulação ---
    def sobra_prevista(self, quando: date) -> float:
        """Previsão simples: sobra do mesmo mês do ano anterior (sazonalidade)."""
        alvo = f"{quando.year - 1}-{quando.month:02d}"
        for m, s in zip(self.perfil.meses, self.perfil.sobra_mensal):
            if m == alvo:
                return s
        return self.capacidade.sobra_mediana

    def avancar_tempo(self, ate: date) -> dict:
        """Avança o relógio: paga vencimentos vencidos, injeta eventos do roteiro e detecta gatilhos."""
        if ate < self.hoje:
            raise ValueError("não dá para voltar no tempo")
        acordo = self.acordo
        eventos_pagos: list[dict] = []
        if acordo is not None:
            eventos_pagos = processar_vencimentos(acordo, ate)
            self.estado["acordo"] = asdict(acordo)
        creditos = []
        ja = {c["descricao"] for c in self.estado.get("creditos_recentes", [])}
        for ev in ROTEIRO_DEMO:
            if date.fromisoformat(ev["a_partir_de"]) <= ate and ev["descricao"] not in ja:
                creditos.append({k: v for k, v in ev.items() if k != "a_partir_de"})
        self.estado["creditos_recentes"] = creditos
        self.estado["hoje"] = ate.isoformat()
        self.estado["sobra_prevista_mes"] = self.sobra_prevista(ate)
        gatilhos = detectar_gatilhos(self.perfil, self.acordo, ate,
                                     sobra_prevista_mes=self.estado["sobra_prevista_mes"],
                                     creditos_recentes=creditos, politica=self.politica)
        self.estado["gatilhos_pendentes"] = gatilhos
        self.salvar()
        self.registrar_evento("tempo_avancado", {"ate": ate.isoformat(), "gatilhos": [g["tipo"] for g in gatilhos]})
        return {"hoje": ate.isoformat(), "pagamentos_processados": eventos_pagos, "gatilhos": gatilhos,
                "acordo": self.estado.get("acordo")}

    def consumir_gatilhos(self) -> list[dict]:
        g = self.estado.get("gatilhos_pendentes", [])
        self.estado["gatilhos_pendentes"] = []
        self.salvar()
        return g
