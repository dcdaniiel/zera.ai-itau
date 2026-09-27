"""Camada de dados: BigQuery (query stubada — sem credenciais no CI), amostra real local e fixture de teste."""

from __future__ import annotations

import asyncio

import pytest

from dados import loader
from zera_agent.contexto import Contexto
from zera_agent.experiencia import Experiencia

REAL = "0316550e-3d08-4837-8f31-ac73dd26f7e3"
LINHA_PERFIL = {
    "meses": ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"],
    "renda_mensal": [2350, 2500, 2700, 1750, 1970, 2300, 2400, 2200, 2350, 1800, 2450, 2300],
    "essenciais_mensal": [1550] * 12, "parcelas_mensal": [0] * 12, "renda_conhecida": True, "cv_renda": 0.13, "meses_no_vermelho": 3,
    "segmento": {"cluster": 2, "distancia": 0.41}, "demo": {"nome": "Cleide", "ordem": 1, "medoide": True},
    "derivadas": [{"divida_id": "dv_cartao_rotativo", "produto": "cartao_rotativo", "saldo": 3200.0, "taxa_mensal": 0.14, "dias_atraso": 60,
                   "parcela_atual": 0.0, "parcelas_restantes": 0, "consequencia": "negativacao", "descricao": "x", "instituicao": "Itaú", "fonte": "derivada_extrato"}],
}
LINHA_REAL = {**LINHA_PERFIL, "renda_mensal": [0] * 12, "renda_conhecida": False, "segmento": {"cluster": 2, "distancia": 0.9},
              "demo": {"nome": "Diego 0316", "ordem": 2, "medoide": False},
              "derivadas": [{"divida_id": "dv_cheque_especial", "produto": "cheque_especial", "saldo": 812.5, "taxa_mensal": 0.08, "dias_atraso": 0,
                             "parcela_atual": 0.0, "parcelas_restantes": 0, "consequencia": "nenhuma", "descricao": "saldo negativo", "instituicao": "Itaú",
                             "fonte": "derivada_extrato"}]}
PERFIS = [{"id_usuario": "aaaa-1", "nome": "Cleide", "medoide": True, "cluster": 2, "distancia": 0.41, "renda_mediana": 2325.0, "renda_conhecida": True,
           "total_dividas": 3200.0, "qtd_dividas": 1, "meses_no_vermelho": 3, "sinais": "rotativo/mínimo do cartão", "ordem": 1},
          {"id_usuario": REAL, "nome": "Diego 0316", "medoide": False, "cluster": 2, "distancia": 0.9, "renda_mediana": 0.0,
           "renda_conhecida": False, "total_dividas": 812.5, "qtd_dividas": 1, "meses_no_vermelho": 4,
           "sinais": "4 meses no vermelho · renda não identificada no extrato", "ordem": 2}]


@pytest.fixture
def bigquery_stub(monkeypatch, tmp_path):
    monkeypatch.setenv("ZERA_FONTE", "bigquery")
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))

    def _query(sql: str, **params):
        if "FROM `" in sql and "perfis_demo` ORDER BY ordem" in sql:
            return PERFIS
        if "perfil_cliente` p" in sql:
            cid = params.get("cliente_id")
            return [LINHA_PERFIL] if cid == "aaaa-1" else ([LINHA_REAL] if cid == REAL else [])
        if "perfil_clusters" in sql:
            return [{"cluster": 2, "clientes": 40, "cluster_alvo": True}]
        raise AssertionError(f"query inesperada: {sql[:80]}")

    monkeypatch.setattr(loader, "_query", _query)
    Contexto.limpar_cache()
    yield
    Contexto.limpar_cache()


def test_listar_clientes_bigquery_vem_do_cluster_alvo(bigquery_stub):
    perfis = loader.listar_clientes()
    assert [p["cliente_id"] for p in perfis] == ["aaaa-1", REAL]
    assert perfis[0]["medoide"] is True and perfis[0]["nome"] == "Cleide" and all(p["persona"] is False for p in perfis)
    assert perfis[1]["renda_conhecida"] is False and perfis[1]["fonte_dividas"] == "derivada_extrato" and perfis[1]["segmentacao"].startswith("k-means")


def test_perfil_bigquery_cliente_real_sem_renda_pergunta(bigquery_stub):
    p, _ = loader.carregar_perfil("aaaa-1")
    assert p.nome == "Cleide" and p.persona is False and p.fonte == "bigquery" and p.renda_mediana == 2325.0
    assert [d.fonte for d in p.dividas] == ["derivada_extrato"]
    real, _ = loader.carregar_perfil(REAL)
    assert real.renda_desconhecida is True and real.dividas[0].fonte == "derivada_extrato"
    exp = Experiencia(Contexto.para(REAL))
    assert exp.avaliar_proatividade()["silent"] is True                  # sem contexto suficiente -> sem abordagem proativa
    r = asyncio.run(exp.evento("START", {}))
    assert r["question"] == "renda"
    r = asyncio.run(exp.evento("ANSWER", {"id": "YES", "valor_mensal": 2600}))
    assert r["question"] == "gasto_recorrente" and Contexto.para(REAL).perfil.renda_mediana == 2600.0
    r = asyncio.run(exp.evento("ANSWER", {"id": "NO"}))
    assert r["state"] in ("SHOWING_OPTIONS", "NO_SUITABLE_OPTION")


def test_amostra_real_segmentacao_por_regras(monkeypatch, tmp_path):
    monkeypatch.setenv("ZERA_FONTE", "amostra")
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))
    Contexto.limpar_cache()
    perfis = loader.listar_clientes()
    assert 3 <= len(perfis) <= 12 and perfis[0]["nome"] == "Cleide" and perfis[0]["medoide"] is True
    assert all(p["persona"] is False and p["fonte"] == "amostra" and p["qtd_dividas"] > 0 for p in perfis)
    assert all(perfis[i]["score"] >= perfis[i + 1]["score"] for i in range(len(perfis) - 1))
    p, _ = loader.carregar_perfil(perfis[0]["cliente_id"])
    assert p.fonte == "amostra" and p.renda_desconhecida and all(d.fonte == "derivada_extrato" for d in p.dividas)
    with pytest.raises(LookupError):
        loader.carregar_perfil("nao-existe")
    exp = Experiencia(Contexto.para(perfis[0]["cliente_id"]))
    r = asyncio.run(exp.evento("START", {}))
    assert r["question"] == "renda"                                        # dados insuficientes -> pergunta (nunca inventa)
    Contexto.limpar_cache()


def test_fixture_so_para_testes():
    assert loader.fonte() == "fixture"
    p, _ = loader.carregar_perfil("cli_001")
    assert p.persona is True and p.fonte == "fixture"
    with pytest.raises(LookupError):
        loader.carregar_perfil("outro")
