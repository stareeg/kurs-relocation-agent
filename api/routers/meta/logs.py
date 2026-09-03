"""Логи: GET /api/logs/bundle → инцидент-бандл, POST /api/logs/frontend → приём фронтовых
ошибок из error-capture.ts, RUM-меток из rum.ts, снимка окружения браузера (kind=client_env)
и хелсчека парсера расширения (kind=extension_parse → тег «РАСШИРЕНИЕ»).

Сборка бандла — в core/platform/repo/log_bundle.py, роутер только отдаёт StreamingResponse.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from api.schemas import FrontendLogBatch
from api.security import AccountContext, require_account_context
from core.platform.observability import event
from core.platform.repo.log_bundle import (
    DEFAULT_WINDOW_HOURS,
    MAX_WINDOW_HOURS,
    build_log_bundle_zip,
)

logger = logging.getLogger(__name__)
frontend_logger = logging.getLogger("frontend")

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Кольцевой буфер на клиенте капается на ~200 записей — здесь дополнительный жёсткий кап на
# случай, если фронт когда-нибудь пришлёт буфер без обрезки (не доверяем клиенту размер).
_MAX_BATCH = 200


def _frontend_level(level: str) -> int:
    name = level.upper()
    if name == "INFO":
        return logging.INFO
    if name == "WARNING":
        return logging.WARNING
    return logging.ERROR


def _frontend_category(kind: str) -> str:
    if kind == "extension_parse":
        return "РАСШИРЕНИЕ"
    if kind.startswith("rum_"):
        return "RUM"
    return "ФРОНТ"


@router.get("/bundle")
async def get_log_bundle(
    account: AccountContext = Depends(require_account_context),
    hours: int = Query(
        DEFAULT_WINDOW_HOURS,
        ge=1,
        le=MAX_WINDOW_HOURS,
        description="Глубина выборки в часах (по умолчанию трое суток).",
    ),
) -> StreamingResponse:
    """Инцидент-бандл строго по своему аккаунту — без операторского исключения."""
    data = await build_log_bundle_zip(account.account_id, window_hours=hours)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M")
    headers = {"Content-Disposition": f'attachment; filename="support_bundle-{stamp}.zip"'}
    return StreamingResponse(iter([data]), media_type="application/zip", headers=headers)


@router.post("/frontend", response_class=Response, status_code=204)
async def post_frontend_logs(batch: FrontendLogBatch) -> Response:
    """Записать пачку фронтовых ошибок/RUM в витрину `copilot_logs` (logger="frontend").

    Явный `Response` + `response_class=Response` — иначе FastAPI 0.115+ падает на старте
    с «Status code 204 must not have a response body» (тело запроса путает с ответом).
    """
    _ingest_frontend_logs(batch)
    return Response(status_code=204)


def _ingest_frontend_logs(batch: FrontendLogBatch) -> None:
    for entry in batch.entries[:_MAX_BATCH]:
        event(
            frontend_logger,
            _frontend_category(entry.kind),
            entry.message,
            level=_frontend_level(entry.level),
            kind=entry.kind,
            client_ts=entry.ts,
            url=entry.url,
            endpoint=entry.endpoint,
            status=entry.status,
            duration_ms=entry.duration_ms,
            stack=entry.stack,
            parse_method=entry.parse_method,
            config_version=entry.config_version,
            config_origin=entry.config_origin,
        )
