"""HTTP-гейт /api/admin: member → 403, owner → 200 (сервис замокан)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.meta import admin as admin_router
from api.security import AccountContext, require_account_context
from core.platform.admin.models import AdminSummary, AdminUserDetail, AdminUserRow, FunnelCounts

_MEMBER = AccountContext(
    account_id=2, telegram_user_id=20, telegram_username="friend", role="member"
)
_OWNER = AccountContext(account_id=1, telegram_user_id=10, telegram_username="op", role="owner")

# Тело-надмножество: pydantic игнорирует лишние поля, поэтому одного словаря хватает любой
# ручке с body. Гейт всё равно срабатывает раньше валидации тела (зависимости решаются до
# разбора body), но с телом тест не зависит и от этого порядка.
_ANY_BODY = {
    "text": "тест",
    "key": "sk-or-v1-x",
    "label": None,
    "reason": "тест",
    "note": "kate",
    "role": "member",
    "days": 30,
    "kind": "tg_push",
    "usd": 5,
    "channel": "user",
}

# Подстановки path-параметров: id аккаунта-жертвы и id заявки. Незнакомый параметр → "1",
# чтобы новая ручка не роняла обход раньше, чем проверит гейт.
_PATH_VALUES = {"account_id": "2", "request_id": "1"}


def _admin_calls() -> list[tuple[str, str]]:
    """Все ручки /api/admin из самого роутера, а не из списка руками.

    Список руками означал, что новую ручку можно добавить без гейта и никто не заметит.
    Здесь перечень берётся из `router.routes`: появилась ручка — она сразу обязана отдавать
    403 для member, иначе тест красный.
    """
    calls: list[tuple[str, str]] = []
    for route in admin_router.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for name, value in _PATH_VALUES.items():
            path = path.replace("{" + name + "}", value)
        path = re.sub(r"\{[^}]+\}", "1", path)
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            calls.append((method, path))
    return calls


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _app() -> FastAPI:
    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(admin_router.router)
    return app


def test_admin_router_exposes_routes() -> None:
    """Обход пустой — значит тест гейта ничего не проверяет; ловим это отдельно."""
    calls = _admin_calls()
    assert len(calls) >= 10, calls
    assert ("GET", "/api/admin/summary") in calls
    assert ("GET", "/api/admin/overview") not in calls


def test_member_gets_403_on_every_admin_path() -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _MEMBER
    with TestClient(app) as client:
        for method, path in _admin_calls():
            response = client.request(method, path, json=_ANY_BODY)
            assert response.status_code == 403, (method, path, response.status_code, response.text)


def test_owner_gets_200_on_summary_and_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _OWNER
    monkeypatch.setattr(admin_router, "ensure_all_system_admin_friendships_throttled", AsyncMock())
    monkeypatch.setattr(admin_router, "load_summary", AsyncMock(return_value=AdminSummary()))
    row = AdminUserRow(
        account_id=2,
        telegram_username="friend",
        telegram_user_id=20,
        role="member",
        status="active",
    )
    monkeypatch.setattr(
        admin_router,
        "load_user_detail",
        AsyncMock(return_value=AdminUserDetail(user=row, funnel=FunnelCounts())),
    )
    monkeypatch.setattr(admin_router, "disable_user", AsyncMock())
    monkeypatch.setattr(admin_router, "enable_user", AsyncMock())
    monkeypatch.setattr(admin_router, "revoke_user_sessions", AsyncMock(return_value=1))
    monkeypatch.setattr(admin_router, "user_log_bundle", AsyncMock(return_value=b"PK\x03\x04"))
    monkeypatch.setattr(admin_router, "enqueue_admin_telegram", AsyncMock())
    monkeypatch.setattr(admin_router, "reject_key_request", AsyncMock())
    monkeypatch.setattr(admin_router, "issue_user_key", AsyncMock())
    monkeypatch.setattr(admin_router, "revoke_user_key", AsyncMock())
    monkeypatch.setattr(admin_router, "set_user_note", AsyncMock())
    monkeypatch.setattr(admin_router, "set_user_role", AsyncMock())
    monkeypatch.setattr(admin_router, "invalidate_web_auth_cache", lambda: None)

    with TestClient(app) as client:
        assert client.get("/api/admin/summary").status_code == 200
        assert client.get("/api/admin/users/2").status_code == 200
        assert client.post("/api/admin/users/2/disable").status_code == 200
        assert client.post("/api/admin/users/2/enable").status_code == 200
        assert client.post("/api/admin/users/2/revoke-sessions").status_code == 200
        logs = client.get("/api/admin/users/2/logs")
        assert logs.status_code == 200
        assert logs.headers["content-type"].startswith("application/zip")
        assert (
            client.post("/api/admin/users/2/telegram", json={"text": "привет"}).status_code == 200
        )
        assert client.post("/api/admin/keys/1/reject").status_code == 200
        issued = client.post("/api/admin/users/2/key", json={"key": "sk-or-v1-x"})
        assert issued.status_code == 200
        assert client.delete("/api/admin/users/2/key").status_code == 200
        assert client.patch("/api/admin/users/2/note", json={"note": "kate"}).status_code == 200
        assert client.post("/api/admin/users/2/role", json={"role": "member"}).status_code == 200
        assert client.post("/api/admin/users/2/disable", json={"reason": "тест"}).status_code == 200
