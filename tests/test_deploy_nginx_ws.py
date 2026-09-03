"""Конфиги реверс-прокси прода: то, что ломается только за nginx/Caddy и никогда локально.

Э16.6 — WebSocket-апгрейд (ниже). Э18 добавил сюда ещё два дефекта того же класса: SPA-маршрут,
перекрытый одноимённым каталогом из `public/` (Д2), и сжатие, которое есть в nginx, но не
доезжает через Caddy (Д3). Все три невидимы на дев-прокси Vite, поэтому держатся тестом.

--- Э16.6 ---
Reverse-proxy фронта не должен молча терять WebSocket-апгрейд.

Партия «Хрюши и Волки» ходит по `/api/multiplayer/ws/{room_code}`. Общий `location /api/`
обслуживает REST и SSE и для этого зачищает `Connection` (`proxy_set_header Connection "";`) —
для WS это ломает handshake насмерть: `Upgrade` — hop-by-hop заголовок, nginx его апстриму не
пересылает, uvicorn не может ответить `101 Switching Protocols`, а браузер получает мгновенный
close. На проде это выглядело как «переподключение (N/8)…» до исчерпания backoff; локально не
воспроизводилось, потому что дев-прокси Vite настроен верно (`vite.config.ts`, `ws: true`).

Тест держит конфиг, а не поведение: поднять настоящий nginx-образ в CI дорого, а вся правка —
несколько директив, которые легко снести при следующем редактировании файла.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NGINX_CONF = ROOT / "frontend" / "nginx.conf"

WS_LOCATION_PREFIX = "/api/multiplayer/ws/"


def _conf() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _ws_location_body(conf: str) -> str:
    """Тело `location … /api/multiplayer/ws/ { … }` — по балансу фигурных скобок."""
    match = re.search(rf"location\s+[^\s{{]*\s*{re.escape(WS_LOCATION_PREFIX)}\s*{{", conf)
    assert match is not None, (
        f"в {NGINX_CONF.name} нет отдельного location для {WS_LOCATION_PREFIX} — "
        "WS-апгрейд снова уйдёт в общий /api/, который зачищает Connection"
    )
    start = match.end()
    depth = 1
    for i in range(start, len(conf)):
        if conf[i] == "{":
            depth += 1
        elif conf[i] == "}":
            depth -= 1
            if depth == 0:
                return conf[start:i]
    raise AssertionError("незакрытый блок location для WS")


def test_ws_location_exists_and_forwards_upgrade() -> None:
    body = _ws_location_body(_conf())
    assert "proxy_set_header Upgrade $http_upgrade;" in body, (
        "без явного проброса Upgrade заголовок не доедет до uvicorn (hop-by-hop)"
    )
    assert re.search(r"proxy_set_header\s+Connection\s+\$connection_upgrade;", body), (
        "Connection должен приходить из map $http_upgrade, а не быть строкой: иначе "
        "не-WS запрос под тем же location получит мусорный 'upgrade'"
    )
    assert "proxy_http_version 1.1;" in body, "апгрейд возможен только на HTTP/1.1"


def test_ws_map_declared() -> None:
    conf = _conf()
    match = re.search(r"map\s+\$http_upgrade\s+\$connection_upgrade\s*{([^}]*)}", conf)
    assert match is not None, (
        "нет `map $http_upgrade $connection_upgrade` — переменная из location будет пустой"
    )
    body = match.group(1)
    assert "default upgrade;" in body
    assert "close;" in body, "запрос без Upgrade должен получать Connection: close"
    assert match.start() < conf.index("server {"), (
        "map — директива уровня http{}, объявлять её нужно до server{} "
        "(файл подключается из conf.d/*.conf, то есть уже внутри http{})"
    )


def test_ws_location_repeats_timeouts() -> None:
    """Таймауты наследуются от server/http, а не от соседнего `location /api/`.

    С дефолтным `proxy_read_timeout 60s` nginx рвал бы простаивающий сокет: в фазе `reveal`
    таймер фазы снимается и сервер перестаёт слать `state_public`, живым соединение держит
    только клиентский `ping` (`wolves-ws.ts`, раз в 25 с). Симптом был бы неотличим от
    исходного бага с Upgrade, поэтому фиксируем явно.
    """
    body = _ws_location_body(_conf())
    read_timeout = re.search(r"proxy_read_timeout\s+(\d+)s;", body)
    assert read_timeout is not None, "в WS-location нет proxy_read_timeout"
    assert int(read_timeout.group(1)) >= 300, "таймаут короче 5 минут рвёт живую партию"
    assert "proxy_buffering off;" in body


def test_shared_api_location_still_clears_connection() -> None:
    """Общий /api/ не трогаем: `Connection ""` там нужен keep-alive к апстриму и SSE."""
    conf = _conf()
    api_start = re.search(r"location\s+/api/\s*{", conf)
    assert api_start is not None
    tail = conf[api_start.end() : conf.index("}", api_start.end())]
    assert 'proxy_set_header Connection "";' in tail


def test_spa_fallback_does_not_try_directories() -> None:
    """Д2: `$uri/` в SPA-фоллбэке отдаёт 403 на маршрутах, у которых есть папка в public/.

    `frontend/public/multiplayer/` (арт игры) Vite кладёт в корень сборки настоящим каталогом.
    С `try_files $uri $uri/ /index.html` nginx матчит его на `$uri/`, редиректит
    /multiplayer → /multiplayer/, не находит там index.html и при autoindex off отдаёт 403 —
    ломая закладку, F5 и deep-link ?join=CODE. Кликом внутри SPA не воспроизводится: запроса
    к nginx нет.
    """
    conf = _conf()
    match = re.search(r"location\s+/\s*{([^}]*)}", conf)
    assert match is not None, "нет SPA-фоллбэка `location / {}`"
    body = match.group(1)
    try_files = re.search(r"try_files\s+([^;]+);", body)
    assert try_files is not None, "в SPA-фоллбэке нет try_files"
    parts = try_files.group(1).split()
    assert "$uri/" not in parts, (
        "`$uri/` возвращает 403 на маршрутах, одноимённых с каталогом в frontend/public/ "
        "(сейчас это /multiplayer). Фоллбэк должен быть `try_files $uri /index.html`"
    )
    assert parts[-1] == "/index.html", "последним звеном обязан быть index.html"


def test_public_asset_dir_still_shadows_a_route() -> None:
    """Пока такой каталог существует, тест выше обязателен — фиксируем саму коллизию.

    Если арт когда-нибудь переедет в /assets/, этот тест упадёт и подскажет, что запрет
    `$uri/` можно пересмотреть.
    """
    public_dir = ROOT / "frontend" / "public"
    collisions = sorted(p.name for p in public_dir.iterdir() if p.is_dir()) if public_dir.is_dir() else []
    assert "multiplayer" in collisions, (
        "frontend/public/multiplayer/ больше нет — перечитать Д2: возможно, `$uri/` "
        "в SPA-фоллбэке снова безопасен"
    )


def test_dockerfile_runs_single_uvicorn_worker() -> None:
    """Э20.5: `multiplayer._HUB` (столы, live-партии, таймеры фаз) — в памяти процесса.

    С `--workers > 1` комнаты разъедутся по процессам и WS попадёт не в тот воркер — стол
    «то работает, то нет». Инвариант невидимый: пока флага нет, всё сходится, и первый же
    «оптимизирующий» коммит его снимет молча.
    """
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    cmd = re.search(r"^CMD\s+(.+)$", dockerfile, re.MULTILINE)
    assert cmd is not None, "в deploy/Dockerfile нет строки CMD"
    assert "--workers" not in cmd.group(1), (
        "uvicorn с несколькими воркерами ломает «Мультиплеер» (in-process хаб столов) — "
        "см. core/domains/multiplayer/README.md, «Один воркер»"
    )
    # WEB_CONCURRENCY тоже включает несколько воркеров у uvicorn[standard].
    assert not re.search(r"^ENV\s+WEB_CONCURRENCY", dockerfile, re.MULTILINE), (
        "WEB_CONCURRENCY в Dockerfile поднимет несколько воркеров — тот же инвариант Э20.5"
    )


def test_caddy_compresses() -> None:
    """Д3: gzip из nginx до браузера не доезжает — сжимать обязан внешний Caddy.

    Замер на проде: тот же чанк через nginx приходит с `Content-Encoding: gzip`, через
    Caddy — без него и в полный размер файла.
    """
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    encode = re.search(r"^\s*encode\s+(.+)$", caddyfile, re.MULTILINE)
    assert encode is not None, (
        "в deploy/Caddyfile нет директивы `encode` — бандл поедет к браузеру несжатым"
    )
    assert "gzip" in encode.group(1), "минимум gzip: его понимают все браузеры"
