"""Carrega o extrato (CSV local ou BigQuery) e monta o PerfilFinanceiro no schema canônico.

Schema canônico de transações:
    cliente_id, data (YYYY-MM-DD), descricao, valor (>0), tipo (credito|debito),
    categoria, essencial (bool), recorrente (bool)

Fontes (env ZERA_FONTE):
    csv       -> dados/cleide_12m.csv + dados/cleide_dividas.json (padrão; persona da demo)
    bigquery  -> 1) `zera.perfil_cliente` + `zera.dividas_derivadas` (agregado, 1 query por sessão — dados/sql/zera_tabelas.sql)
                 2) fallback: extrato bruto `hackathon_dados.extrato_sintetico` clusterizado por id_usuario + derivar_dividas()
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from motor.modelos import Divida, PerfilFinanceiro, r2

AQUI = Path(__file__).parent

PROJETO = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
DATASET = os.getenv("ZERA_BQ_DATASET", "hackathon_dados")
TABELA = os.getenv("ZERA_BQ_TABELA", "extrato_sintetico")
DATASET_ZERA = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")

# taxas fictícias usadas quando a dívida é derivada do extrato (sem cadastro de dívidas na base do evento)
TAXAS_DERIVADAS = {"cheque_especial": 0.08, "cartao_rotativo": 0.14, "emprestimo": 0.045, "crediario": 0.0}

# Schema real de `hackathon_dados.extrato_sintetico` (visto em 26/09): coluna canônica -> coluna da tabela
#   id_usuario, anomesdia (TIMESTAMP), anomes (INT), tipo (S = saída, E = entrada), descr, vlr,
#   nom_cate_macro, nom_cate_micro, saldo_apos, parcela_atual, parcela_total
MAPEAMENTO_COLUNAS = {
    "cliente_id": "id_usuario",
    "data": "anomesdia",
    "descricao": "descr",
    "valor": "vlr",
    "tipo": "tipo",
    "categoria": "nom_cate_macro",
    "subcategoria": "nom_cate_micro",
    "saldo_apos": "saldo_apos",
    "parcela_atual": "parcela_atual",
    "parcela_total": "parcela_total",
}

# categorias essenciais (fallback quando a base não traz a flag)
CATEGORIAS_ESSENCIAIS = {"moradia", "aluguel", "contas", "energia", "agua", "gas", "alimentacao", "mercado",
                         "supermercado", "transporte", "telefone", "saude", "farmacia", "educacao",
                         # macro-categorias da base do evento
                         "casa", "transporte publico", "posto de combustivel", "educacao", "contas e servicos", "saude"}
# micro-categorias claramente não essenciais dentro de macros essenciais (ex.: Casa > Jardinagem)
MICRO_NAO_ESSENCIAIS = {"jardinagem", "lavanderia"}
PADRAO_RENDA = re.compile(r"(?:SALARIO|SAL[ÁA]RIO|PIX RECEBIDO|TED RECEBIDA|PAGAMENTO RECEBIDO|DIARIA|PROVENTO)", re.I)
PADRAO_DIVIDA = re.compile(r"(?:JUROS|PARCELA|FATURA|EMPRESTIMO|EMPR[ÉE]STIMO|MINIMO|M[ÍI]NIMO|ROTATIVO|CHEQUE ESPECIAL)", re.I)


# ---------- normalização ----------

def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={v: k for k, v in MAPEAMENTO_COLUNAS.items() if v in df.columns}).copy()
    df["data"] = pd.to_datetime(df["data"]).dt.date.astype(str)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").abs()
    if "tipo" not in df.columns:
        df["tipo"] = "debito"
    # base do evento: S = saída (débito), E = entrada (crédito)
    df["tipo"] = df["tipo"].astype(str).str.lower().map(lambda t: "credito" if t.startswith(("c", "e", "+")) else "debito")
    if "categoria" not in df.columns:
        df["categoria"] = "outros"
    df["categoria"] = df["categoria"].astype(str).str.lower().str.strip()
    if "descricao" not in df.columns:
        df["descricao"] = ""
    # renda: créditos com cara de renda (ou categoria renda)
    renda_mask = (df["tipo"] == "credito") & (df["categoria"].isin({"renda", "salario", "salário"}) | df["descricao"].astype(str).str.contains(PADRAO_RENDA))
    df.loc[renda_mask, "categoria"] = "renda"
    # dívida: débitos de juros/parcelas
    divida_mask = (df["tipo"] == "debito") & (df["categoria"].isin({"divida", "dívida"}) | df["descricao"].astype(str).str.contains(PADRAO_DIVIDA))
    df.loc[divida_mask, "categoria"] = "divida"
    if "subcategoria" in df.columns:
        df["subcategoria"] = df["subcategoria"].astype(str).str.lower().str.strip()
    if "essencial" not in df.columns:
        df["essencial"] = (df["tipo"] == "debito") & df["categoria"].isin(CATEGORIAS_ESSENCIAIS)
        if "subcategoria" in df.columns:
            df.loc[df["subcategoria"].isin(MICRO_NAO_ESSENCIAIS), "essencial"] = False
        # Mercado da base é macro "mercado" (já coberto); delivery/restaurantes ficam fora da sobra
    df["essencial"] = df["essencial"].astype(str).str.lower().isin({"true", "1", "sim", "yes"}) if df["essencial"].dtype == object else df["essencial"].astype(bool)
    if "recorrente" not in df.columns:
        df["recorrente"] = df["categoria"].isin({"renda"} | CATEGORIAS_ESSENCIAIS)
    df["mes"] = df["data"].str.slice(0, 7)
    return df


# ---------- fontes ----------

def carregar_csv(path: Path | None = None) -> pd.DataFrame:
    return normalizar(pd.read_csv(path or AQUI / "cleide_12m.csv"))


def carregar_bigquery(cliente_id: str, meses: int = 12) -> pd.DataFrame:
    from google.cloud import bigquery  # import tardio: só quando a fonte é BigQuery

    client = bigquery.Client(project=PROJETO)
    col = MAPEAMENTO_COLUNAS
    sql = f"""
        SELECT *
        FROM `{PROJETO}.{DATASET}.{TABELA}`
        WHERE {col['cliente_id']} = @cliente_id
          AND DATE({col['data']}) >= DATE_SUB((SELECT MAX(DATE({col['data']})) FROM `{PROJETO}.{DATASET}.{TABELA}`), INTERVAL @meses MONTH)
        ORDER BY {col['data']}
    """
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("cliente_id", "STRING", cliente_id),
        bigquery.ScalarQueryParameter("meses", "INT64", meses),
    ]))
    return normalizar(job.result().to_dataframe())


def carregar_bigquery_agregado(cliente_id: str) -> tuple[dict | None, list[dict]]:
    """Caminho rápido: 1 query em `zera.perfil_cliente` (arrays de 12 meses) + dívidas derivadas. None se não existir."""
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJETO)
    sql = f"""
        SELECT p.meses, p.renda_mensal, p.essenciais_mensal, p.parcelas_mensal, p.cv_renda, p.meses_no_vermelho,
               ARRAY(SELECT AS STRUCT divida_id, produto, saldo, taxa_mensal, dias_atraso, consequencia, descricao
                     FROM `{PROJETO}.{DATASET_ZERA}.dividas_derivadas` d WHERE d.id_usuario = p.id_usuario) AS dividas
        FROM `{PROJETO}.{DATASET_ZERA}.perfil_cliente` p
        WHERE p.id_usuario = @cliente_id
    """
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("cliente_id", "STRING", cliente_id)]))
    for row in job.result():
        perfil = {"meses": list(row["meses"]), "renda_mensal": [float(x) for x in row["renda_mensal"]],
                  "essenciais_mensal": [float(x) for x in row["essenciais_mensal"]],
                  "parcelas_mensal": [float(x) for x in row["parcelas_mensal"]]}
        dividas = [dict(d) for d in row["dividas"]]
        return perfil, dividas
    return None, []


def derivar_dividas(df: pd.DataFrame, cliente_id: str) -> list[dict]:
    """Infere dívidas do extrato bruto (mesmas regras de dados/sql/zera_tabelas.sql), para ids reais sem cadastro."""
    d = df[df["cliente_id"].astype(str) == str(cliente_id)]
    if d.empty:
        return []
    ultimo = d["mes"].max()
    u = d[d["mes"] == ultimo]
    dividas: list[dict] = []
    if "saldo_apos" in u.columns and (u["saldo_apos"] < 0).any():
        dividas.append({"divida_id": "dv_cheque_especial", "produto": "cheque_especial", "saldo": r2(-u["saldo_apos"].min()),
                        "taxa_mensal": TAXAS_DERIVADAS["cheque_especial"], "dias_atraso": 0, "consequencia": "nenhuma",
                        "descricao": "saldo negativo no último mês"})
    if "parcela_total" in u.columns:
        pr = u[u["parcela_total"].notna()]
        if not pr.empty:
            saldo = (pr["valor"] * (pr["parcela_total"] - pr["parcela_atual"].fillna(1) + 1)).sum()
            dividas.append({"divida_id": "dv_crediario", "produto": "crediario", "saldo": r2(saldo),
                            "taxa_mensal": TAXAS_DERIVADAS["crediario"], "dias_atraso": 0, "consequencia": "nenhuma",
                            "descricao": f"{len(pr)} parcelamentos ativos"})
    desc = u["descricao"].astype(str).str.lower()
    cartao = u[desc.str.contains(r"minimo|mínimo|rotativo|juros cart|encargo", regex=True)]
    if not cartao.empty:
        dividas.append({"divida_id": "dv_cartao_rotativo", "produto": "cartao_rotativo", "saldo": r2(cartao["valor"].sum() * 6),
                        "taxa_mensal": TAXAS_DERIVADAS["cartao_rotativo"], "dias_atraso": 60, "consequencia": "negativacao",
                        "descricao": "pagamento mínimo/rotativo detectado"})
    emp = u[desc.str.contains(r"emprest|emprést|financ|consign", regex=True)]
    if not emp.empty:
        dividas.append({"divida_id": "dv_emprestimo", "produto": "emprestimo", "saldo": r2(emp["valor"].sum() * 8),
                        "taxa_mensal": TAXAS_DERIVADAS["emprestimo"], "dias_atraso": 0, "consequencia": "negativacao",
                        "descricao": "parcela de empréstimo detectada"})
    return dividas


def carregar_dividas_json(path: Path | None = None) -> dict:
    return json.loads((path or AQUI / "cleide_dividas.json").read_text(encoding="utf-8"))


# ---------- perfil ----------

def perfil_de_transacoes(cliente_id: str, nome: str, df: pd.DataFrame, dividas: list[dict],
                         tem_reserva: bool = False, dia_pagamento: int = 10, meses: int = 12) -> PerfilFinanceiro:
    df = df[df["cliente_id"].astype(str) == str(cliente_id)]
    todos_meses = sorted(df["mes"].unique())[-meses:]
    renda = df[df["categoria"] == "renda"].groupby("mes")["valor"].sum()
    essenciais = df[(df["tipo"] == "debito") & df["essencial"]].groupby("mes")["valor"].sum()
    # compromissos fora do acordo: parcelas recorrentes de produtos que NÃO estão na lista de dívidas (ex.: consórcio)
    compromissos = pd.Series(0.0, index=todos_meses)
    return PerfilFinanceiro(
        cliente_id=str(cliente_id),
        nome=nome,
        meses=list(todos_meses),
        renda_mensal=[r2(renda.get(m, 0.0)) for m in todos_meses],
        essenciais_mensal=[r2(essenciais.get(m, 0.0)) for m in todos_meses],
        compromissos_mensal=[r2(compromissos.get(m, 0.0)) for m in todos_meses],
        dividas=[Divida(**{k: v for k, v in d.items() if k in Divida.__dataclass_fields__}) for d in dividas],
        tem_reserva=tem_reserva,
        dia_pagamento_preferido=dia_pagamento,
    )


def carregar_perfil(cliente_id: str = "cli_001") -> tuple[PerfilFinanceiro, pd.DataFrame]:
    """Fonte por env ZERA_FONTE: csv (persona sintética) | bigquery (agregado zera.perfil_cliente; cai para o extrato bruto)."""
    fonte = os.getenv("ZERA_FONTE", "csv")
    meta = carregar_dividas_json()
    if fonte == "bigquery" and cliente_id != meta.get("cliente_id"):
        agregado, dividas = carregar_bigquery_agregado(cliente_id)
        if agregado:
            n = len(agregado["meses"])
            perfil = PerfilFinanceiro(
                cliente_id=cliente_id, nome=f"Cliente {cliente_id[:8]}", meses=agregado["meses"],
                renda_mensal=[r2(x) for x in agregado["renda_mensal"]],
                essenciais_mensal=[r2(x) for x in agregado["essenciais_mensal"]],
                compromissos_mensal=[0.0] * n,
                dividas=[Divida(**{k: v for k, v in d.items() if k in Divida.__dataclass_fields__}) for d in dividas],
                tem_reserva=False, dia_pagamento_preferido=10,
            )
            return perfil, pd.DataFrame()
        df = carregar_bigquery(cliente_id)
        dividas = derivar_dividas(df, cliente_id)
        perfil = perfil_de_transacoes(cliente_id, f"Cliente {cliente_id[:8]}", df, dividas)
        return perfil, df
    df = carregar_csv()
    perfil = perfil_de_transacoes(cliente_id, meta.get("nome", cliente_id), df, meta["dividas"],
                                  tem_reserva=meta.get("tem_reserva", False),
                                  dia_pagamento=meta.get("dia_pagamento_preferido", 10))
    return perfil, df
