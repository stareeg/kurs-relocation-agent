"""Доменная ошибка → HTTP-конверт.

Сценарии в `core/app` и `core/domains` не знают про FastAPI и бросают `kernel.errors.*`.
Роутер либо пишет `raise to_http(exc) from exc`, либо просто пробрасывает `DomainError` —
центральный handler в `api.main` отдаёт тот же конверт.

Конверт ответа::

    {"detail": {"code": "invalid_input", "message": "...", "details": {}}}

Канон статусов: пустой/битый вход → 400, не найдено → 404, лимит → 429,
нет ключа / LLM / хранилище → 503.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from core.kernel.errors import (
    DomainError,
    InternalError,
    InvalidInput,
    LlmError,
    NotFound,
    RateLimited,
    StorageUnavailable,
    Unprocessable,
    UpstreamError,
)

_STATUS: dict[type[DomainError], int] = {
    InvalidInput: 400,
    Unprocessable: 422,
    NotFound: 404,
    RateLimited: 429,
    InternalError: 500,
    UpstreamError: 502,
    StorageUnavailable: 503,
    LlmError: 503,
}


def http_status_for(exc: DomainError) -> int:
    """Статус для доменной ошибки; незнакомый подтип — 503 (сервис временно не может)."""
    for kind, status in _STATUS.items():
        if isinstance(exc, kind):
            return status
    return 503


def error_envelope(exc: DomainError) -> dict[str, Any]:
    """Тело ``detail`` единого конверта: code + message + details."""
    return {
        "code": exc.code,
        "message": exc.message,
        "details": dict(exc.details),
    }


def error_content(exc: DomainError) -> dict[str, Any]:
    """Полное JSON-тело ответа: ``{"detail": {code, message, details}}``."""
    return {"detail": error_envelope(exc)}


def to_http(exc: DomainError) -> HTTPException:
    """`raise to_http(exc) from exc` — форма маппинга в тонком роутере."""
    return HTTPException(status_code=http_status_for(exc), detail=error_envelope(exc))


def to_response(exc: DomainError) -> JSONResponse:
    """Ответ для exception handler / мест без raise HTTPException."""
    return JSONResponse(status_code=http_status_for(exc), content=error_content(exc))


__all__ = [
    "error_content",
    "error_envelope",
    "http_status_for",
    "to_http",
    "to_response",
]
