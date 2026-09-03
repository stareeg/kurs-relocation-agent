"""L-01: Server-Timing (db/llm/app) и X-Request-Id на ответах API."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.timing import REQUEST_ID_HEADER, SERVER_TIMING_HEADER, request_timing_middleware
from core.platform.observability.request_timing import (
    begin_request,
    end_request,
    record_db_ms,
    record_llm_ms,
)

_SERVER_TIMING_RE = re.compile(
    r"db;dur=[\d.]+, llm;dur=[\d.]+, app;dur=[\d.]+, total;dur=[\d.]+"
)


def test_server_timing_header_format() -> None:
    timing, token = begin_request("req-test")
    try:
        record_db_ms(12.34)
        record_llm_ms(100.0)
        header = timing.server_timing_header(total_ms=150.0)
    finally:
        end_request(token)
    assert header == "db;dur=12.3, llm;dur=100.0, app;dur=37.7, total;dur=150.0"


def test_record_helpers_noop_without_request() -> None:
    # Вне HTTP — не падаем и ничего не копим.
    record_db_ms(5.0)
    record_llm_ms(5.0)


def _stub_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_timing_middleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/meta")
    def meta() -> dict[str, str]:
        record_db_ms(3.0)
        return {"ok": "1"}

    @app.post("/score")
    async def score() -> dict[str, str]:
        record_llm_ms(25.0)
        await asyncio.sleep(0.01)
        return {"scored": "1"}

    return app


def test_headers_on_three_endpoints() -> None:
    """Проверка L-01: заголовки есть у трёх разных ручек."""
    client = TestClient(_stub_app())
    paths = [("/health", "GET"), ("/meta", "GET"), ("/score", "POST")]
    for path, method in paths:
        response = client.request(method, path)
        assert response.status_code == 200, path
        assert REQUEST_ID_HEADER in response.headers, path
        assert response.headers[REQUEST_ID_HEADER]
        timing = response.headers.get(SERVER_TIMING_HEADER)
        assert timing, path
        assert _SERVER_TIMING_RE.fullmatch(timing), (path, timing)


def test_echoes_incoming_request_id() -> None:
    client = TestClient(_stub_app())
    response = client.get("/health", headers={"X-Request-Id": "client-42"})
    assert response.headers[REQUEST_ID_HEADER] == "client-42"


def test_llm_bucket_reflected_in_server_timing() -> None:
    client = TestClient(_stub_app())
    response = client.post("/score")
    timing = response.headers[SERVER_TIMING_HEADER]
    llm_m = re.search(r"llm;dur=([\d.]+)", timing)
    assert llm_m is not None
    assert float(llm_m.group(1)) >= 25.0


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def test_api_main_registers_timing_middleware() -> None:
    """Реальный app: middleware на месте; три ручки отдают заголовки (без PG lifespan)."""
    from api.main import app

    app.router.lifespan_context = _noop_lifespan  # type: ignore[method-assign]
    with TestClient(app) as client:
        checks = [
            ("GET", "/health", None),
            ("POST", "/auth/logout", None),
            ("POST", "/auth/token", {"token": "nope"}),
        ]
        for method, path, body in checks:
            response = client.request(method, path, json=body)
            assert REQUEST_ID_HEADER in response.headers, path
            assert SERVER_TIMING_HEADER in response.headers, path
            assert _SERVER_TIMING_RE.fullmatch(response.headers[SERVER_TIMING_HEADER]), path


def test_begin_request_wall_clock() -> None:
    timing, token = begin_request()
    try:
        time.sleep(0.01)
        header = timing.server_timing_header()
    finally:
        end_request(token)
    total_m = re.search(r"total;dur=([\d.]+)", header)
    assert total_m is not None
    assert float(total_m.group(1)) >= 10.0
