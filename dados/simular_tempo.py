"""Relógio da demo: avança o tempo do cliente (paga vencimentos, injeta eventos do roteiro, detecta gatilhos).

    python -m dados.simular_tempo --cliente cli_001 --ate 2027-01-07
    python -m dados.simular_tempo --cliente cli_001 --reset
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from zera_agent.contexto import Contexto


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", default="cli_001")
    ap.add_argument("--ate", help="YYYY-MM-DD")
    ap.add_argument("--reset", action="store_true", help="apaga o estado simulado do cliente")
    args = ap.parse_args()
    ctx = Contexto.para(args.cliente)
    if args.reset:
        ctx.resetar()
        print(f"estado de {args.cliente} resetado (hoje = {ctx.estado['hoje']})")
        return
    if not args.ate:
        ap.error("--ate ou --reset")
    res = ctx.avancar_tempo(date.fromisoformat(args.ate))
    print(json.dumps({k: v for k, v in res.items() if k != "acordo"}, ensure_ascii=False, indent=2, default=str))
    if res.get("acordo"):
        a = res["acordo"]
        print(f"acordo: {a['status']} | pagas {a['pagas']}/{a['prazo']} | parcela {a['parcela']} | próximo {a['proximo_vencimento']}")


if __name__ == "__main__":
    main()
