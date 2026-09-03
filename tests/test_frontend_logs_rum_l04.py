"""L-04: POST /api/logs/frontend принимает RUM (INFO) и кладёт в витрину с категорией RUM."""

from __future__ import annotations

import logging

from api.routers.meta.logs import _frontend_category, _frontend_level


def test_rum_kind_maps_to_rum_category() -> None:
    assert _frontend_category("rum_ttfb") == "RUM"
    assert _frontend_category("rum_lcp") == "RUM"
    assert _frontend_category("http") == "ФРОНТ"
    assert _frontend_category("extension_parse") == "РАСШИРЕНИЕ"


def test_info_level_for_rum() -> None:
    assert _frontend_level("INFO") == logging.INFO
    assert _frontend_level("WARNING") == logging.WARNING
    assert _frontend_level("ERROR") == logging.ERROR
    assert _frontend_level("debug") == logging.ERROR


def test_post_frontend_rum_entry_emits_info(caplog) -> None:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers.meta import logs as logs_router

    @asynccontextmanager
    async def _noop(_app: FastAPI):
        yield

    app = FastAPI(lifespan=_noop)
    app.include_router(logs_router.router)

    with (
        caplog.at_level(logging.INFO, logger="frontend"),
        TestClient(app) as client,
    ):
        res = client.post(
            "/api/logs/frontend",
            json={
                "entries": [
                    {
                        "ts": "2026-07-26T10:00:00Z",
                        "level": "INFO",
                        "kind": "rum_ttfb",
                        "message": "клик → первый байт · chat",
                        "duration_ms": 180,
                        "endpoint": "/api/chat/stream",
                    }
                ]
            },
        )
        assert res.status_code == 204

    assert any("первый байт" in r.message and r.levelno == logging.INFO for r in caplog.records)


def test_post_frontend_parse_health_keeps_method_fields(caplog) -> None:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers.meta import logs as logs_router

    @asynccontextmanager
    async def _noop(_app: FastAPI):
        yield

    app = FastAPI(lifespan=_noop)
    app.include_router(logs_router.router)

    with (
        caplog.at_level(logging.WARNING, logger="frontend"),
        TestClient(app) as client,
    ):
        res = client.post(
            "/api/logs/frontend",
            json={
                "entries": [
                    {
                        "ts": "2026-08-25T10:00:00Z",
                        "level": "WARNING",
                        "kind": "extension_parse",
                        "message": "Парсер hh/vacancy: пустой текст",
                        "url": "https://hh.ru/vacancy/1",
                        "endpoint": "extension:hh/vacancy",
                        "parse_method": "structural",
                        "config_version": 2,
                        "config_origin": "server",
                    }
                ]
            },
        )
        assert res.status_code == 204

    rec = next(r for r in caplog.records if "пустой текст" in r.message)
    assert rec.levelno == logging.WARNING
    assert getattr(rec, "parse_method", None) == "structural"
    assert getattr(rec, "config_version", None) == 2
    assert getattr(rec, "config_origin", None) == "server"
    assert getattr(rec, "url", None) == "https://hh.ru/vacancy/1"
