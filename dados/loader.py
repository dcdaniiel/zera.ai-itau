"""Carrega o extrato (CSV local ou BigQuery) e monta o PerfilFinanceiro no schema canônico.

Schema canônico de transações:
    cliente_id, data (YYYY-MM-DD), descricao, valor (>0), tipo (credito|debito),
    categoria, essencial (bool), recorrente (bool)

Fontes (env ZERA_FONTE):
    csv       -> dados/cleide_12m.csv + dados/cleide_dividas.json (padrão; P0)
    bigquery  -> `{projeto}.{dataset}.{tabela}` via MAPEAMENTO_COLUNAS (P1; ajuste após ver o schema real)
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
    fonte = os.getenv("ZERA_FONTE", "csv")
    meta = carregar_dividas_json()
    if fonte == "bigquery":
        df = carregar_bigquery(cliente_id)
    else:
        df = carregar_csv()
    perfil = perfil_de_transacoes(cliente_id, meta.get("nome", cliente_id), df, meta["dividas"],
                                  tem_reserva=meta.get("tem_reserva", False),
                                  dia_pagamento=meta.get("dia_pagamento_preferido", 10))
    return perfil, df
