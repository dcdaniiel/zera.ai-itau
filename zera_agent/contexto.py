"""Estado do cliente + relógio de simulação (P0: JSON local; P1: BigQuery append-only — Firestore não está liberado).

O agente nunca toca o extrato bruto: ele só vê o que as tools devolvem a partir deste contexto.
"""

from __future__ import annotations

import json
import logging
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
from motor.modelos import Divida, PerfilFinanceiro

log = logging.getLogger("zera.contexto")
RAIZ = Path(__file__).resolve().parent.parent
HOJE_INICIAL = os.getenv("ZERA_HOJE", "2026-09-26")


def pasta_estado() -> Path:
    return Path(os.getenv("ZERA_ESTADO_DIR", RAIZ / ".zera_state"))

# Roteiro da demo: eventos que o "avançar tempo" injeta (dinheiro extra etc.)
ROTEIRO_DEMO: list[dict] = [
    # O gatilho que abre a jornada no dia da demo é a ENTRADA NO ROTATIVO (detectada no extrato/cadastro — quadro item 11).
    # Os eventos abaixo entram quando o relógio avança: dinheiro extra vira entrada/amortização.
    {"a_partir_de": "2026-12-05", "tipo": "credito", "valor": 2800.00, "descricao": "PIX RECEBIDO - 13 SALARIO / RENDA EXTRA", "recorrente": False},
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


class RepositorioResiliente:
    """BigQuery primeiro; se o runtime não tiver permissão (403 em jobs/insert) ou credencial, cai para JSON local e avisa
    uma vez — a conversa nunca quebra por causa do repositório de estado."""

    def __init__(self, primario, reserva):
        self.primario, self.reserva, self.caiu = primario, reserva, False

    def _tentar(self, nome, *args):
        if not self.caiu:
            try:
                return getattr(self.primario, nome)(*args)
            except Exception as e:  # noqa: BLE001
                self.caiu = True
                log.warning("estado no BigQuery indisponível em runtime (%s): usando JSON local (%s)", str(e)[:160], self.reserva.pasta)
        return getattr(self.reserva, nome)(*args)

    def ler(self, cliente_id):
        return self._tentar("ler", cliente_id)

    def gravar(self, cliente_id, estado):
        return self._tentar("gravar", cliente_id, estado)

    def apagar(self, cliente_id):
        return self._tentar("apagar", cliente_id)

    def gravar_evento(self, cliente_id, tipo, payload, data_simulada):
        if self.caiu:
            return None
        try:
            return self.primario.gravar_evento(cliente_id, tipo, payload, data_simulada)
        except Exception as e:  # noqa: BLE001
            self.caiu = True
            log.warning("eventos no BigQuery indisponíveis (%s): estado segue em JSON local", str(e)[:160])
            return None


def repositorio():
    if os.getenv("ZERA_ESTADO", "json") == "bigquery":
        try:
            return RepositorioResiliente(RepositorioBigQuery(), RepositorioJson())
        except Exception as e:  # noqa: BLE001 — sem biblioteca/credencial: JSON
            log.warning("RepositorioBigQuery indisponível (%s): usando JSON", str(e)[:160])
    return RepositorioJson()


# ---------- contexto ----------

class Contexto:
    """Tudo que o Zera sabe sobre um cliente: perfil (derivado do extrato), acordo, consentimentos, gatilhos, memória."""

    _cache: dict[str, "Contexto"] = {}

    def __init__(self, cliente_id: str):
        self.cliente_id = cliente_id
        self.repo = repositorio()
        self.politica = carregar_politica()
        self.perfil, self._df = carregar_perfil(cliente_id)
        self._renda_base = list(self.perfil.renda_mensal)
        self._compromissos_base = list(self.perfil.compromissos_mensal)
        self._dividas_base = list(self.perfil.dividas)
        self.capacidade = calcular_capacidade(self.perfil, self.politica)
        self.estado: dict[str, Any] = self.repo.ler(cliente_id) or self._estado_inicial()
        self.estado.setdefault("compromissos_extras", [])
        self.estado.setdefault("memoria", {})
        self.estado.setdefault("acordos", [self.estado["acordo"]] if self.estado.get("acordo") else [])
        self._aplicar_renda_informada()
        self._aplicar_acordos()

    @classmethod
    def para(cls, cliente_id: str) -> "Contexto":
        if cliente_id not in cls._cache:
            cls._cache[cliente_id] = cls(cliente_id)
        return cls._cache[cliente_id]

    @classmethod
    def limpar_cache(cls) -> None:
        cls._cache.clear()

    def _estado_inicial(self) -> dict:
        hoje = date.fromisoformat(HOJE_INICIAL)
        creditos = [{k: v for k, v in ev.items() if k != "a_partir_de"} for ev in ROTEIRO_DEMO
                    if date.fromisoformat(ev["a_partir_de"]) <= hoje]
        gatilhos = detectar_gatilhos(self.perfil, None, hoje, creditos_recentes=creditos, politica=self.politica)
        return {
            "hoje": HOJE_INICIAL,
            "acordo": None,       # acordo mais recente (compatibilidade); todos ficam em "acordos"
            "acordos": [],        # pode haver mais de uma opção contratada (ex.: uma dívida agora, outra depois)
            "consentimentos": [],
            "gatilhos_pendentes": gatilhos,
            "eventos": [],
            "creditos_recentes": creditos,
            "sobra_prevista_mes": None,
            "memoria": {"dia_pagamento_preferido": self.perfil.dia_pagamento_preferido, "canal": "app"},
            "escalonamentos": [],
            "compromissos_extras": [],   # gastos importantes informados pelo cliente que não aparecem no extrato
        }

    # --- informações confirmadas pela cliente (quadro de produto, item 14: dados internos + o que ela confirma) ---
    def adicionar_compromisso(self, descricao: str, valor_mensal: float) -> dict:
        """Tela "Vamos considerar esse gasto": gasto fixo fora do extrato -> reduz a sobra e recalcula a capacidade."""
        item = {"descricao": descricao, "valor_mensal": round(float(valor_mensal), 2), "data": self.estado["hoje"]}
        self.estado.setdefault("compromissos_extras", []).append(item)
        self._aplicar_compromissos()
        self.salvar()
        self.registrar_evento("compromisso_informado", item)
        return item

    def remover_compromissos(self) -> None:
        self.estado["compromissos_extras"] = []
        self._aplicar_compromissos()
        self.salvar()
        self.registrar_evento("compromissos_removidos", {})

    def informar_renda(self, valor_mensal: float) -> None:
        """Extrato sem entradas de renda (dados insuficientes): a cliente informa um valor aproximado, uma vez."""
        self.estado.setdefault("memoria", {})["renda_informada"] = round(float(valor_mensal), 2)
        self._aplicar_renda_informada()
        self._aplicar_compromissos()
        self.salvar()
        self.registrar_evento("renda_informada", {"valor": round(float(valor_mensal), 2)})

    def _aplicar_renda_informada(self) -> None:
        base = getattr(self, "_renda_base", None)
        if base is None:
            self._renda_base = list(self.perfil.renda_mensal)
            base = self._renda_base
        valor = (self.estado.get("memoria") or {}).get("renda_informada")
        if valor and (not any(base) or self.perfil.renda_informada is not None):
            self.perfil.renda_informada = float(valor)
            self.perfil.renda_mensal = [float(valor)] * len(self.perfil.meses)
        else:
            self.perfil.renda_mensal = list(base)

    def _aplicar_compromissos(self) -> None:
        """Compromissos extras e parcelas dos acordos ativos entram em todos os meses e reduzem a sobra; a capacidade é recalculada."""
        extra = round(sum(c["valor_mensal"] for c in self.estado.get("compromissos_extras", []))
                      + sum(a.parcela for a in self.acordos if a.status == "ativo"), 2)
        base = getattr(self, "_compromissos_base", None)
        if base is None:
            self._compromissos_base = list(self.perfil.compromissos_mensal)
            base = self._compromissos_base
        self.perfil.compromissos_mensal = [round(b + extra, 2) for b in base]
        self.capacidade = calcular_capacidade(self.perfil, self.politica)

    def _aplicar_acordos(self) -> None:
        """Mais de uma opção contratada: dívidas já quitadas ou renegociadas em acordo ativo saem do perfil (não entram em
        novos cenários) e as parcelas contratadas viram compromisso fixo — a próxima jornada calcula só o que sobrou."""
        base = getattr(self, "_dividas_base", None)
        if base is None:
            self._dividas_base = list(self.perfil.dividas)
            base = self._dividas_base
        cobertas: set[str] = set()
        for a in self.acordos:
            cobertas.update(q["divida_id"] for q in a.quitacoes)
            if a.status == "ativo":
                cobertas.update(c["divida_id"] for c in a.componentes_ativos)
        self.perfil.dividas = [d for d in base if d.divida_id not in cobertas]
        self._aplicar_compromissos()

    # --- propriedades ---
    @property
    def hoje(self) -> date:
        return date.fromisoformat(self.estado["hoje"])

    @property
    def acordos(self) -> list[Acordo]:
        return [Acordo(**a) for a in (self.estado.get("acordos") or []) if a]

    @property
    def acordo(self) -> Acordo | None:
        """Acordo ativo mais recente (as tools de respiro/amortização atuam sobre ele)."""
        ativos = [a for a in self.acordos if a.status == "ativo"]
        if ativos:
            return ativos[-1]
        a = self.estado.get("acordo")
        return Acordo(**a) if a else None

    @property
    def dividas_em_acordo(self) -> list[Divida]:
        atuais = {d.divida_id for d in self.perfil.dividas}
        return [d for d in getattr(self, "_dividas_base", []) if d.divida_id not in atuais]

    def salvar(self, acordo: Acordo | None = None) -> None:
        if acordo is not None:
            registro = asdict(acordo)
            acordos = [a for a in (self.estado.get("acordos") or []) if a and a.get("acordo_id") != acordo.acordo_id]
            acordos.append(registro)
            self.estado["acordos"] = acordos
            ativos = [a for a in acordos if a.get("status") == "ativo"]
            self.estado["acordo"] = ativos[-1] if ativos else registro
            self._aplicar_acordos()
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
        self.perfil.renda_informada = None
        self._aplicar_renda_informada()
        self._aplicar_acordos()
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
        eventos_pagos: list[dict] = []
        for acordo in self.acordos:
            if acordo.status == "ativo":
                eventos_pagos += processar_vencimentos(acordo, ate)
                self.salvar(acordo)
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
                "acordo": self.estado.get("acordo"), "acordos": self.estado.get("acordos", [])}

    def consumir_gatilhos(self) -> list[dict]:
        g = self.estado.get("gatilhos_pendentes", [])
        self.estado["gatilhos_pendentes"] = []
        self.salvar()
        return g
