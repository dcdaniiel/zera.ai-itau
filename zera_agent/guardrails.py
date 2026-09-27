"""Guardrails do Zera — arquitetura alvo do workshop RAI (Itaú × Google):

    Pergunta do usuário ──► GUARDRAIL DE ENTRADA ──► modelo gera resposta ──► GUARDRAIL DE SAÍDA ──► usuário
                                 │ fortes indícios de                                │ fortes indícios de
                                 ▼ pergunta problemática                             ▼ resposta problemática
                              BLOQUEADA (resposta segura fixa,                    BLOQUEADA (resposta segura fixa,
                              modelo nem é chamado)                               resposta do modelo descartada)

Entrada  (before_model_callback): Model Armor (P1) + injeção de prompt/jailbreak, engenharia social
          (senha, token, transferência, dados de terceiros), fora de escopo (investimento, crédito novo),
          PII redigida, vulnerabilidade (não bloqueia: muda o tom e escala), contexto (memória, gatilhos).
Ferramentas (before/after_tool_callback): consentimento por ação (uso único), números permitidos.
Saída    (after_model_callback): Model Armor (P1) + PII, pressão/cobrança, promessas, vazamento de prompt,
          fora de escopo, e checagem de todo R$ / % / prazo contra as tools.

Cada bloqueio vira evento (`guardrail_bloqueio`) para o dashboard: taxa de bloqueio, tipo, falso positivo (golden set).
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from zera_agent.contexto import Contexto

log = logging.getLogger("zera.guardrails")

ACOES_COM_CONSENTIMENTO = {"fechar_acordo", "acionar_respiro", "amortizar"}

# ---------- padrões ----------
PADRAO_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PADRAO_TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")
PADRAO_CARTAO = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PADRAO_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PADRAO_TOKEN_MORSE = re.compile(r"^[.-]{1,6}$")
PADRAO_TOKEN_BASE64 = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9+/]{16,}={0,2}$")

LIMITE_BLOQUEIOS_ESCALONAMENTO = 3

# consentimento tem que vir do cliente no turno atual, não pode ser inventado pela tool
PADRAO_CONSENTIMENTO_EXPLICITO = re.compile(
    r"\b(sim(?:\s*,?\s*confirmo)?|confirmo|aceito|autorizo|concordo|quero\s+sim|pode\s+(?:fazer|fechar|usar|aplicar))\b",
    re.IGNORECASE,
)
PADRAO_NEGACAO_CONSENTIMENTO = re.compile(
    r"\b(n[aã]o|jamais|nunca)\b.{0,30}\b(confirmo|aceito|autorizo|concordo|quero|pode)\b",
    re.IGNORECASE,
)

PADRAO_VULNERABILIDADE = re.compile(
    r"(n[ãa]o aguento|desesper|acabar com tudo|me matar|suic|depress|doen[çc]a grave|c[âa]ncer|internad|"
    r"luto|faleceu|morreu|amea[çc]a|agiota|violen|n[ãa]o tenho o que comer|fome)", re.IGNORECASE)

BLOQUEIOS_ENTRADA: dict[str, tuple[re.Pattern, str]] = {
    "injecao_prompt": (
        re.compile(r"(ignore (as|todas as|suas) (instru|regras)|esque[çc]a (as|suas) (regras|instru)|system prompt|prompt do sistema|"
                   r"voc[êe] agora [ée]|a partir de agora voc[êe] [ée]|modo desenvolvedor|developer mode|\bDAN\b|jailbreak|"
                   r"revele (o|seu|suas) (prompt|instru|regras)|mostre (o|seu) prompt|finja que (voc[êe] )?[ée]|"
                   r"sem restri[çc][õo]es|desative (os|as) (guardrails|filtros|regras))", re.IGNORECASE),
        "Não consigo mudar como eu funciono, mas posso continuar te ajudando com as suas dívidas. "
        "Quer ver o raio-X das suas dívidas ou os cenários que cabem no seu mês?",
    ),
    "engenharia_social": (
        re.compile(r"(senha|token|c[óo]digo de (seguran[çc]a|verifica[çc][ãa]o)|\bcvv\b|"
                   r"(fa[çc]a|fazer|faz|manda|mande|envie|enviar|realize) (um |uma )?(pix|ted|transfer[êe]ncia)|"
                   r"transfer(ir|e|ira) (para|pra|pro)|pix (para|pra|pro)|"
                   r"(conta|extrato|d[íi]vidas?|dados|limite) d[oa] (?:(?:meu|minha|outr[oa]|uma?) )?(marido|esposa|m[ãa]e|pai|filh|irm[ãa]|vizinh|amig|cliente|pessoa)|"
                   r"outro cliente|cpf de outra|libere (o|meu) limite|aumente (o|meu) limite)", re.IGNORECASE),
        "Por segurança eu não peço nem uso senhas, códigos ou dados de outras pessoas, e não faço transferências. "
        "Aqui eu só cuido das suas dívidas: quer ver as opções que cabem no seu mês?",
    ),
    "fora_de_escopo": (
        re.compile(r"(invest(ir|imento|e)|cripto|bitcoin|a[çc][õo]es da bolsa|tesouro direto|\bcdb\b|\bbet\b|aposta|"
                   r"(quero|preciso|posso) (fazer|pegar|contratar) (um |outro |mais )?(empr[ée]stimo|cr[ée]dito|financiamento|cart[ãa]o)|"
                   r"novo (empr[ée]stimo|cart[ãa]o|cr[ée]dito)|consignado novo)", re.IGNORECASE),
        "Isso fica fora do que eu faço: eu não recomendo investimentos nem crédito novo — o foco aqui é tirar você "
        "do vermelho com o que já existe. Quer que eu mostre os cenários de renegociação que cabem no seu mês?",
    ),
    "assunto_fora_do_dominio": (
        re.compile(r"(conte (uma |a )?piada|escreva (um |uma )?(poema|redação|hist[óo]ria|m[úu]sica)|"
                   r"me ajude (com|a fazer) (o |a )?(trabalho|dever|li[çc][ãa]o) de (casa|escola|faculdade)|"
                   r"traduza (isso|esse texto|para)|receita de|previs[ãa]o do tempo|"
                   r"qual (a |sua )?opini[ãa]o (sobre|a respeito)|quem (vai ganhar|ganhou) (a elei[çc][ãa]o|as elei[çc][õo]es)|"
                   r"o que voc[êe] acha (do|da|de) (governo|presidente|pol[íi]tica)|me d[êe] uma dica de (filme|s[ée]rie|livro))",
                   re.IGNORECASE),
        "Isso não é algo que eu consigo ajudar por aqui — eu só cuido das suas dívidas e do seu acordo com o banco. "
        "Quer ver o raio-X das suas dívidas ou os cenários que cabem no seu mês?",
    ),
}

RESPOSTA_CONTEUDO_CODIFICADO = (
    "Não consigo processar instruções codificadas. Para sua segurança, escreva o pedido em texto normal. "
    "Posso ajudar com o raio-X das suas dívidas ou com uma proposta que caiba no seu mês."
)
RESPOSTA_ESCALONAMENTO_FORCADO = (
    "Por segurança, vou encaminhar essa conversa para uma pessoa do time. Nenhuma ação foi executada; "
    "alguém vai entrar em contato."
)

BLOQUEIOS_SAIDA: dict[str, tuple[re.Pattern, str]] = {
    "pressao_cobranca": (
        re.compile(r"([úu]ltima chance|voc[êe] (precisa|tem que|deve|é obrigad[oa] a) pagar (agora|hoje|imediatamente)|"
                   r"ser[áa] (processad|negativad|protestad)|cobran[çc]a judicial|advogad|ju[íi]zo|vamos cobrar|"
                   r"se n[ãa]o pagar|n[ãa]o tem escolha|irrespons[áa]vel|culpa sua)", re.IGNORECASE),
        "Desculpa, deixa eu dizer isso de um jeito melhor. Eu estou do seu lado: podemos olhar juntos as opções "
        "que cabem no seu mês, sem pressa e sem pressão. Quer ver?",
    ),
    "promessa_indevida": (
        re.compile(r"(garanto|garantido|garantia de que|com certeza (seu|o) nome|nome limpo (hoje|agora|na hora)|"
                   r"sem juros nenhum|100% de desconto|nunca mais vai|resolve tudo)", re.IGNORECASE),
        "Prefiro não prometer o que eu não controlo. O que eu posso te mostrar são os números reais de cada opção "
        "— parcela, prazo, desconto e quando o atraso é regularizado. Quer ver?",
    ),
    "vazamento_prompt": (
        re.compile(r"(REGRAS INVIOL[ÁA]VEIS|instru[çc][õo]es do sistema|system prompt|meu prompt|"
                   r"antes_do_modelo|before_model|after_model|guardrail_saida)", re.IGNORECASE),
        "Isso é parte de como eu funciono por dentro e não dá para compartilhar. Posso continuar te ajudando com as suas dívidas?",
    ),
    "fora_de_escopo": (
        re.compile(r"(invista em|aplique em|compre (a[çc][õo]es|cripto|bitcoin)|recomendo (um |o )?(empr[ée]stimo|cart[ãa]o) novo|"
                   r"pegue (um )?(empr[ée]stimo|cr[ée]dito) novo)", re.IGNORECASE),
        "Eu não recomendo investimentos nem crédito novo — meu papel é ajudar você a sair do vermelho com o que já existe. "
        "Quer ver os cenários de renegociação?",
    ),
}

# R$ 1.234,56 | R$1234 | 12x | 1,5%
PADRAO_DINHEIRO = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")
PADRAO_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
PADRAO_PRAZO = re.compile(r"\b(\d{1,3})\s?x\b", re.IGNORECASE)


def _para_float(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _resposta_fixa(texto: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=texto)]))


def _redigir_pii(texto: str) -> str:
    """Remove identificadores antes de enviar ao modelo, responder ou registrar logs."""
    texto = PADRAO_CPF.sub("[CPF removido]", texto)
    texto = PADRAO_CARTAO.sub("[número removido]", texto)
    texto = PADRAO_TELEFONE.sub("[telefone removido]", texto)
    return PADRAO_EMAIL.sub("[e-mail removido]", texto)


def _normalizar_texto(texto: str) -> str:
    return " ".join(texto.casefold().strip().split())


def _contem_morse(texto: str) -> bool:
    """Ao menos 4 grupos de ponto/traço; deixa passar reticências e listas comuns."""
    normalizado = texto.replace("–", "-").replace("—", "-")
    tokens = re.split(r"\s+|/", normalizado.strip())
    morse = [token for token in tokens if PADRAO_TOKEN_MORSE.fullmatch(token)]
    return len(morse) >= 4 and sum(len(token) for token in morse) >= 8


def _contem_base64(texto: str) -> bool:
    """Só conta se o token realmente decodificar em texto legível (evita falso positivo em ids/hashes)."""
    for token in re.split(r"\s+", texto.strip()):
        token = token.strip(".,;:!?")
        if not PADRAO_TOKEN_BASE64.fullmatch(token):
            continue
        try:
            decodificado = base64.b64decode(token, validate=True)
        except Exception:
            continue
        if not decodificado:
            continue
        imprimiveis = sum(1 for b in decodificado if 32 <= b <= 126)
        if imprimiveis / len(decodificado) >= 0.85:
            return True
    return False


def _conteudo_codificado(texto: str) -> str | None:
    if _contem_morse(texto):
        return "conteudo_codificado_morse"
    if _contem_base64(texto):
        return "conteudo_codificado_base64"
    return None


def _registrar_bloqueio(state, ctx: Contexto | None, camada: str, tipo: str, trecho: str = "") -> None:
    bloqueios = list(state.get("bloqueios_guardrail") or [])
    bloqueios.append({"camada": camada, "tipo": tipo, "trecho": _redigir_pii(trecho)[:80]})
    state["bloqueios_guardrail"] = bloqueios[-50:]
    log.warning("guardrail %s bloqueou: %s", camada, tipo)
    if ctx is not None:
        try:
            ctx.registrar_evento("guardrail_bloqueio", {"camada": camada, "tipo": tipo})
        except Exception:  # métrica é best-effort
            pass


# ---------- Model Armor (P1; liga com ZERA_MODEL_ARMOR=1 e um template criado no projeto) ----------

def _model_armor(texto: str, camada: str) -> tuple[bool, str] | None:
    """Retorna (bloqueado, categorias) ou None se desligado/indisponível. Nunca derruba a conversa."""
    if os.getenv("ZERA_MODEL_ARMOR") != "1" or not texto:
        return None
    try:
        from google.cloud import modelarmor_v1  # type: ignore

        projeto = os.getenv("GOOGLE_CLOUD_PROJECT")
        local = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        template = os.getenv("ZERA_MODEL_ARMOR_TEMPLATE", "zera-guardrails")
        client = modelarmor_v1.ModelArmorClient(client_options={"api_endpoint": f"modelarmor.{local}.rep.googleapis.com"})
        nome = f"projects/{projeto}/locations/{local}/templates/{template}"
        item = modelarmor_v1.DataItem(text=texto)
        if camada == "entrada":
            resp = client.sanitize_user_prompt(request=modelarmor_v1.SanitizeUserPromptRequest(name=nome, user_prompt_data=item))
        else:
            resp = client.sanitize_model_response(request=modelarmor_v1.SanitizeModelResponseRequest(name=nome, model_response_data=item))
        resultado = resp.sanitization_result
        bloqueado = resultado.filter_match_state == modelarmor_v1.FilterMatchState.MATCH_FOUND
        categorias = ",".join(k for k, v in dict(resultado.filter_results).items()
                              if getattr(v, "filter_match_state", None) == modelarmor_v1.FilterMatchState.MATCH_FOUND) if bloqueado else ""
        return bloqueado, categorias
    except Exception as e:  # sem API/permissão: segue com os guardrails locais
        log.info("Model Armor indisponível (%s); usando guardrails locais", e)
        return None


# ======================================================================
# GUARDRAIL DE ENTRADA  (before_model_callback)
# ======================================================================

def guardrail_entrada(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    state = callback_context.state
    cliente_id = state.get("cliente_id", "cli_001")
    ctx = Contexto.para(cliente_id)

    # function_response também vem com role="user" no Gemini, então exige texto de verdade
    _ultimo = llm_request.contents[-1] if llm_request.contents else None
    novo_turno = bool(_ultimo and _ultimo.role == "user" and any(p.text for p in (_ultimo.parts or [])))

    # última mensagem do usuário (texto)
    ultima_parts, ultima = [], ""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts and any(p.text for p in content.parts):
            ultima_parts = [p for p in content.parts if p.text]
            ultima = " ".join(p.text or "" for p in ultima_parts)
            break

    # redige PII antes de qualquer classificação/log
    for content in llm_request.contents or []:
        if content.role != "user":
            continue
        for part in content.parts or []:
            if part.text:
                novo = _redigir_pii(part.text)
                if novo != part.text:
                    state["pii_redigida"] = state.get("pii_redigida", 0) + 1
                    part.text = novo
    if ultima_parts and novo_turno:
        ultima = " ".join(p.text or "" for p in ultima_parts)
        state["ultima_mensagem_usuario"] = ultima
        state["turno_usuario"] = state.get("turno_usuario", 0) + 1
        # autoriza somente números devolvidos por tools neste turno
        state["ultimos_numeros"] = []

    # 1) BLOQUEIO: fortes indícios de pergunta problemática -> resposta fixa, modelo não é chamado
    if ultima and novo_turno:
        total_bloqueios = len(state.get("bloqueios_guardrail") or []) + state.get("bloqueios_consentimento", 0)
        if total_bloqueios >= LIMITE_BLOQUEIOS_ESCALONAMENTO:
            state["escalonamento_forcado"] = True
            ctx.registrar_evento("escalado_humano", {"motivo": "bloqueios_guardrail_repetidos"})
            return _resposta_fixa(RESPOSTA_ESCALONAMENTO_FORCADO)
        tipo_codificado = _conteudo_codificado(ultima)
        if tipo_codificado:
            _registrar_bloqueio(state, ctx, "entrada", tipo_codificado, "[codificado omitido]")
            return _resposta_fixa(RESPOSTA_CONTEUDO_CODIFICADO)
        armor = _model_armor(ultima, "entrada")
        if armor and armor[0]:
            _registrar_bloqueio(state, ctx, "entrada", f"model_armor:{armor[1]}", ultima)
            return _resposta_fixa(BLOQUEIOS_ENTRADA["injecao_prompt"][1])
        for tipo, (padrao, resposta) in BLOQUEIOS_ENTRADA.items():
            m = padrao.search(ultima)
            if m:
                _registrar_bloqueio(state, ctx, "entrada", tipo, m.group(0))
                return _resposta_fixa(resposta)

    # 2) vulnerabilidade: não bloqueia — muda o tom e pede escalonamento
    instrucoes: list[str] = []
    if PADRAO_VULNERABILIDADE.search(ultima):
        state["vulneravel"] = True
        instrucoes.append("ATENÇÃO: o cliente demonstrou sinal de vulnerabilidade. Acolha em uma frase, NÃO negocie, "
                          "não apresente planos, e ofereça falar com uma pessoa chamando escalar_humano.")

    # 3) contexto: data simulada, memória, acordo e gatilhos pendentes
    instrucoes.append(f"DATA DE HOJE (simulada): {ctx.estado['hoje']}. Cliente: {ctx.perfil.nome} (id {cliente_id}).")
    memoria = ctx.estado.get("memoria") or {}
    if memoria:
        instrucoes.append("MEMÓRIA DO CLIENTE: " + "; ".join(f"{k}={v}" for k, v in memoria.items()))
    if ctx.estado.get("acordo"):
        a = ctx.estado["acordo"]
        instrucoes.append(f"ACORDO ATIVO: {a['status']}, {a['pagas']} parcelas pagas de {a['prazo']}, "
                          f"parcela {a['parcela']:.2f}, próximo vencimento {a['proximo_vencimento']}, "
                          f"respiros usados {a['respiros_usados']} de {a['respiros_max']}.")
    gatilhos = ctx.estado.get("gatilhos_pendentes") or []
    if gatilhos:
        linhas = "; ".join(f"{g['tipo']}: {g['mensagem']}" for g in gatilhos)
        instrucoes.append("GATILHO PENDENTE — você deve INICIAR a conversa explicando o que viu e propondo UMA ação, "
                          "pedindo confirmação: " + linhas + ". Use as tools para citar números.")
        state["gatilho"] = gatilhos
    llm_request.append_instructions(instrucoes)
    return None


# ======================================================================
# FERRAMENTAS  (before_tool / after_tool)
# ======================================================================

def exigir_consentimento(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    nome = tool.name
    if nome == "registrar_consentimento":
        frase = str(args.get("frase_cliente") or "")
        ultima = str(tool_context.state.get("ultima_mensagem_usuario") or "")
        frase_norm, ultima_norm = _normalizar_texto(frase), _normalizar_texto(ultima)
        valido = (
            bool(frase_norm)
            and frase_norm == ultima_norm
            and bool(PADRAO_CONSENTIMENTO_EXPLICITO.search(ultima))
            and not PADRAO_NEGACAO_CONSENTIMENTO.search(ultima)
            and args.get("acao") in ACOES_COM_CONSENTIMENTO
        )
        if not valido:
            tool_context.state["bloqueios_consentimento"] = tool_context.state.get("bloqueios_consentimento", 0) + 1
            return {
                "erro": "consentimento_invalido",
                "instrucao": "Não registre consentimento em nome do cliente. Peça confirmação explícita e use exatamente a última resposta dele.",
            }
    if nome == "amortizar" and not args.get("aplicar"):
        return None  # simulação não precisa de consentimento
    if nome in ACOES_COM_CONSENTIMENTO:
        consentimentos = tool_context.state.get("consentimento") or {}
        if not consentimentos.get(nome):
            tool_context.state["bloqueios_consentimento"] = tool_context.state.get("bloqueios_consentimento", 0) + 1
            return {"erro": "consentimento_ausente", "acao": nome,
                    "instrucao": ("Antes de executar, pergunte ao cliente se ele confirma, espere a resposta, "
                                  "chame registrar_consentimento(acao, frase_cliente) e só então chame esta ação.")}
    return None


def registrar_numeros(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict) -> dict | None:
    permitidos = set(tool_context.state.get("ultimos_numeros") or [])
    if isinstance(tool_response, dict):
        permitidos.update(float(x) for x in tool_response.get("numeros_permitidos", []))
    tool_context.state["ultimos_numeros"] = sorted(permitidos)[-600:]
    if tool.name in ACOES_COM_CONSENTIMENTO and isinstance(tool_response, dict) and tool_response.get("ok"):
        consentimentos = dict(tool_context.state.get("consentimento") or {})
        consentimentos.pop(tool.name, None)          # consentimento é de uso único
        tool_context.state["consentimento"] = consentimentos
    if tool.name in {"acionar_respiro", "amortizar", "fechar_acordo", "escalar_humano"}:
        Contexto.para(tool_context.state.get("cliente_id", "cli_001")).consumir_gatilhos()
        tool_context.state["gatilho"] = []
    return None


# ======================================================================
# GUARDRAIL DE SAÍDA  (after_model_callback)
# ======================================================================

def _valores_na_resposta(texto: str) -> dict[str, list[float]]:
    return {"dinheiro": [_para_float(m) for m in PADRAO_DINHEIRO.findall(texto)],
            "pct": [_para_float(m) for m in PADRAO_PCT.findall(texto)],
            "prazo": [float(m) for m in PADRAO_PRAZO.findall(texto)]}


def _permitido(valor: float, permitidos: list[float], tolerancia: float = 0.6) -> bool:
    return any(abs(valor - p) <= tolerancia for p in permitidos)


def guardrail_saida(callback_context: CallbackContext, llm_response: LlmResponse) -> LlmResponse | None:
    if not llm_response.content or not llm_response.content.parts:
        return None
    texto = "".join(p.text or "" for p in llm_response.content.parts if p.text)
    if not texto:
        return None  # chamadas de tool passam direto
    state = callback_context.state
    ctx = Contexto.para(state.get("cliente_id", "cli_001"))

    # 1) BLOQUEIO: fortes indícios de resposta problemática -> resposta fixa (a do modelo é descartada)
    armor = _model_armor(texto, "saida")
    if armor and armor[0]:
        _registrar_bloqueio(state, ctx, "saida", f"model_armor:{armor[1]}", texto)
        return _resposta_fixa(BLOQUEIOS_SAIDA["pressao_cobranca"][1])
    for tipo, (padrao, resposta) in BLOQUEIOS_SAIDA.items():
        m = padrao.search(texto)
        if m:
            _registrar_bloqueio(state, ctx, "saida", tipo, m.group(0))
            return _resposta_fixa(resposta)

    # 2) PII na saída: o agente nunca deve ecoar identificadores
    novo = _redigir_pii(texto)
    alterado = novo != texto
    if alterado:
        _registrar_bloqueio(state, ctx, "saida", "pii_redigida", "")

    # 3) números: todo R$ / % / prazo precisa existir nas respostas das tools
    permitidos = [float(x) for x in (state.get("ultimos_numeros") or [])]
    achados = _valores_na_resposta(novo)
    estranhos = [v for grupo in ("dinheiro", "pct", "prazo") for v in achados[grupo] if not _permitido(v, permitidos)]
    if estranhos:
        state["alucinacao_numerica"] = state.get("alucinacao_numerica", 0) + len(estranhos)
        _registrar_bloqueio(state, ctx, "saida", "numero_fora_das_tools", ", ".join(str(v) for v in estranhos[:5]))
        if os.getenv("ZERA_STRICT_NUMEROS", "1") == "1":
            for m in list(PADRAO_DINHEIRO.finditer(novo))[::-1]:
                if not _permitido(_para_float(m.group(1)), permitidos):
                    novo = novo[:m.start()] + "[valor a confirmar]" + novo[m.end():]
            for m in list(PADRAO_PCT.finditer(novo))[::-1]:
                if not _permitido(_para_float(m.group(1)), permitidos):
                    novo = novo[:m.start()] + "[percentual a confirmar]" + novo[m.end():]
            for m in list(PADRAO_PRAZO.finditer(novo))[::-1]:
                if not _permitido(float(m.group(1)), permitidos):
                    novo = novo[:m.start()] + "[prazo a confirmar]" + novo[m.end():]
            novo += "\n\n(Alguns valores acima precisam ser confirmados; vou verificar na calculadora antes de seguir.)"
            alterado = True
    return _resposta_fixa(novo) if alterado else None


# compatibilidade com nomes antigos
antes_do_modelo = guardrail_entrada
checar_numeros = guardrail_saida
