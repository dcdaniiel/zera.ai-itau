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
    assert Contexto.para(REAL).perfil.renda_mediana == 2600.0
    if r.get("question") == "gasto_recorrente":                                       # só quando os dados sugerem gasto fora do extrato
        r = asyncio.run(exp.evento("ANSWER", {"id": "NO"}))
    assert r["state"] in ("SHOWING_OPTIONS", "NO_SUITABLE_OPTION")


def test_amostra_real_segmentacao_por_regras(monkeypatch, tmp_path):
    monkeypatch.setenv("ZERA_FONTE", "amostra")
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))
    Contexto.limpar_cache()
    perfis = loader.listar_clientes()
    assert 3 <= len(perfis) <= 12 and perfis[0]["nome"] == "Cleide" and perfis[0]["medoide"] is True
    assert all(p["persona"] is False and p["fonte"] == "amostra" and p["qtd_dividas"] > 0 for p in perfis)
    # com renda identificada primeiro; dentro de cada grupo, mais endividado primeiro
    chave = [(p["renda_conhecida"], p["score"]) for p in perfis]
    assert chave == sorted(chave, reverse=True)
    p, _ = loader.carregar_perfil(perfis[0]["cliente_id"])
    assert p.fonte == "amostra" and all(d.fonte == "derivada_extrato" for d in p.dividas)
    assert p.renda_desconhecida == (p.meses_com_renda == 0)                # renda = entradas do histórico; sem entrada -> desconhecida
    assert p.renda_fonte.startswith("média mensal das entradas") if not p.renda_desconhecida else p.renda_fonte == "não identificada no extrato"
    with pytest.raises(LookupError):
        loader.carregar_perfil("nao-existe")
    exp = Experiencia(Contexto.para(perfis[0]["cliente_id"]))
    r = asyncio.run(exp.evento("START", {}))
    if p.renda_desconhecida:
        assert r["question"] == "renda"                                    # dados insuficientes -> pergunta (nunca inventa)
    else:
        assert r["state"] in ("NEEDS_INFORMATION", "SHOWING_OPTIONS", "NO_SUITABLE_OPTION") and r.get("question") != "renda"
    Contexto.limpar_cache()


def test_fixture_so_para_testes():
    assert loader.fonte() == "fixture"
    p, _ = loader.carregar_perfil("cli_001")
    assert p.persona is True and p.fonte == "fixture"
    with pytest.raises(LookupError):
        loader.carregar_perfil("outro")


def test_snapshot_do_bigquery_cobre_runtime_sem_permissao(monkeypatch, tmp_path):
    """Produção: a identidade do Cloud Run pode não ter bigquery.jobs.create. O deploy exporta o resultado do BigQuery ML
    (perfis_demo + agregados + clusters) e a API cai para o snapshot quando a consulta é recusada — rotulando a fonte."""
    import json

    monkeypatch.setenv("ZERA_FONTE", "bigquery")
    monkeypatch.setenv("ZERA_ESTADO_DIR", str(tmp_path))
    snap = tmp_path / "snapshot_bq"; snap.mkdir()
    perfis = [{"cliente_id": "real-1", "nome": "Cleide", "persona": False, "medoide": True, "cluster": 2, "distancia": 0.3, "renda_mediana": 4000.0,
               "renda_media": 4100.0, "meses_com_renda": 12, "renda_conhecida": True, "total_dividas": 9000.0, "qtd_dividas": 2, "meses_no_vermelho": 10,
               "sinais": "10 meses no vermelho", "fonte_dividas": "derivada_extrato", "fonte": "bigquery", "segmentacao": "k-means (BigQuery ML)"}]
    agregado = {"meses": [f"2025-{m:02d}" for m in range(1, 13)], "renda_mensal": [4100.0] * 12, "essenciais_mensal": [2000.0] * 12,
                "parcelas_mensal": [0.0] * 12, "renda_conhecida": True, "nome": "Cleide", "medoide": True, "segmento": {"cluster": 2, "distancia": 0.3},
                "dividas": [{"divida_id": "d1", "produto": "cheque_especial", "saldo": 9000.0, "taxa_mensal": 0.08, "dias_atraso": 0, "parcela_atual": 0.0,
                             "parcelas_restantes": 0, "consequencia": "nenhuma", "descricao": "cheque especial", "instituicao": "Itaú", "fonte": "derivada_extrato"}]}
    (snap / "perfis_demo.json").write_text(json.dumps(perfis)); (snap / "perfis.json").write_text(json.dumps({"real-1": agregado}))
    (snap / "perfil_clusters.json").write_text(json.dumps([{"cluster": 2, "cluster_alvo": True}]))
    (snap / "meta.json").write_text(json.dumps({"gerado_em": "2026-09-27T04:00:00+00:00", "perfis": 1}))
    monkeypatch.setattr(loader, "SNAPSHOT", snap)
    monkeypatch.setattr(loader, "_snapshot_ativo", None)

    def recusa(sql, **params):
        raise PermissionError("403 POST https://bigquery.googleapis.com/.../jobs: Access Denied: Project batalha-time-03-vhxk")
    monkeypatch.setattr(loader, "_query", recusa)

    lista = loader.listar_clientes()
    assert lista[0]["nome"] == "Cleide" and lista[0]["fonte"].startswith("bigquery_snapshot (2026-09-27")
    p, _ = loader.carregar_perfil("real-1")
    assert p.renda_media == 4100.0 and p.dividas[0].produto == "cheque_especial" and p.fonte.startswith("bigquery_snapshot")
    assert loader.perfil_clusters()[0]["cluster_alvo"] is True and loader.fonte_efetiva().startswith("bigquery_snapshot")
    with pytest.raises(LookupError):
        loader.carregar_perfil("nao-existe")
    monkeypatch.setattr(loader, "_snapshot_ativo", None)
