"""`GET /api/opportunities/parser-config/extension` + админ-ручки оверрайда рантайм-конфига."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.domains.opportunities.extension_runtime_config import (
    reset_extension_runtime_config_cache,
    resolve_extension_runtime_config,
)


def _repo_version() -> int:
    """Версия дефолтного конфига из репозитория. Читаем её, а не хардкодим: version
    поднимается при каждой правке tuning/флагов (иначе ETag `ext-runtime-N` отдаёт 304 и
    установленные расширения новых значений не видят), и хардкод ломал бы тест на каждой."""
    from core.domains.opportunities.extension_runtime_config import load_repo_config

    return int(load_repo_config()["version"])


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_extension_runtime_config_cache()
    yield
    reset_extension_runtime_config_cache()


def _client(monkeypatch: pytest.MonkeyPatch, override: object | None = None) -> TestClient:
    from api.routers.opportunities import parser_config as router_mod

    cfg = resolve_extension_runtime_config(override, None)

    async def fake_get() -> object:
        return cfg

    monkeypatch.setattr(router_mod, "get_extension_runtime_config", fake_get)
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app)


def test_extension_config_etag_and_304(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as client:
        first = client.get("/api/opportunities/parser-config/extension")
        assert first.status_code == 200
        assert first.headers["etag"] == f'"ext-runtime-{_repo_version()}"'
        assert first.headers["cache-control"] == "no-cache"
        body = first.json()
        assert body["origin"] == "repo"
        assert body["flags"]["auto_apply_enabled"] is True
        assert body["tuning"]["auto_apply_tick_minutes"] == 5
        assert body["apply_selectors"]["hh"]["responseLinkTop"]

        cached = client.get(
            "/api/opportunities/parser-config/extension",
            headers={"If-None-Match": first.headers["etag"]},
        )
        assert cached.status_code == 304
        assert cached.content == b""


def test_extension_config_serves_override(monkeypatch: pytest.MonkeyPatch) -> None:
    override = {"version": 9, "flags": {"auto_apply_hh_enabled": False}}
    with _client(monkeypatch, override) as client:
        body = client.get("/api/opportunities/parser-config/extension").json()
        assert body["origin"] == "db_override"
        assert body["version"] == 9
        assert body["flags"]["auto_apply_hh_enabled"] is False


async def test_admin_set_override_bumps_version_and_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_extension_runtime_config_admin: пишет через set_setting, поднимает version, `{}` снимает."""
    from core.platform.admin import service as admin_service

    store: dict[str, object] = {}

    async def fake_get_setting(key: str, default: object = None, *, account_id: object, db: object = None):
        return store.get(key, default)

    async def fake_set_setting(key: str, value: object, *, account_id: object, db: object = None):
        store[key] = value

    class _Pool:
        async def execute(self, sql: str, *args: object) -> str:
            store.pop("extension_runtime_config", None)
            return "DELETE 1"

    monkeypatch.setattr(
        "core.domains.opportunities.extension_runtime_config.get_setting", fake_get_setting
    )
    monkeypatch.setattr(
        "core.domains.opportunities.extension_runtime_config.set_setting", fake_set_setting
    )
    monkeypatch.setattr(admin_service, "get_pool", lambda: _Pool())

    async def noop_log(*a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(admin_service, "_log_action", noop_log)

    res = await admin_service.set_extension_runtime_config_admin(
        {"flags": {"auto_apply_getmatch_enabled": False}}, actor_id=1
    )
    assert res["origin"] == "db_override"
    assert res["version"] == _repo_version() + 1
    assert res["flags"]["auto_apply_getmatch_enabled"] is False
    assert store["extension_runtime_config"]["version"] == _repo_version() + 1  # type: ignore[index]

    cleared = await admin_service.set_extension_runtime_config_admin({}, actor_id=1)
    assert cleared["origin"] == "repo"
    assert "extension_runtime_config" not in store
