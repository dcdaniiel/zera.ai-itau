"""Autenticação do agente no Gemini: credencial do ambiente (padrão) ou chave de API (plano B quando a identidade de runtime
não tem roles/aiplatform.user). Sem rede: só a construção do cliente do SDK."""

from zera_agent import agent


def test_padrao_usa_credencial_do_ambiente(monkeypatch):
    monkeypatch.delenv("ZERA_GEMINI_API_KEY", raising=False)
    assert agent.autenticacao_llm() == "adc"
    assert agent.modelo() == agent.MODEL   # string: o ADK monta o cliente Vertex com ADC / identidade do serviço


def test_chave_de_api_vertex_modo_express_ignora_projeto_e_location(monkeypatch):
    monkeypatch.setenv("ZERA_GEMINI_API_KEY", "AIza-teste")
    monkeypatch.delenv("ZERA_GEMINI_API_KEY_MODO", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "batalha-time-03-vhxk")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    m = agent.modelo()
    assert agent.autenticacao_llm() == "api_key:vertex"
    assert m.model == agent.MODEL
    cli = m.api_client
    assert cli.vertexai is True
    assert cli._api_client.api_key == "AIza-teste"
    assert cli._api_client.project is None and cli._api_client.location is None   # a chave explícita vence o projeto/location do ambiente
    assert cli._api_client._http_options.base_url == "https://aiplatform.googleapis.com/"


def test_chave_de_api_modo_developer(monkeypatch):
    monkeypatch.setenv("ZERA_GEMINI_API_KEY", "AIza-teste")
    monkeypatch.setenv("ZERA_GEMINI_API_KEY_MODO", "developer")
    m = agent.modelo()
    assert agent.autenticacao_llm() == "api_key:developer"
    assert m.api_client.vertexai is False
    assert m.api_client._api_client._http_options.base_url == "https://generativelanguage.googleapis.com/"
