"""Concede à identidade de runtime do Cloud Run acesso ao dataset `zera` — o dono do dataset (quem rodou publicar_bq) pode fazer
isso sem ser Owner do projeto. Com WRITER no dataset a API lê zera.* direto das tabelas (tabledata.list, sem job) e grava
estado/eventos/telemetria por streaming insert — tudo ao vivo no BigQuery, sem depender de bigquery.jobs.create.

    uv run python infra/conceder_dataset.py                       # conta compute do projeto (padrão do Cloud Run)
    uv run python infra/conceder_dataset.py zera-run@proj.iam.gserviceaccount.com
"""

from __future__ import annotations

import os
import sys

from google.cloud import bigquery

PROJETO = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
DATASET = os.getenv("ZERA_BQ_DATASET_ZERA", "zera")


def main() -> None:
    client = bigquery.Client(project=PROJETO)
    numero = client.get_dataset(f"{PROJETO}.{DATASET}").project  # só para validar acesso
    if len(sys.argv) > 1:
        sa = sys.argv[1]
    else:
        from google.cloud import resourcemanager_v3  # type: ignore

        try:
            proj = resourcemanager_v3.ProjectsClient().get_project(name=f"projects/{PROJETO}")
            sa = f"{proj.name.split('/')[-1]}-compute@developer.gserviceaccount.com"
        except Exception:  # noqa: BLE001 — sem a lib/permissão: passe a SA como argumento
            sys.exit("informe a service account de runtime como argumento (ex.: 27813124245-compute@developer.gserviceaccount.com)")
    ds = client.get_dataset(f"{PROJETO}.{DATASET}")
    entradas = list(ds.access_entries)
    if any(e.entity_id == sa for e in entradas):
        print(f"já tem acesso: {sa} em {PROJETO}.{DATASET}")
        return
    entradas.append(bigquery.AccessEntry("WRITER", "serviceAccount", sa))
    ds.access_entries = entradas
    client.update_dataset(ds, ["access_entries"])
    print(f"ok: WRITER em {numero}.{DATASET} para {sa} — a API passa a ler/gravar ao vivo no BigQuery (sem job)")


if __name__ == "__main__":
    main()
