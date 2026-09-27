#!/usr/bin/env bash
# Smoke test de produção — valida o serviço de ponta a ponta, inclusive Gemini e o HITL do botão Contratar.
#   infra/smoke_prod.sh https://zera-xxxx-uc.a.run.app
set -euo pipefail
URL="${1:?uso: infra/smoke_prod.sh <URL do Cloud Run>}"
URL="${URL%/}"
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
ok() { echo "  ok  $*"; }
falha() { echo "  FALHA $*"; exit 1; }

echo ">> 1) health / ready"
H=$(curl -sf "$URL/health") || falha "health"; echo "$H" | j "d['modelo'], d['fonte'], d['estado'], d['versao'], d['otel']" | sed 's/^/     /'
R=$(curl -sf "$URL/ready") || falha "ready (fonte de dados não responde)"; echo "$R" | j "d['perfis'], d['fonte']" | sed 's/^/     perfis, fonte: /'
[ "$(echo "$R" | j "d['ok']")" = "True" ] && ok "ready" || falha "ready ok=false"

echo ">> 2) perfis reais do cluster-alvo"
C=$(curl -sf "$URL/v1/clientes") || falha "clientes"
CID=$(echo "$C" | j "d['perfis'][0]['cliente_id']"); NOME=$(echo "$C" | j "d['perfis'][0]['nome']"); FONTE=$(echo "$C" | j "d['perfis'][0]['fonte']")
ok "primeiro perfil: $NOME ($CID) · fonte $FONTE · $(echo "$C" | j "len(d['perfis'])") perfis"
P=$(curl -sf "$URL/v1/clientes/$CID/perfil") || falha "perfil"
echo "$P" | j "'renda: %s | %s | dividas: %d | parcela max: %s' % (d['renda_media'], d['renda_fonte'], len(d['dividas']), d['capacidade']['parcela_maxima'])" | sed 's/^/     /'

echo ">> 3) proatividade (balão) e experiência guiada (0 tokens)"
curl -sf -X POST "$URL/v1/clientes/$CID/preferencias" -H 'Content-Type: application/json' -d '{"analisar":true,"momentos":true,"recomendar":true,"avisar":true,"open_finance":false}' >/dev/null
PR=$(curl -sf "$URL/v1/clientes/$CID/proativa"); echo "$PR" | j "'silent=%s trigger=%s reason=%s' % (d.get('silent'), d.get('trigger'), d.get('reason'))" | sed 's/^/     /'
E=$(curl -sf -X POST "$URL/v1/clientes/$CID/experiencia/evento" -H 'Content-Type: application/json' -d '{"acao":"START","payload":{},"sessao_id":"smoke"}')
echo "$E" | j "'state=%s type=%s' % (d['state'], d['response_type'])" | sed 's/^/     /'

echo ">> 4) chat: abertura determinística + Gemini via Vertex AI (stream NDJSON)"
S="smoke-$RANDOM"
I=$(curl -sf "$URL/chat/inicio?cliente_id=$CID&sessao_id=$S") || falha "chat/inicio"; ok "inicio: $(echo "$I" | j "d['texto'][:70]")…"
curl -sf -X POST "$URL/chat/stream" -H 'Content-Type: application/json' -d "{\"cliente_id\":\"$CID\",\"sessao_id\":\"$S\",\"mensagem\":\"Quais opções cabem no meu bolso?\"}" > /tmp/zera_stream.ndjson || falha "chat/stream"
grep -q '"tipo": "erro"' /tmp/zera_stream.ndjson && { echo "     $(grep '"tipo": "erro"' /tmp/zera_stream.ndjson | head -c 300)"; falha "o agente devolveu erro (credencial/modelo/location? veja a dica acima)"; }
grep -q '"tipo": "tool_call"' /tmp/zera_stream.ndjson && ok "tools chamadas: $(grep -o '"nome": "[a-z_]*"' /tmp/zera_stream.ndjson | sort -u | tr '\n' ' ')" || echo "     (sem tool neste turno — o modelo respondeu direto)"
grep -q '"tipo": "texto"' /tmp/zera_stream.ndjson && ok "texto do Gemini recebido" || falha "sem texto do modelo"
grep -q '"tipo": "card", "bloco": {"tipo": "cenarios"' /tmp/zera_stream.ndjson && ok "card de cenários" || echo "     (sem card de cenários neste turno)"

echo ">> 5) botão Contratar -> card HITL -> recusa (nada contratado)"
CEN=$(grep -o '"id": "C[0-9]*"' /tmp/zera_stream.ndjson | head -1 | grep -o 'C[0-9]*' || true)
if [ -n "$CEN" ]; then
  HT=$(curl -sf -X POST "$URL/chat/contratar" -H 'Content-Type: application/json' -d "{\"cliente_id\":\"$CID\",\"sessao_id\":\"$S\",\"cenario_id\":\"$CEN\"}") || falha "chat/contratar"
  RID=$(echo "$HT" | j "d['hitl']['request_id']"); ok "card HITL $(echo "$HT" | j "d['hitl']['titulo']") ($RID)"
  curl -sf -X POST "$URL/chat/confirmar/stream" -H 'Content-Type: application/json' -d "{\"cliente_id\":\"$CID\",\"sessao_id\":\"$S\",\"request_id\":\"$RID\",\"confirmed\":false,\"frase\":\"não\"}" | grep -q "nada foi contratado" && ok "recusa respeitada (nada contratado)" || falha "recusa"
else
  echo "     (sem cenário no stream para testar o botão)"
fi
echo ">> 6) reset do perfil de smoke (LGPD: apaga estado)"
curl -sf -X POST "$URL/reset/$CID" >/dev/null && ok "reset"
echo; echo "SMOKE OK — $URL"
