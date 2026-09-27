"""Carrega o perfil financeiro do cliente (BigQuery ou CSV local) no schema canônico do motor.

Fontes (env ZERA_FONTE):
    bigquery  -> `zera.perfil_cliente` (12 meses em arrays) + `zera.dividas_derivadas` + `zera.clusters_clientes` (segmento).
                 1 query por sessão. Fallback: extrato bruto `zera.extrato` (ou hackathon_dados.extrato_sintetico) + derivar_dividas().
                 Perfis disponíveis: `zera.perfis_demo` = clientes reais do cluster-alvo (BigQuery ML k-means), o mais típico
                 (medoide) recebe o nome da persona do quadro de produto.
    amostra   -> dados/amostra_bq_extrato_sintetico.csv (export real da base do evento, 10k lançamentos) + segmentação por
                 regras (dados/segmentacao.py). Para rodar local sem credenciais. Nenhum dado sintético.
    fixture   -> tests/fixtures/ (perfil sintético usado SOMENTE pelos testes automatizados).

Nada é inventado: quando o extrato não traz renda, o perfil sai com `renda_desconhecida=True` e a experiência
pergunta antes de calcular (dados insuficientes — quadro de produto, item 13). Dívidas derivadas do extrato são
rotuladas `fonte=derivada_extrato` e a interface mostra "estimado do extrato".
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import pandas as pd

from motor.modelos import Divida, PerfilFinanceiro, r2

log = logging.getLogger("zera.dados")

AQUI = Path(__file__).parent
FIXTURES = AQUI.parent / "tests" / "fixtures"
AMOSTRA = AQUI / "amostra_bq_extrato_sintetico.csv"
MAX_PERFIS = int(os.getenv("ZERA_MAX_PERFIS", "12"))

PROJETO = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
DATASET = os.getenv("ZERA_BQ_DATASET", "hackathon_dados")
TABELA = os.getenv("ZERA_BQ_TABELA", "extrato_sintetico")
DATASET_ZERA = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")

# taxas fictícias usadas quando a dívida é derivada do extrato (sem cadastro de dívidas na base do evento)
TAXAS_DERIVADAS = {"cheque_especial": 0.08, "cartao_rotativo": 0.14, "emprestimo": 0.045, "crediario": 0.0}

# Schema real de `hackathon_dados.extrato_sintetico`: coluna canônica -> coluna da tabela
MAPEAMENTO_COLUNAS = {
    "cliente_id": "id_usuario", "data": "anomesdia", "descricao": "descr", "valor": "vlr", "tipo": "tipo",
    "categoria": "nom_cate_macro", "subcategoria": "nom_cate_micro", "saldo_apos": "saldo_apos",
    "parcela_atual": "parcela_atual", "parcela_total": "parcela_total",
}
CATEGORIAS_ESSENCIAIS = {"moradia", "aluguel", "contas", "energia", "agua", "gas", "alimentacao", "mercado", "supermercado",
                         "transporte", "telefone", "saude", "farmacia", "educacao",
                         "casa", "transporte publico", "posto de combustivel", "contas e servicos"}
MICRO_NAO_ESSENCIAIS = {"jardinagem", "lavanderia"}
PADRAO_RENDA = re.compile(r"(?:SALARIO|SAL[ÁA]RIO|PIX RECEBIDO|TED RECEBIDA|PAGAMENTO RECEBIDO|DIARIA|PROVENTO)", re.I)
PADRAO_NAO_RENDA = re.compile(r"(?:ESTORNO|REEMBOLSO|CANCELAMENTO|DEVOLU)", re.I)
PADRAO_DIVIDA = re.compile(r"(?:JUROS|PARCELA|FATURA|EMPRESTIMO|EMPR[ÉE]STIMO|MINIMO|M[ÍI]NIMO|ROTATIVO|CHEQUE ESPECIAL)", re.I)
CAMPOS_DIVIDA = set(Divida.__dataclass_fields__)


SNAPSHOT = Path(__file__).parent / "snapshot_bq"
_snapshot_ativo: dict | None = None      # meta do snapshot quando ele está sendo usado (fallback ou modo explícito)
_snapshot_motivo = ""


def fonte() -> str:
    f = os.getenv("ZERA_FONTE", "amostra")
    return "amostra" if f == "csv" else f


def fonte_efetiva() -> str:
    """O que a API mostra em /health e nos cards: 'bigquery', 'bigquery_snapshot (<hora>)', 'amostra' ou 'fixture'."""
    if _snapshot_ativo:
        return f"bigquery_snapshot ({_snapshot_ativo.get('gerado_em', '')})"
    return fonte()


def _snapshot_disponivel() -> bool:
    return (SNAPSHOT / "meta.json").exists() and (SNAPSHOT / "perfis_demo.json").exists()


def _ler_snapshot(nome: str):
    return json.loads((SNAPSHOT / f"{nome}.json").read_text(encoding="utf-8"))


def _usar_snapshot(motivo: str) -> None:
    """Liga o snapshot (resultado do BigQuery ML exportado no deploy com a credencial de quem publicou)."""
    global _snapshot_ativo, _snapshot_motivo
    if _snapshot_ativo is None:
        _snapshot_ativo = _ler_snapshot("meta")
        _snapshot_motivo = motivo
        log.warning("BigQuery em runtime indisponível (%s): usando snapshot exportado em %s (%d perfis do cluster-alvo)",
                    motivo[:160], _snapshot_ativo.get("gerado_em"), _snapshot_ativo.get("perfis", 0))


def _bq_ou_snapshot(consulta, do_snapshot):
    """Executa a consulta no BigQuery; se o runtime não tiver permissão/credencial e houver snapshot, usa o snapshot."""
    if fonte() == "bigquery_snapshot" or _snapshot_ativo:
        if not _snapshot_disponivel():
            raise RuntimeError("ZERA_FONTE=bigquery_snapshot sem dados/snapshot_bq — rode `python -m dados.exportar_snapshot_bq`")
        _usar_snapshot("modo explícito" if fonte() == "bigquery_snapshot" else _snapshot_motivo)
        return do_snapshot()
    try:
        return consulta()
    except Exception as e:  # noqa: BLE001 — 403 (jobs.create), credencial ausente, dataset inexistente…
        if _snapshot_disponivel():
            _usar_snapshot(str(e))
            return do_snapshot()
        raise


# ---------- normalização ----------

def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={v: k for k, v in MAPEAMENTO_COLUNAS.items() if v in df.columns}).copy()
    df["data"] = pd.to_datetime(df["data"]).dt.date.astype(str)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").abs()
    if "tipo" not in df.columns:
        df["tipo"] = "debito"
    df["tipo"] = df["tipo"].astype(str).str.lower().map(lambda t: "credito" if t.startswith(("c", "e", "+")) else "debito")
    if "categoria" not in df.columns:
        df["categoria"] = "outros"
    df["categoria"] = df["categoria"].astype(str).str.lower().str.strip()
    if "descricao" not in df.columns:
        df["descricao"] = ""
    # toda entrada (tipo E) é renda — mesma regra de dados/sql/zera_tabelas.sql —, exceto estorno/reembolso
    renda_mask = (df["tipo"] == "credito") & ~df["descricao"].astype(str).str.contains(PADRAO_NAO_RENDA)
    df.loc[renda_mask, "categoria"] = "renda"
    divida_mask = (df["tipo"] == "debito") & (df["categoria"].isin({"divida", "dívida"}) | df["descricao"].astype(str).str.contains(PADRAO_DIVIDA))
    df.loc[divida_mask, "categoria"] = "divida"
    if "subcategoria" in df.columns:
        df["subcategoria"] = df["subcategoria"].astype(str).str.lower().str.strip()
    if "essencial" not in df.columns:
        df["essencial"] = (df["tipo"] == "debito") & df["categoria"].isin(CATEGORIAS_ESSENCIAIS)
        if "subcategoria" in df.columns:
            df.loc[df["subcategoria"].isin(MICRO_NAO_ESSENCIAIS), "essencial"] = False
    df["essencial"] = df["essencial"].astype(str).str.lower().isin({"true", "1", "sim", "yes"}) if df["essencial"].dtype == object else df["essencial"].astype(bool)
    if "recorrente" not in df.columns:
        df["recorrente"] = df["categoria"].isin({"renda"} | CATEGORIAS_ESSENCIAIS)
    df["mes"] = df["data"].str.slice(0, 7)
    return df


# ---------- fontes ----------

_cache_amostra: pd.DataFrame | None = None


def carregar_amostra() -> pd.DataFrame:
    """Export real de `hackathon_dados.extrato_sintetico` (mesmo schema da tabela), normalizado uma vez por processo."""
    global _cache_amostra
    if _cache_amostra is None:
        _cache_amostra = normalizar(pd.read_csv(AMOSTRA))
        meses, entradas = _cache_amostra["mes"].nunique(), int((_cache_amostra["tipo"] == "credito").sum())
        if entradas == 0 or meses < 3:
            log.warning("amostra %s cobre %d mês(es) e tem %d entrada(s): a renda ficará 'não identificada' e a zera.ai vai perguntar. "
                        "Gere uma amostra completa com dados/sql/exportar_amostra.sql.", AMOSTRA.name, meses, entradas)
    return _cache_amostra


def carregar_fixture() -> pd.DataFrame:
    return normalizar(pd.read_csv(FIXTURES / "persona_cleide_12m.csv"))


def _bq():
    from google.cloud import bigquery  # import tardio: só quando a fonte é BigQuery

    return bigquery, bigquery.Client(project=PROJETO)


def _query(sql: str, **params) -> list[dict]:
    bigquery, client = _bq()
    tipos = {str: "STRING", int: "INT64", float: "FLOAT64"}
    qp = [bigquery.ScalarQueryParameter(k, tipos[type(v)], v) for k, v in params.items()]
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=qp))
    return [dict(row) for row in job.result()]


def carregar_bigquery(cliente_id: str, meses: int = 12) -> pd.DataFrame:
    """Fallback: extrato bruto (clusterizado por id_usuario) — 1 query, sem depender de db-dtypes."""
    tabela = f"`{PROJETO}.{DATASET_ZERA}.extrato`"
    try:
        linhas = _query(f"""
            SELECT id_usuario, TIMESTAMP(dia) AS anomesdia, descr, vlr, tipo, macro AS nom_cate_macro, micro AS nom_cate_micro,
                   saldo_apos, parcela_atual, parcela_total
            FROM {tabela}
            WHERE id_usuario = @cliente_id
              AND dia >= DATE_SUB((SELECT MAX(dia) FROM {tabela} WHERE id_usuario = @cliente_id), INTERVAL @meses MONTH)
            ORDER BY dia""", cliente_id=cliente_id, meses=meses)
    except Exception:  # tabela unificada ainda não publicada: lê a do evento
        col = MAPEAMENTO_COLUNAS
        tabela = f"`{PROJETO}.{DATASET}.{TABELA}`"
        linhas = _query(f"""
            SELECT * FROM {tabela}
            WHERE {col['cliente_id']} = @cliente_id
              AND DATE({col['data']}) >= DATE_SUB((SELECT MAX(DATE({col['data']})) FROM {tabela} WHERE {col['cliente_id']} = @cliente_id), INTERVAL @meses MONTH)
            ORDER BY {col['data']}""", cliente_id=cliente_id, meses=meses)
    if not linhas:
        raise LookupError(f"cliente {cliente_id} não encontrado no BigQuery")
    return normalizar(pd.DataFrame(linhas))


def carregar_bigquery_agregado(cliente_id: str) -> dict | None:
    """Caminho rápido: 1 query em `zera.perfil_cliente` + dívidas derivadas + nome/ordem em perfis_demo + cluster."""
    z = f"{PROJETO}.{DATASET_ZERA}"
    linhas = _query(f"""
        SELECT p.meses, p.renda_mensal, p.essenciais_mensal, p.parcelas_mensal, p.renda_conhecida, p.cv_renda, p.meses_no_vermelho,
               (SELECT AS STRUCT k.cluster, k.distancia FROM `{z}.clusters_clientes` k WHERE k.id_usuario = p.id_usuario) AS segmento,
               (SELECT AS STRUCT d.nome, d.ordem, d.medoide FROM `{z}.perfis_demo` d WHERE d.id_usuario = p.id_usuario) AS demo,
               ARRAY(SELECT AS STRUCT divida_id, produto, saldo, taxa_mensal, dias_atraso, parcela_atual, parcelas_restantes, consequencia,
                            descricao, instituicao, fonte
                     FROM `{z}.dividas_derivadas` d WHERE d.id_usuario = p.id_usuario) AS derivadas
        FROM `{z}.perfil_cliente` p
        WHERE p.id_usuario = @cliente_id""", cliente_id=cliente_id)
    if not linhas:
        return None
    row = linhas[0]
    demo = dict(row["demo"]) if row.get("demo") else {}
    return {"meses": list(row["meses"]), "renda_mensal": [float(x or 0) for x in row["renda_mensal"]],
            "essenciais_mensal": [float(x or 0) for x in row["essenciais_mensal"]],
            "parcelas_mensal": [float(x or 0) for x in row["parcelas_mensal"]], "renda_conhecida": bool(row.get("renda_conhecida")),
            "nome": demo.get("nome"), "medoide": bool(demo.get("medoide")), "segmento": dict(row["segmento"]) if row.get("segmento") else None,
            "dividas": [dict(d) for d in (row.get("derivadas") or [])]}


def listar_clientes() -> list[dict]:
    """Perfis disponíveis para a demo: clientes REAIS do segmento-alvo. bigquery: `perfis_demo` (k-means);
    amostra: segmentação por regras sobre o export; fixture: o perfil sintético de teste."""
    f = fonte()
    if f in ("bigquery", "bigquery_snapshot"):
        z = f"{PROJETO}.{DATASET_ZERA}"

        def consulta():
            linhas = _query(f"""SELECT id_usuario, nome, medoide, cluster, distancia, renda_mediana, renda_media, meses_com_renda, renda_conhecida,
                                       total_dividas, qtd_dividas, meses_no_vermelho, sinais, ordem
                                FROM `{z}.perfis_demo` ORDER BY ordem""")
            return [{"cliente_id": r["id_usuario"], "nome": r["nome"], "persona": False, "medoide": bool(r["medoide"]), "cluster": r["cluster"],
                     "distancia": r["distancia"], "renda_mediana": r2(r["renda_mediana"] or 0), "renda_media": r2(r.get("renda_media") or 0),
                     "meses_com_renda": int(r.get("meses_com_renda") or 0), "renda_conhecida": bool(r["renda_conhecida"]),
                     "total_dividas": r2(r["total_dividas"] or 0), "qtd_dividas": int(r["qtd_dividas"] or 0), "meses_no_vermelho": r["meses_no_vermelho"],
                     "sinais": r["sinais"], "fonte_dividas": "derivada_extrato", "fonte": "bigquery", "segmentacao": "k-means (BigQuery ML)"} for r in linhas]

        def do_snapshot():
            return [{**p, "fonte": fonte_efetiva()} for p in _ler_snapshot("perfis_demo")]

        return _bq_ou_snapshot(consulta, do_snapshot)
    if f == "fixture":
        meta = carregar_dividas_json()
        p, _ = carregar_perfil(meta["cliente_id"])
        return [{"cliente_id": p.cliente_id, "nome": p.nome, "persona": True, "medoide": False, "cluster": None, "distancia": None,
                 "renda_mediana": p.renda_mediana, "renda_media": p.renda_media, "meses_com_renda": p.meses_com_renda, "renda_conhecida": not p.renda_desconhecida, "total_dividas": p.total_dividas,
                 "qtd_dividas": len(p.dividas), "meses_no_vermelho": None, "sinais": "fixture de teste", "fonte_dividas": "cadastro",
                 "fonte": "fixture", "segmentacao": "nenhuma (fixture)"}]
    from dados.segmentacao import features_por_cliente, pseudonimo, score_endividamento, sinais_de

    df = carregar_amostra()
    feats = features_por_cliente(df)
    feats["score"] = score_endividamento(feats)
    # com renda identificada primeiro (dados suficientes para a proatividade); dentro de cada grupo, mais endividado primeiro
    feats["renda_ok"] = (feats["meses_com_renda"] > 0).astype(int)
    feats = feats.sort_values(["renda_ok", "score"], ascending=[False, False])
    perfis = []
    for cid, row in feats.iterrows():
        dividas = derivar_dividas(df, str(cid))
        if not dividas:
            continue
        ordem = len(perfis) + 1
        renda_conhecida = bool(row["meses_com_renda"] > 0)
        perfis.append({"cliente_id": str(cid), "nome": pseudonimo(str(cid), ordem), "persona": False, "medoide": ordem == 1, "cluster": None,
                       "distancia": None, "renda_mediana": r2(row["renda_mediana"]), "renda_media": r2(row["renda_media"]), "meses_com_renda": int(row["meses_com_renda"]), "renda_conhecida": renda_conhecida,
                       "total_dividas": r2(sum(d["saldo"] for d in dividas)), "qtd_dividas": len(dividas),
                       "meses_no_vermelho": int(row["meses_no_vermelho"]), "sinais": sinais_de(row, renda_conhecida),
                       "fonte_dividas": "derivada_extrato", "fonte": "amostra", "segmentacao": "regras (amostra local)",
                       "score": r2(row["score"])})
        if len(perfis) >= MAX_PERFIS:
            break
    return perfis


def perfil_clusters() -> list[dict]:
    if fonte() not in ("bigquery", "bigquery_snapshot"):
        return []
    return _bq_ou_snapshot(lambda: _query(f"SELECT * FROM `{PROJETO}.{DATASET_ZERA}.perfil_clusters` ORDER BY cluster"),
                           lambda: _ler_snapshot("perfil_clusters"))


def derivar_dividas(df: pd.DataFrame, cliente_id: str) -> list[dict]:
    """Infere dívidas do extrato bruto (mesmas regras de dados/sql/zera_tabelas.sql), para ids reais sem cadastro."""
    d = df[df["cliente_id"].astype(str) == str(cliente_id)]
    if d.empty:
        return []
    ultimo = d["mes"].max()
    u = d[d["mes"] == ultimo]
    dividas: list[dict] = []
    base = {"instituicao": "Itaú", "fonte": "derivada_extrato"}
    if "saldo_apos" in u.columns and (u["saldo_apos"] < 0).any():
        dividas.append({**base, "divida_id": "dv_cheque_especial", "produto": "cheque_especial", "saldo": r2(-u["saldo_apos"].min()),
                        "taxa_mensal": TAXAS_DERIVADAS["cheque_especial"], "dias_atraso": 0, "consequencia": "nenhuma",
                        "descricao": "saldo negativo no último mês (estimado a partir do extrato)"})
    if "parcela_total" in u.columns:
        pr = u[u["parcela_total"].notna()]
        if not pr.empty:
            saldo = (pr["valor"] * (pr["parcela_total"] - pr["parcela_atual"].fillna(1) + 1)).sum()
            dividas.append({**base, "divida_id": "dv_crediario", "produto": "crediario", "saldo": r2(saldo), "parcela_atual": r2(pr["valor"].sum()),
                            "parcelas_restantes": int((pr["parcela_total"] - pr["parcela_atual"].fillna(1) + 1).max()),
                            "taxa_mensal": TAXAS_DERIVADAS["crediario"], "dias_atraso": 0, "consequencia": "nenhuma",
                            "descricao": f"{len(pr)} parcelamentos ativos (estimado a partir do extrato)"})
    desc = u["descricao"].astype(str).str.lower()
    cartao = u[desc.str.contains(r"minimo|mínimo|rotativo|juros cart|encargo", regex=True)]
    if not cartao.empty:
        dividas.append({**base, "divida_id": "dv_cartao_rotativo", "produto": "cartao_rotativo", "saldo": r2(cartao["valor"].sum() * 6),
                        "taxa_mensal": TAXAS_DERIVADAS["cartao_rotativo"], "dias_atraso": 60, "consequencia": "negativacao",
                        "descricao": "pagamento mínimo/rotativo detectado (estimado a partir do extrato)"})
    emp = u[desc.str.contains(r"emprest|emprést|financ|consign", regex=True)]
    if not emp.empty:
        dividas.append({**base, "divida_id": "dv_emprestimo", "produto": "emprestimo", "saldo": r2(emp["valor"].sum() * 8),
                        "parcela_atual": r2(emp["valor"].sum()), "parcelas_restantes": 8,
                        "taxa_mensal": TAXAS_DERIVADAS["emprestimo"], "dias_atraso": 0, "consequencia": "negativacao",
                        "descricao": "parcela de empréstimo detectada (estimado a partir do extrato)"})
    return dividas


def carregar_dividas_json(path: Path | None = None) -> dict:
    return json.loads((path or FIXTURES / "persona_cleide_dividas.json").read_text(encoding="utf-8"))


# ---------- perfil ----------

def _dividas(lista: list[dict]) -> list[Divida]:
    out = []
    for d in lista:
        campos = {k: v for k, v in d.items() if k in CAMPOS_DIVIDA and v is not None}
        campos.setdefault("parcela_atual", 0.0)
        campos.setdefault("parcelas_restantes", 0)
        out.append(Divida(**campos))
    return out


def perfil_de_transacoes(cliente_id: str, nome: str, df: pd.DataFrame, dividas: list[dict],
                         tem_reserva: bool = False, dia_pagamento: int = 10, meses: int = 12, **flags) -> PerfilFinanceiro:
    df = df[df["cliente_id"].astype(str) == str(cliente_id)]
    todos_meses = sorted(df["mes"].unique())[-meses:]
    renda = df[df["categoria"] == "renda"].groupby("mes")["valor"].sum()
    essenciais = df[(df["tipo"] == "debito") & df["essencial"]].groupby("mes")["valor"].sum()
    compromissos = pd.Series(0.0, index=todos_meses)   # parcelas fixas fora do acordo (ex.: consórcio) — nenhuma na base
    return PerfilFinanceiro(
        cliente_id=str(cliente_id), nome=nome, meses=list(todos_meses),
        renda_mensal=[r2(renda.get(m, 0.0)) for m in todos_meses],
        essenciais_mensal=[r2(essenciais.get(m, 0.0)) for m in todos_meses],
        compromissos_mensal=[r2(compromissos.get(m, 0.0)) for m in todos_meses],
        dividas=_dividas(dividas), tem_reserva=tem_reserva, dia_pagamento_preferido=dia_pagamento, **flags,
    )


def carregar_perfil(cliente_id: str) -> tuple[PerfilFinanceiro, pd.DataFrame]:
    """Fonte por env ZERA_FONTE: bigquery (agregado; cai para o extrato bruto) | amostra (export real) | fixture (testes)."""
    f = fonte()
    if f in ("bigquery", "bigquery_snapshot"):
        agregado = _bq_ou_snapshot(lambda: carregar_bigquery_agregado(cliente_id),
                                   lambda: _ler_snapshot("perfis").get(str(cliente_id)))
        if agregado:
            n = len(agregado["meses"])
            perfil = PerfilFinanceiro(
                cliente_id=cliente_id, nome=agregado.get("nome") or f"Cliente {cliente_id[:4].upper()}", meses=agregado["meses"],
                renda_mensal=[r2(x) for x in agregado["renda_mensal"]],
                essenciais_mensal=[r2(x) for x in agregado["essenciais_mensal"]],
                compromissos_mensal=[0.0] * n, dividas=_dividas(agregado["dividas"]),
                tem_reserva=False, dia_pagamento_preferido=10, persona=False, fonte=fonte_efetiva(),
            )
            return perfil, pd.DataFrame()
        if _snapshot_ativo or f == "bigquery_snapshot":
            raise LookupError(f"cliente {cliente_id} não está no snapshot do cluster-alvo")
        df = carregar_bigquery(cliente_id)
        dividas = derivar_dividas(df, cliente_id)
        return perfil_de_transacoes(cliente_id, f"Cliente {cliente_id[:4].upper()}", df, dividas, fonte="bigquery"), df
    if f == "fixture":
        meta = carregar_dividas_json()
        if cliente_id != meta.get("cliente_id"):
            raise LookupError(f"cliente {cliente_id} não existe no fixture de teste")
        df = carregar_fixture()
        perfil = perfil_de_transacoes(cliente_id, meta.get("nome", cliente_id), df, meta["dividas"],
                                      tem_reserva=meta.get("tem_reserva", False), dia_pagamento=meta.get("dia_pagamento_preferido", 10),
                                      persona=True, fonte="fixture")
        return perfil, df
    df = carregar_amostra()
    if df[df["cliente_id"].astype(str) == str(cliente_id)].empty:
        raise LookupError(f"cliente {cliente_id} não existe na amostra; use ZERA_FONTE=bigquery para a base completa")
    dividas = derivar_dividas(df, cliente_id)
    nome = next((p["nome"] for p in listar_clientes() if p["cliente_id"] == str(cliente_id)), f"Cliente {cliente_id[:4].upper()}")
    return perfil_de_transacoes(cliente_id, nome, df, dividas, fonte="amostra"), df
