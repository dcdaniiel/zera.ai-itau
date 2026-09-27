"""Segmentação por regras sobre uma amostra do extrato (modo local `amostra`).

É a versão em pandas das MESMAS features de dados/sql/clusterizacao.sql, para rodar sem BigQuery com a amostra
exportada da base do evento (dados/amostra_bq_extrato_sintetico.csv). No GCP a segmentação é feita por k-means
(BigQuery ML) — aqui é "segmentação por regras" (quadro de produto, item 05: só afirmar clusterização por modelo
se executada). Nada é inventado: os perfis listados são ids reais da amostra; o nome é um pseudônimo determinístico.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from motor.modelos import r2

PSEUDONIMOS = ["Ana", "Bruno", "Carla", "Diego", "Elaine", "Fábio", "Gisele", "Heitor", "Iara", "Jorge", "Kelly", "Luan",
               "Marta", "Nilton", "Otávia", "Paulo"]
NOME_MEDOIDE = "Cleide"   # o cliente mais típico do segmento-alvo recebe o nome da persona do quadro de produto


def pseudonimo(cliente_id: str, ordem: int) -> str:
    if ordem == 1:
        return NOME_MEDOIDE
    h = int(hashlib.sha256(cliente_id.encode()).hexdigest(), 16)
    return f"{PSEUDONIMOS[h % len(PSEUDONIMOS)]} {cliente_id[:4].upper()}"


def features_por_cliente(df: pd.DataFrame) -> pd.DataFrame:
    """Mesmas features de `zera.features_cliente`, calculadas sobre o extrato normalizado (dados/loader.normalizar)."""
    d = df.copy()
    d["saidas"] = d["valor"].where(d["tipo"] == "debito", 0.0)
    d["renda"] = d["valor"].where(d["categoria"] == "renda", 0.0)
    d["essencial_v"] = d["valor"].where(d["essencial"], 0.0)
    d["divida_v"] = d["valor"].where(d["categoria"] == "divida", 0.0)
    d["parcela_v"] = d["valor"].where(d.get("parcela_total", pd.Series(index=d.index, dtype=float)).notna(), 0.0)
    d["assin_v"] = d["valor"].where(d["categoria"].str.contains("assinatura", na=False), 0.0)
    desc = d["descricao"].astype(str).str.lower()
    d["sin_rot"] = desc.str.contains(r"minimo|mínimo|rotativo", regex=True).astype(int)
    d["sin_emp"] = desc.str.contains(r"emprest|emprést|financ|consign", regex=True).astype(int)
    d["neg"] = (d["saldo_apos"] < 0).astype(int) if "saldo_apos" in d.columns else 0
    mensal = d.groupby(["cliente_id", "mes"]).agg(renda=("renda", "sum"), saidas=("saidas", "sum"), essenciais=("essencial_v", "sum"),
                                                  servico_divida=("divida_v", "sum"), parcelas=("parcela_v", "sum"), assinaturas=("assin_v", "sum"),
                                                  qtd_parcelas=("parcela_v", lambda s: int((s > 0).sum())),
                                                  saldo_minimo=("saldo_apos", "min") if "saldo_apos" in d.columns else ("valor", "min"),
                                                  sinais_rotativo=("sin_rot", "sum"), sinais_emprestimo=("sin_emp", "sum")).reset_index()
    g = mensal.groupby("cliente_id")
    f = pd.DataFrame({
        "n_meses": g.size(),
        "renda_mediana": g["renda"].median(),
        "cv_renda": (g["renda"].std(ddof=0) / g["renda"].mean().replace(0, float("nan"))).fillna(0.0),
        "saidas_media": g["saidas"].mean(),
        "pct_essenciais": (g["essenciais"].mean() / g["saidas"].mean().replace(0, float("nan"))).fillna(0.0),
        "pct_servico_divida": (g["servico_divida"].mean() / g["saidas"].mean().replace(0, float("nan"))).fillna(0.0),
        "parcelas_media": g["parcelas"].mean(),
        "qtd_parcelas_media": g["qtd_parcelas"].mean(),
        "assinaturas_media": g["assinaturas"].mean(),
        "meses_no_vermelho": g["saldo_minimo"].apply(lambda s: int((s < 0).sum())),
        "pior_saldo": g["saldo_minimo"].min().fillna(0.0),
        "sinais_rotativo": g["sinais_rotativo"].sum(),
        "sinais_emprestimo": g["sinais_emprestimo"].sum(),
    })
    return f.fillna(0.0)


def score_endividamento(f: pd.DataFrame) -> pd.Series:
    """Índice do segmento-alvo (mesma fórmula do SQL): quanto maior, mais parecido com a persona do quadro de produto."""
    z = lambda s: (s - s.mean()) / (s.std(ddof=0) or 1.0)  # noqa: E731
    return (z(f["meses_no_vermelho"]) + z(-f["pior_saldo"].clip(upper=0)) + z(f["pct_servico_divida"]) + z(f["qtd_parcelas_media"])
            + z(f["sinais_rotativo"]) + z(f["sinais_emprestimo"]))


def sinais_de(row: pd.Series, renda_conhecida: bool) -> str:
    partes = []
    if row["meses_no_vermelho"] > 0:
        partes.append(f"{int(row['meses_no_vermelho'])} {'mês' if row['meses_no_vermelho'] == 1 else 'meses'} no vermelho (pior saldo {r2(row['pior_saldo']):,.0f})".replace(",", "."))
    if row["sinais_rotativo"] > 0:
        partes.append("rotativo/mínimo do cartão")
    if row["sinais_emprestimo"] > 0:
        partes.append("parcela de empréstimo")
    if row["qtd_parcelas_media"] >= 1:
        partes.append(f"~{int(round(row['qtd_parcelas_media']))} parcelamentos/mês")
    if not renda_conhecida:
        partes.append("renda não identificada no extrato")
    return " · ".join(partes)
