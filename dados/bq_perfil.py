"""QA da fonte BigQuery: imprime perfil, capacidade e cenários de um id_usuario real.

    ZERA_FONTE=bigquery python -m dados.bq_perfil --cliente 2e85f8ba-452e-4dff-bbfc-f3cdce456263 --extra 2800
"""

from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", required=True)
    ap.add_argument("--extra", type=float, default=0.0, help="dinheiro extra para montar os cenários")
    args = ap.parse_args()
    os.environ.setdefault("ZERA_FONTE", "bigquery")
    from dados.loader import carregar_perfil
    from motor import calcular_capacidade, montar_cenarios, priorizar_dividas

    perfil, _ = carregar_perfil(args.cliente)
    cap = calcular_capacidade(perfil)
    print(json.dumps(perfil.to_dict(), ensure_ascii=False, indent=1))
    print(json.dumps(cap.to_dict(), ensure_ascii=False, indent=1))
    print(json.dumps(priorizar_dividas(perfil)["ordem"], ensure_ascii=False, indent=1))
    r = montar_cenarios(perfil, cap, valor_extra=args.extra)
    for c in r.get("cenarios", []):
        print(c["id"], c["rotulos"], "->", c["resumo"], "|", c["comprometimento_mensal"], "/mês")
    print(r.get("explicacao") or r.get("motivo"))


if __name__ == "__main__":
    main()
