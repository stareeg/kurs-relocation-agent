#!/bin/sh
# Где рвётся WebSocket-апгрейд партии «Хрюши и Волки» (/api/multiplayer/ws/).
#
# Запускать НА ВМ:
#   scp -i secrets/id_ed25519 deploy/ws_probe.sh deploy@<host>:/tmp/ && \
#   ssh -i secrets/id_ed25519 deploy@<host> "sh /tmp/ws_probe.sh"
#
# Как читать:
#   101 — апгрейд прошёл (дальше приложение само закроет соединение с 4401 по auth —
#         это ожидаемо, зонд не логинится);
#   404 — заголовок Upgrade потерян по дороге: до FastAPI запрос доехал обычным GET,
#         а `@router.websocket(...)` на такой не матчится. Ровно этот симптом давал
#         `proxy_set_header Connection "";` в общем `location /api/` (Э16.1);
#   502/504 — апстрим не отвечает, к апгрейду отношения не имеет.
#
# Здоровая цепочка = 101 на всех трёх строках.
set -u

DOMAIN="${DOMAIN:?укажите DOMAIN, например DOMAIN=example.com}"
ROOM="${ROOM:-AAAAAA}"

probe() {
  code=$(curl -s -o /dev/null -w '%{http_code}' --http1.1 -m 5 \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    "$2")
  echo "$1 -> $code"
}

probe 'api напрямую ' "http://127.0.0.1:8000/api/multiplayer/ws/${ROOM}"
probe 'через nginx  ' "http://127.0.0.1:5173/api/multiplayer/ws/${ROOM}"
probe 'через caddy  ' "https://${DOMAIN}/api/multiplayer/ws/${ROOM}"
echo "контроль /health -> $(curl -s -o /dev/null -w '%{http_code}' -m 5 "https://${DOMAIN}/health")"
