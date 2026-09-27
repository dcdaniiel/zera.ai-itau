"""Publica a camada de dados do zera.ai no BigQuery — sem mock, sem dado sintético.

    gcloud auth application-default login          # uma vez, na sua máquina (ou rode no Cloud Shell, já autenticado)
    python -m dados.publicar_bq                    # tudo: tabelas (zera_tabelas.sql) -> clusterização (clusterizacao.sql) -> perfis_demo
    python -m dados.publicar_bq --so-sql           # só roda dados/sql/zera_tabelas.sql
    python -m dados.publicar_bq --so-cluster       # só roda dados/sql/clusterizacao.sql (k-means + perfis_demo)
    python -m dados.publicar_bq --mostrar          # imprime perfil_clusters e perfis_demo

Idempotente: CREATE OR REPLACE / IF NOT EXISTS. O dataset `zera` é criado na MESMA location de `hackathon_dados`
(BigQuery não faz JOIN entre locations). Alternativa sem Python: `bq query --use_legacy_sql=false < dados/sql/zera_tabelas.sql`
(substituindo ${PROJETO}/${DATASET}/${DATASET_EVENTO} antes) e o mesmo para clusterizacao.sql.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).parent
PROJETO = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
DATASET_EVENTO = os.getenv("ZERA_BQ_DATASET", "hackathon_dados")
DATASET = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")
NOME_MEDOIDE = os.getenv("ZERA_NOME_PERSONA", "Cleide")   # o cliente mais típico do cluster-alvo recebe o nome da persona do produto


def _client():
    from google.cloud import bigquery

    return bigquery, bigquery.Client(project=PROJETO)


def garantir_dataset(bigquery, client) -> str:
    origem = client.get_dataset(f"{PROJETO}.{DATASET_EVENTO}")
    ds = bigquery.Dataset(f"{PROJETO}.{DATASET}")
    ds.location = origem.location
    ds.description = "zera.ai — camada de dados (extrato particionado, features, perfis, clusterização k-means, estado, eventos, telemetria)"
    client.create_dataset(ds, exists_ok=True)
    print(f"dataset {PROJETO}.{DATASET} ok (location {origem.location})")
    return origem.location


def sql_renderizado(arquivo: Path, **params: str) -> str:
    sql = arquivo.read_text(encoding="utf-8")
    for k, v in {"PROJETO": PROJETO, "DATASET": DATASET, "DATASET_EVENTO": DATASET_EVENTO, "NOME_MEDOIDE": NOME_MEDOIDE, **params}.items():
        sql = sql.replace("${" + k + "}", str(v))
    return sql


def rodar_sql(client, arquivo: Path, **params: str) -> None:
    print(f"rodando {arquivo.name} ...", end=" ", flush=True)
    client.query(sql_renderizado(arquivo, **params)).result()
    print("ok")


def mostrar(client) -> None:
    for tabela, ordem in (("perfil_clusters", "cluster"), ("perfis_demo", "ordem")):
        print(f"\n== {DATASET}.{tabela}")
        for row in client.query(f"SELECT * FROM `{PROJETO}.{DATASET}.{tabela}` ORDER BY {ordem}").result():
            print(json.dumps(dict(row), ensure_ascii=False, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-sql", action="store_true")
    ap.add_argument("--so-cluster", action="store_true")
    ap.add_argument("--mostrar", action="store_true")
    ap.add_argument("--imprimir", action="store_true", help="só imprime o SQL renderizado (para rodar no console/bq)")
    ap.add_argument("--clusters", type=int, default=int(os.getenv("ZERA_NUM_CLUSTERS", "4")))
    ap.add_argument("--max-perfis", type=int, default=int(os.getenv("ZERA_MAX_PERFIS", "12")))
    args = ap.parse_args()
    params = {"NUM_CLUSTERS": args.clusters, "MAX_PERFIS": args.max_perfis}
    if args.imprimir:
        print(sql_renderizado(AQUI / "sql" / "zera_tabelas.sql"))
        print(sql_renderizado(AQUI / "sql" / "clusterizacao.sql", **params))
        return
    tudo = not (args.so_sql or args.so_cluster or args.mostrar)
    bigquery, client = _client()
    garantir_dataset(bigquery, client)
    if tudo or args.so_sql:
        rodar_sql(client, AQUI / "sql" / "zera_tabelas.sql")
    if tudo or args.so_cluster:
        rodar_sql(client, AQUI / "sql" / "clusterizacao.sql", **params)
    if tudo or args.mostrar:
        mostrar(client)
    print("\npronto. Suba a API com ZERA_FONTE=bigquery (e ZERA_ESTADO=bigquery para estado/eventos no BQ).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"falhou: {e}", file=sys.stderr)
        sys.exit(1)
