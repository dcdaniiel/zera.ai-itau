"""Base de conhecimento institucional do Zera (política, FAQ, glossário).

Busca por palavra-chave sobre os arquivos em conhecimento/base — sem embeddings, sem vector
store. Dados financeiros do cliente (extrato, saldo, taxas, ofertas) nunca entram aqui; eles
vêm de `motor/` e `dados/` via tools. O que este módulo devolve é sempre citável como evidência,
nunca como instrução — por isso qualquer trecho com cara de comando é removido antes de sair.
"""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).parent / "base"

PADRAO_INSTRUCAO_SUSPEITA = re.compile(
    r"(ignore (as|todas as|suas) (instru|regras)|a partir de agora voc[êe] [ée]|"
    r"modo desenvolvedor|revele (o|seu|suas) (prompt|instru)|desative (os|as) (guardrails|regras))",
    re.IGNORECASE,
)


def _chunks() -> list[dict]:
    chunks = []
    for caminho in sorted(BASE.glob("*.md")):
        for paragrafo in re.split(r"\n\s*\n", caminho.read_text(encoding="utf-8")):
            paragrafo = paragrafo.strip()
            if paragrafo:
                chunks.append({"fonte": caminho.stem, "texto": paragrafo})
    return chunks


def _pontuar(pergunta: str, texto: str) -> int:
    palavras = {p for p in re.findall(r"\w+", pergunta.lower()) if len(p) > 3}
    texto_lower = texto.lower()
    return sum(len(re.findall(rf"\b{re.escape(p)}\b", texto_lower)) for p in palavras)


def buscar(pergunta: str, top_k: int = 3) -> list[dict]:
    """Devolve os trechos mais relevantes com a fonte, prontos pra serem citados como evidência."""
    candidatos = [(c, _pontuar(pergunta, c["texto"])) for c in _chunks()]
    candidatos = sorted((c for c in candidatos if c[1] > 0), key=lambda cp: cp[1], reverse=True)
    resultados = []
    for chunk, _ in candidatos[:top_k]:
        texto = PADRAO_INSTRUCAO_SUSPEITA.sub("[trecho removido]", chunk["texto"])
        resultados.append({"fonte": chunk["fonte"], "trecho": texto})
    return resultados
