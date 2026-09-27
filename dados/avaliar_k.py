"""Escolha do número de clusters: treina k-means (BigQuery ML) para k = 2…8 com as MESMAS features do modelo de produção,
avalia cada um (ML.EVALUATE: Davies-Bouldin, distância quadrática média) e desenha o gráfico da solução.

    uv run python -m dados.avaliar_k              # ~5–8 min (7 modelos); escreve zera.kmeans_avaliacao + docs/davies_bouldin.svg
    uv run python -m dados.avaliar_k --ks 2 3 4 5 6   # outro intervalo
    uv run python -m dados.avaliar_k --so-grafico     # só redesenha a partir de zera.kmeans_avaliacao (sem treinar)

Nada é inventado: os pontos do gráfico são os valores devolvidos pelo BigQuery ML; o k de produção (4) é destacado.
Davies-Bouldin: menor = clusters mais compactos e separados. A escolha final pondera o índice com a legibilidade
de negócio dos segmentos (um cluster "no vermelho crônico" claro), registrada em docs/arquitetura-explicativa.md §8 (A5).
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from dados.publicar_bq import DATASET, PROJETO, _client

FEATURES = ("pct_essenciais, pct_servico_divida, parcelas_media, qtd_parcelas_media, assinaturas_media, "
            "meses_no_vermelho, pior_saldo, sinais_rotativo, sinais_emprestimo, cv_renda, comprometimento_futuro_medio")
K_PRODUCAO = int(os.getenv("ZERA_NUM_CLUSTERS", "4"))
SAIDA = Path(__file__).resolve().parent.parent / "docs" / "davies_bouldin.svg"


def treinar_e_avaliar(client, ks: list[int]) -> list[dict]:
    linhas = []
    for k in ks:
        modelo = f"`{PROJETO}.{DATASET}.kmeans_k{k}`"
        print(f"k={k}: treinando ...", end=" ", flush=True)
        client.query(f"""
            CREATE OR REPLACE MODEL {modelo}
            OPTIONS (model_type = 'KMEANS', num_clusters = {k}, standardize_features = TRUE,
                     kmeans_init_method = 'KMEANS++', max_iterations = 50) AS
            SELECT {FEATURES} FROM `{PROJETO}.{DATASET}.features_cliente`""").result()
        row = next(iter(client.query(f"SELECT davies_bouldin_index AS db, mean_squared_distance AS msd FROM ML.EVALUATE(MODEL {modelo})").result()))
        linhas.append({"k": k, "davies_bouldin_index": float(row["db"]), "mean_squared_distance": float(row["msd"])})
        print(f"Davies-Bouldin {row['db']:.3f} · dist. quadr. média {row['msd']:.3f}")
    valores = ", ".join(f"STRUCT({l['k']} AS k, {l['davies_bouldin_index']!r} AS davies_bouldin_index, {l['mean_squared_distance']!r} AS mean_squared_distance)" for l in linhas)
    client.query(f"""
        CREATE OR REPLACE TABLE `{PROJETO}.{DATASET}.kmeans_avaliacao` AS
        SELECT k, davies_bouldin_index, mean_squared_distance, {K_PRODUCAO} AS k_producao, CURRENT_TIMESTAMP() AS avaliado_em
        FROM UNNEST([{valores}])""").result()
    print(f"tabela {DATASET}.kmeans_avaliacao gravada")
    return linhas


def ler_avaliacao(client) -> list[dict]:
    return [dict(r) for r in client.query(f"SELECT k, davies_bouldin_index, mean_squared_distance FROM `{PROJETO}.{DATASET}.kmeans_avaliacao` ORDER BY k").result()]


def grafico_svg(linhas: list[dict], destino: Path = SAIDA, k_prod: int = K_PRODUCAO) -> Path:
    """Gráfico de linha do Davies-Bouldin por k (SVG puro, sem dependências): pronto para slide/README."""
    W, H, ML, MR, MT, MB = 760, 420, 78, 28, 64, 70
    ks = [l["k"] for l in linhas]
    ys = [l["davies_bouldin_index"] for l in linhas]
    ymin, ymax = 0.0, max(ys) * 1.15
    px = lambda k: ML + (k - min(ks)) / max(1, (max(ks) - min(ks))) * (W - ML - MR)  # noqa: E731
    py = lambda y: MT + (1 - (y - ymin) / (ymax - ymin)) * (H - MT - MB)              # noqa: E731
    laranja, navy, cinza, grade = "#EC7000", "#15203A", "#5A6577", "#E3E7EE"
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">',
              f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
              f'<text x="{ML}" y="30" font-size="18" font-weight="700" fill="{navy}">Davies-Bouldin por número de clusters (k-means, BigQuery ML)</text>',
              f'<text x="{ML}" y="50" font-size="11.5" fill="{cinza}">Base completa do evento · {len(ks)} modelos, mesmas 11 features padronizadas · menor = clusters mais compactos e separados</text>']
    # grade e eixo y
    passos = 5
    for i in range(passos + 1):
        y = ymin + (ymax - ymin) * i / passos
        partes.append(f'<line x1="{ML}" y1="{py(y):.1f}" x2="{W - MR}" y2="{py(y):.1f}" stroke="{grade}" stroke-width="1"/>')
        partes.append(f'<text x="{ML - 10}" y="{py(y) + 4:.1f}" font-size="11" text-anchor="end" fill="{cinza}">{y:.2f}</text>')
    # eixo x
    for k in ks:
        partes.append(f'<text x="{px(k):.1f}" y="{H - MB + 22}" font-size="12" text-anchor="middle" fill="{navy if k == k_prod else cinza}" font-weight="{700 if k == k_prod else 400}">k = {k}</text>')
    partes.append(f'<text x="{(ML + W - MR) / 2:.1f}" y="{H - MB + 40}" font-size="12" text-anchor="middle" fill="{cinza}">número de clusters</text>')
    partes.append(f'<text transform="translate(20 {(MT + H - MB) / 2:.1f}) rotate(-90)" font-size="12" text-anchor="middle" fill="{cinza}">índice Davies-Bouldin</text>')
    # linha e pontos
    caminho = " ".join(f"{'M' if i == 0 else 'L'}{px(k):.1f},{py(y):.1f}" for i, (k, y) in enumerate(zip(ks, ys)))
    partes.append(f'<path d="{caminho}" fill="none" stroke="{navy}" stroke-width="2.5" stroke-linejoin="round"/>')
    for k, y in zip(ks, ys):
        destaque = k == k_prod
        partes.append(f'<circle cx="{px(k):.1f}" cy="{py(y):.1f}" r="{9 if destaque else 5}" fill="{laranja if destaque else "#FFFFFF"}" stroke="{laranja if destaque else navy}" stroke-width="2.5"/>')
        partes.append(f'<text x="{px(k):.1f}" y="{py(y) - 14:.1f}" font-size="12" text-anchor="middle" font-weight="{700 if destaque else 500}" fill="{laranja if destaque else navy}">{y:.3f}</text>')
    kp = next((l for l in linhas if l["k"] == k_prod), None)
    if kp:
        partes.append(f'<text x="{W - MR}" y="{H - 8}" font-size="11" text-anchor="end" fill="{laranja}" font-weight="700">● k = {k_prod}: modelo em produção (zera.kmeans_perfis) — Davies-Bouldin {kp["davies_bouldin_index"]:.3f}</text>')
    partes.append("</svg>")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(partes), encoding="utf-8")
    return destino


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", type=int, nargs="+", default=[2, 3, 4, 5, 6, 7, 8])
    ap.add_argument("--so-grafico", action="store_true", help="não treina: lê zera.kmeans_avaliacao e redesenha")
    args = ap.parse_args()
    _, client = _client()
    linhas = ler_avaliacao(client) if args.so_grafico else treinar_e_avaliar(client, args.ks)
    print("\nk | Davies-Bouldin | dist. quadrática média")
    for l in linhas:
        print(f"{l['k']} | {l['davies_bouldin_index']:.3f} | {l['mean_squared_distance']:.3f}{'   <- produção' if l['k'] == K_PRODUCAO else ''}")
    melhor = min(linhas, key=lambda l: l["davies_bouldin_index"])
    print(f"\nmenor Davies-Bouldin: k = {melhor['k']} ({melhor['davies_bouldin_index']:.3f}); produção: k = {K_PRODUCAO}")
    print(f"gráfico: {grafico_svg(linhas)}  ({datetime.now(timezone.utc).isoformat(timespec='seconds')})")


if __name__ == "__main__":
    main()
