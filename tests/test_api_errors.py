"""A-15: единый конверт ошибок — 5 типовых статусов + форма тела."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import (
    error_content,
    error_envelope,
    http_status_for,
    to_http,
    to_response,
)
from api.main import app as main_app
from core.kernel.errors import (
    DomainError,
    InvalidInput,
    LlmError,
    NotFound,
    RateLimited,
    StorageUnavailable,
)

# Пять канонических раскладок из плана A-15.
_CASES: list[tuple[type[DomainError], str, int, str]] = [
    (InvalidInput, "пустой вход", 400, "invalid_input"),
    (NotFound, "вакансия не найдена", 404, "not_found"),
    (RateLimited, "лимит OpenRouter", 429, "rate_limited"),
    (LlmError, "OPENROUTER_API_KEY не задан", 503, "llm_error"),
    (StorageUnavailable, "Postgres недоступен", 503, "storage_unavailable"),
]


@pytest.mark.parametrize(("cls", "message", "status", "code"), _CASES)
def test_five_typical_error_statuses(
    cls: type[DomainError], message: str, status: int, code: str
) -> None:
    exc = cls(message)
    assert http_status_for(exc) == status
    assert exc.code == code

    envelope = error_envelope(exc)
    assert envelope == {"code": code, "message": message, "details": {}}

    http_exc = to_http(exc)
    assert http_exc.status_code == status
    assert http_exc.detail == envelope

    assert error_content(exc) == {"detail": envelope}
    assert to_response(exc).status_code == status


def test_domain_error_handler_returns_envelope() -> None:
    """Непойманный DomainError → конверт A-15, не безликий 500."""
    probe = FastAPI()
    probe.add_exception_handler(DomainError, main_app.exception_handlers[DomainError])

    @probe.get("/boom")
    async def boom() -> None:
        raise InvalidInput("нужен текст вакансии")

    client = TestClient(probe, raise_server_exceptions=False)
    res = client.get("/boom")
    assert res.status_code == 400
    assert res.json() == {
        "detail": {
            "code": "invalid_input",
            "message": "нужен текст вакансии",
            "details": {},
        }
    }


def test_to_http_preserves_details() -> None:
    exc = InvalidInput("плохо", details={"field": "transcript"})
    assert to_http(exc).detail["details"] == {"field": "transcript"}
