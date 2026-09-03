"""Конфиг селекторов парсера hh — расширение чинит вёрстку без перевыпуска zip.

`GET /api/opportunities/parser-config/hh`. Бэкенд сам к hh.ru не ходит: отдаёт
строки CSS из репозитория или горячего оверрайда в Postgres.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from api.schemas.parser_config import ExtensionRuntimeConfigOut, ParserSelectorsConfigOut
from core.domains.opportunities.extension_runtime_config import (
    ExtensionRuntimeConfig,
    get_extension_runtime_config,
)
from core.domains.opportunities.parser_config import (
    SOURCE_HH,
    HhSelectorsConfig,
    get_hh_selectors,
)
from core.platform.observability import event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/opportunities/parser-config", tags=["parser-config"])

_CACHE_HEADERS = {"Cache-Control": "no-cache"}


def _etag_for(cfg: HhSelectorsConfig) -> str:
    return f'"hh-{cfg.version}"'


def _not_modified(request: Request, etag: str) -> bool:
    inm = request.headers.get("if-none-match", "")
    return etag in (tag.strip() for tag in inm.split(",") if tag.strip())


def hh_parser_config_response(request: Request, cfg: HhSelectorsConfig) -> Response:
    etag = _etag_for(cfg)
    not_modified = _not_modified(request, etag)
    event(
        logger,
        "РАСШИРЕНИЕ",
        "конфиг парсера отдан: %s v%s origin=%s%s",
        SOURCE_HH,
        cfg.version,
        cfg.origin,
        " 304" if not_modified else "",
        event="parser_config_served",
        source=SOURCE_HH,
        version=cfg.version,
        origin=cfg.origin,
        not_modified=not_modified,
    )
    headers = {"ETag": etag, **_CACHE_HEADERS}
    if not_modified:
        return Response(status_code=304, headers=headers)
    body = ParserSelectorsConfigOut(
        version=cfg.version,
        updated_at=cfg.updated_at,
        origin=cfg.origin,
        selectors=cfg.selectors,
        patterns=cfg.patterns,
    )
    return JSONResponse(content=body.model_dump(mode="json"), headers=headers)


@router.get("/hh", response_model=ParserSelectorsConfigOut)
async def get_hh_parser_config(request: Request) -> Response:
    """Актуальные CSS-селекторы hh: ETag + no-cache, тело только если версия сменилась."""
    return hh_parser_config_response(request, await get_hh_selectors())


@router.get("/extension", response_model=ExtensionRuntimeConfigOut)
async def get_extension_config(request: Request) -> Response:
    """Рантайм-конфиг расширения: флаги (аварийный стоп), тюнинг темпа/таймаутов, селекторы
    отклика. ETag + no-cache, тело только если версия сменилась — расширение тянет по alarm'у
    раз в 30 мин и держит в chrome.storage.local, фиксы не требуют переустановки zip."""
    cfg: ExtensionRuntimeConfig = await get_extension_runtime_config()
    etag = f'"ext-runtime-{cfg.version}"'
    not_modified = _not_modified(request, etag)
    event(
        logger,
        "РАСШИРЕНИЕ",
        "рантайм-конфиг отдан: v%s origin=%s%s",
        cfg.version,
        cfg.origin,
        " 304" if not_modified else "",
        event="extension_runtime_config_served",
        version=cfg.version,
        origin=cfg.origin,
        not_modified=not_modified,
    )
    headers = {"ETag": etag, **_CACHE_HEADERS}
    if not_modified:
        return Response(status_code=304, headers=headers)
    body = ExtensionRuntimeConfigOut(
        version=cfg.version,
        updated_at=cfg.updated_at,
        origin=cfg.origin,  # type: ignore[arg-type]
        flags=cfg.flags,
        tuning=cfg.tuning,
        apply_selectors=cfg.apply_selectors,
        parse_selectors=cfg.parse_selectors,
        text_signals=cfg.text_signals,
    )
    return JSONResponse(content=body.model_dump(mode="json"), headers=headers)
