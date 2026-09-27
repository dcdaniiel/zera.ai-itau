"""Snapshot dos resultados do BigQuery (k-means + perfis) para embarcar na imagem de produção.

Por que existe: no projeto do evento a identidade de runtime do Cloud Run não tem permissão de rodar jobs no BigQuery
(bigquery.jobs.create), mas a conta de quem faz o deploy tem. Então o deploy exporta, com a credencial de quem publica,
exatamente o que `zera.*` devolveria em runtime — `perfis_demo` (clientes reais do cluster-alvo, ordenados pela distância
ao centróide), o perfil agregado de 12 meses de cada um, as dívidas derivadas e `perfil_clusters` — e a API lê esse snapshot
quando o BigQuery recusa a query (ou quando ZERA_FONTE=bigquery_snapshot). A fonte fica rotulada com a hora da exportação.

    uv run python -m dados.exportar_snapshot_bq          # escreve dados/snapshot_bq/*.json (pequeno: 12 perfis)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dados import loader

PASTA = Path(__file__).parent / "snapshot_bq"


def exportar(pasta: Path = PASTA) -> dict:
    assert loader.fonte() == "bigquery", "rode com ZERA_FONTE=bigquery (é o que será exportado)"
    pasta.mkdir(parents=True, exist_ok=True)
    perfis = loader.listar_clientes()
    agregados = {}
    for p in perfis:
        ag = loader.carregar_bigquery_agregado(p["cliente_id"])
        if ag:
            agregados[p["cliente_id"]] = ag
    clusters = loader.perfil_clusters()
    meta = {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "projeto": loader.PROJETO,
            "dataset": loader.DATASET_ZERA, "perfis": len(perfis), "agregados": len(agregados), "clusters": len(clusters)}
    (pasta / "perfis_demo.json").write_text(json.dumps(perfis, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (pasta / "perfis.json").write_text(json.dumps(agregados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (pasta / "perfil_clusters.json").write_text(json.dumps(clusters, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (pasta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


if __name__ == "__main__":
    m = exportar()
    print(f"snapshot ok: {m['perfis']} perfis do cluster-alvo, {m['agregados']} agregados, {m['clusters']} clusters -> {PASTA} ({m['gerado_em']})")
