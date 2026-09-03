"""L-38: GET /api/session — лёгкий пинг сессии для AuthProvider, без БД и без логики.

Реализован фактически в рамках R-12 (замена ручки `/api/hitl/pending`); здесь —
регрессия на форму ответа и на то, что ручка не требует БД (noop lifespan).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.security import require_account


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def client() -> TestClient:
    from api.main import app

    app.router.lifespan_context = _noop_lifespan  # type: ignore[method-assign]
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_account, None)


def test_session_authed_without_db(client: TestClient) -> None:
    client.app.dependency_overrides[require_account] = lambda: None
    response = client.get("/api/session")
    assert response.status_code == 200
    assert response.json() == {"authed": True}


def test_session_unauthorized_without_valid_cookie_or_key(client: TestClient) -> None:
    async def _deny() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Не авторизован")

    client.app.dependency_overrides[require_account] = _deny
    response = client.get("/api/session")
    assert response.status_code == 401
