"""Gera o extrato sintético da persona da demo (Cleide) no schema canônico.

Uso:  python -m dados.gerar_cleide   (escreve dados/cleide_12m.csv e dados/cleide_dividas.json)

Os números são desenhados para a história da demo:
- renda irregular (diarista), mediana ≈ 2.325; meses fracos: jan e jul
- essenciais ≈ 1.550/mês
- 3 dívidas Itaú: cartão no rotativo, cheque especial, empréstimo com 2 parcelas atrasadas
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

AQUI = Path(__file__).parent
CLIENTE_ID = "cli_001"
NOME = "Cleide"

# mês -> (renda alvo, sobra alvo)  |  essenciais fixos = 1.550
MESES = [
    ("2025-10", 2350), ("2025-11", 2500), ("2025-12", 2700), ("2026-01", 1750),
    ("2026-02", 1970), ("2026-03", 2300), ("2026-04", 2400), ("2026-05", 2200),
    ("2026-06", 2350), ("2026-07", 1800), ("2026-08", 2450), ("2026-09", 2300),
]

ESSENCIAIS = [  # (dia, descricao, valor, categoria)
    (5, "ALUGUEL PIX IMOBILIARIA", 700.00, "moradia"),
    (12, "ENEL ENERGIA", 110.00, "contas"),
    (14, "SABESP", 50.00, "contas"),
    (20, "GAS BOTIJAO", 30.00, "contas"),
    (3, "SUPERMERCADO DIA", 120.00, "alimentacao"),
    (10, "SUPERMERCADO DIA", 115.00, "alimentacao"),
    (17, "ACOUGUE SAO JOSE", 95.00, "alimentacao"),
    (24, "SUPERMERCADO DIA", 130.00, "alimentacao"),
    (2, "RECARGA BILHETE UNICO", 50.00, "transporte"),
    (16, "RECARGA BILHETE UNICO", 50.00, "transporte"),
    (28, "RECARGA BILHETE UNICO", 50.00, "transporte"),
    (8, "CLARO PRE", 50.00, "telefone"),
]

DIVIDAS = [
    {"divida_id": "dv_cartao", "produto": "cartao_rotativo", "saldo": 3200.00, "taxa_mensal": 0.14,
     "dias_atraso": 60, "parcela_atual": 0.0, "parcelas_restantes": 0, "consequencia": "negativacao",
     "descricao": "Cartão Itaú — 2 ciclos no rotativo", "instituicao": "Itaú"},
    {"divida_id": "dv_cheque", "produto": "cheque_especial", "saldo": 900.00, "taxa_mensal": 0.08,
     "dias_atraso": 0, "parcela_atual": 0.0, "parcelas_restantes": 0, "consequencia": "nenhuma",
     "descricao": "Cheque especial em uso há 20 dias", "instituicao": "Itaú"},
    {"divida_id": "dv_emprestimo", "produto": "emprestimo", "saldo": 2700.00, "taxa_mensal": 0.045,
     "dias_atraso": 60, "parcela_atual": 380.00, "parcelas_restantes": 8, "consequencia": "negativacao",
     "descricao": "Empréstimo pessoal — 2 parcelas de 380 atrasadas", "instituicao": "Outra instituição (Open Finance)"},
]


def _dias_do_mes(ano: int, mes: int) -> int:
    prox = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return (prox - timedelta(days=1)).day


def gerar(seed: int = 42) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    linhas: list[dict] = []
    for mes, renda_alvo in MESES:
        ano, m = map(int, mes.split("-"))
        nd = _dias_do_mes(ano, m)
        # renda: 9 a 12 PIX de faxina somando exatamente renda_alvo
        n = rng.randint(9, 12)
        pesos = [rng.uniform(0.6, 1.4) for _ in range(n)]
        total_peso = sum(pesos)
        valores = [round(renda_alvo * p / total_peso, 2) for p in pesos]
        valores[-1] = round(renda_alvo - sum(valores[:-1]), 2)
        dias = sorted(rng.sample(range(1, nd + 1), n))
        for d, v in zip(dias, valores):
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-{d:02d}", "descricao": "PIX RECEBIDO DIARIA",
                           "valor": v, "tipo": "credito", "categoria": "renda", "essencial": False, "recorrente": True})
        # essenciais
        for d, desc, v, cat in ESSENCIAIS:
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-{min(d, nd):02d}", "descricao": desc,
                           "valor": v, "tipo": "debito", "categoria": cat, "essencial": True, "recorrente": True})
        # gastos não essenciais (não entram na sobra; ficam no extrato para realismo)
        for _ in range(rng.randint(2, 4)):
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-{rng.randint(1, nd):02d}",
                           "descricao": rng.choice(["LANCHONETE", "FARMACIA POPULAR", "LOJAS AMERICANAS", "IFOOD"]),
                           "valor": round(rng.uniform(18, 70), 2), "tipo": "debito", "categoria": "outros",
                           "essencial": False, "recorrente": False})
        # serviço da dívida (categoria 'divida' — fora da sobra; entra no acordo)
        if mes <= "2026-07":
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-15", "descricao": "PARCELA EMPRESTIMO PESSOAL 07/15",
                           "valor": 380.00, "tipo": "debito", "categoria": "divida", "essencial": False, "recorrente": True})
        if mes >= "2026-08":
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-20", "descricao": "PAGTO MINIMO FATURA CARTAO",
                           "valor": 480.00, "tipo": "debito", "categoria": "divida", "essencial": False, "recorrente": True})
        if mes == "2026-09":
            linhas.append({"cliente_id": CLIENTE_ID, "data": f"{mes}-25", "descricao": "JUROS CHEQUE ESPECIAL",
                           "valor": 48.00, "tipo": "debito", "categoria": "divida", "essencial": False, "recorrente": False})
    linhas.sort(key=lambda r: r["data"])
    return linhas, DIVIDAS


def main() -> None:
    linhas, dividas = gerar()
    csv_path = AQUI / "cleide_12m.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    (AQUI / "cleide_dividas.json").write_text(json.dumps(
        {"cliente_id": CLIENTE_ID, "nome": NOME, "tem_reserva": False, "dia_pagamento_preferido": 10, "dividas": dividas},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(linhas)} transações -> {csv_path.name}; {len(dividas)} dívidas -> cleide_dividas.json")


if __name__ == "__main__":
    main()
