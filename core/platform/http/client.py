"""Общий httpx.AsyncClient к OpenRouter.

Раньше каждый LLM-вызов создавал новый `AsyncClient` → TCP+TLS handshake на каждый
запрос (−100…300 мс). Здесь один keep-alive пул на процесс: HTTP/2 (если без прокси),
раздельные connect/read таймауты, закрытие в lifespan API.

L-08: `warmup_openrouter` — лёгкий GET /models на старте, чтобы первый пользовательский
вызов не платил за handshake.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from core.config import get_settings, runtime_openrouter_key
from core.platform.observability import event

logger = logging.getLogger(__name__)

# Короткий connect: не ждать полный llm_timeout на мёртвом сокете.
CONNECT_TIMEOUT_S = 10.0
WRITE_TIMEOUT_S = 10.0
POOL_TIMEOUT_S = 10.0

MAX_CONNECTIONS = 20
MAX_KEEPALIVE_CONNECTIONS = 10
KEEPALIVE_EXPIRY_S = 30.0

# L-08: прогрев не должен ждать полный llm_timeout — только handshake + короткий ответ.
WARMUP_CONNECT_TIMEOUT_S = 5.0
WARMUP_READ_TIMEOUT_S = 15.0

_client: httpx.AsyncClient | None = None
_lock = threading.Lock()


def request_timeout(read_s: float | None = None) -> httpx.Timeout:
    """Таймауты по фазам: connect/write/pool короткие, read — потолок ответа модели."""
    settings = get_settings()
    read = float(read_s if read_s is not None else settings.llm_timeout_s)
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT_S,
        read=read,
        write=WRITE_TIMEOUT_S,
        pool=POOL_TIMEOUT_S,
    )


def _proxy_from_settings() -> str | None:
    proxy = get_settings().openrouter_proxy
    return proxy or None


def make_client(
    *,
    timeout: httpx.Timeout | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    proxy: str | None = None,
    apply_settings_proxy: bool = True,
) -> httpx.AsyncClient:
    """Собрать клиент (для singleton и для ephemeral MockTransport в тестах)."""
    if transport is None and apply_settings_proxy and proxy is None:
        proxy = _proxy_from_settings()
    timeout = timeout or request_timeout()
    limits = httpx.Limits(
        max_connections=MAX_CONNECTIONS,
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=KEEPALIVE_EXPIRY_S,
    )
    # HTTP/2 через HTTP(S)-прокси в httpx недоступен; прямой канал / SOCKS — ок.
    use_http2 = transport is None and not proxy
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "limits": limits,
        "http2": use_http2,
    }
    if transport is not None:
        kwargs["transport"] = transport
    elif proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


def get_http_client() -> httpx.AsyncClient:
    """Singleton; lazy-create если lifespan ещё не вызвал init (CLI / бот без API)."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    with _lock:
        if _client is None or _client.is_closed:
            proxy = _proxy_from_settings()
            use_http2 = not proxy
            _client = make_client(proxy=proxy)
            event(
                logger,
                "ЗАПУСК",
                "http-клиент OpenRouter поднят (keep-alive, http2=%s, proxy=%s); "
                "handshake один раз на пул",
                "да" if use_http2 else "нет",
                "да" if proxy else "нет",
            )
        return _client


async def init_http_client() -> httpx.AsyncClient:
    """Идемпотентно создать singleton в lifespan (сокет — при первом запросе / warmup)."""
    return get_http_client()


def _warmup_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=WARMUP_CONNECT_TIMEOUT_S,
        read=WARMUP_READ_TIMEOUT_S,
        write=WARMUP_CONNECT_TIMEOUT_S,
        pool=WARMUP_CONNECT_TIMEOUT_S,
    )


async def warmup_openrouter() -> bool:
    """L-08: GET /models через общий клиент — TCP+TLS handshake до первого LLM-вызова.

    Ошибка сети/API не пробрасывается: API должен подняться и без OpenRouter.
    Возвращает True, если ответ < 500.
    """
    settings = get_settings()
    api_key = runtime_openrouter_key() or settings.openrouter_api_key
    url = f"{settings.openrouter_base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    client = get_http_client()
    started = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=_warmup_timeout())
        elapsed_ms = (time.perf_counter() - started) * 1000
        ok = resp.status_code < 500
        event(
            logger,
            "ЗАПУСК",
            "OpenRouter прогрет: GET /models → %s за %.0f мс (handshake в keep-alive)",
            resp.status_code,
            elapsed_ms,
            level=logging.INFO if ok else logging.WARNING,
            status_code=resp.status_code,
            warmup_ms=round(elapsed_ms),
        )
        return ok
    except Exception as exc:  # noqa: BLE001 — прогрев не должен валить lifespan
        elapsed_ms = (time.perf_counter() - started) * 1000
        event(
            logger,
            "ЗАПУСК",
            "OpenRouter прогрев не удался за %.0f мс: %s (первый LLM-вызов оплатит handshake)",
            elapsed_ms,
            exc,
            level=logging.WARNING,
            warmup_ms=round(elapsed_ms),
        )
        return False


async def close_http_client() -> None:
    """Закрыть пул соединений (lifespan shutdown)."""
    global _client
    with _lock:
        client = _client
        _client = None
    if client is not None and not client.is_closed:
        await client.aclose()
        event(logger, "ЗАПУСК", "http-клиент OpenRouter закрыт")
