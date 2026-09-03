"""HTTP middleware L-01: `X-Request-Id` + `Server-Timing` (db / llm / app / total)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response

from core.platform.observability.request_timing import begin_request, end_request

REQUEST_ID_HEADER = "X-Request-Id"
SERVER_TIMING_HEADER = "Server-Timing"


async def request_timing_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Проставить корреляционный id и разбивку latency в заголовках ответа."""
    incoming = request.headers.get("x-request-id") or request.headers.get("X-Request-Id")
    timing, token = begin_request(incoming.strip() if incoming else None)
    request.state.request_id = timing.request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        end_request(token)
        raise
    total_ms = (time.perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = timing.request_id
    response.headers[SERVER_TIMING_HEADER] = timing.server_timing_header(total_ms)
    end_request(token)
    return response
