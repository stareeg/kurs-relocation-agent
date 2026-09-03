"""Этап 5 fix (LLM key routing gap — память project_openrouter_key_flow_2026_08_05):
`get_chat_model` должен резолвить ключ АККАУНТА текущего запроса/апдейта, не один ключ на
процесс. Три слоя:

- `core.platform.config.runtime` — чистые unit-тесты contextvar/кэша;
- `core.platform.repo.settings.prime_runtime_openrouter_key_for_account` — репо-слой (мок get_setting);
- `api.main` middleware сквозь реальный FastAPI app (TestClient) — доказывает, что запрос
  реально прогревает per-account кэш, не только что функции существуют по отдельности.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.platform.config import runtime as cfg_runtime


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    cfg_runtime.reset_runtime_for_tests()
    yield
    cfg_runtime.reset_runtime_for_tests()


# ---------- core.platform.config.runtime ----------


def test_current_account_key_empty_without_context() -> None:
    assert cfg_runtime.current_account_openrouter_key() == ""


def test_current_account_key_reads_cache_for_current_account_only() -> None:
    cfg_runtime.cache_account_openrouter_key(42, "sk-or-v1-a")
    cfg_runtime.cache_account_openrouter_key(7, "sk-or-v1-b")

    token = cfg_runtime.set_current_account_id(42)
    try:
        assert cfg_runtime.current_account_openrouter_key() == "sk-or-v1-a"
    finally:
        cfg_runtime.reset_current_account_id(token)

    assert cfg_runtime.current_account_openrouter_key() == ""  # контекст сброшен


def test_current_account_key_empty_when_cache_cold() -> None:
    token = cfg_runtime.set_current_account_id(99)
    try:
        assert cfg_runtime.current_account_openrouter_key() == ""
    finally:
        cfg_runtime.reset_current_account_id(token)


def test_account_key_cache_stale_ttl() -> None:
    assert cfg_runtime.account_openrouter_key_cache_stale(1) is True
    cfg_runtime.cache_account_openrouter_key(1, "sk-or-v1-x")
    assert cfg_runtime.account_openrouter_key_cache_stale(1) is False


def test_blank_key_cached_as_empty_not_as_literal_spaces() -> None:
    cfg_runtime.cache_account_openrouter_key(1, "   ")
    token = cfg_runtime.set_current_account_id(1)
    try:
        assert cfg_runtime.current_account_openrouter_key() == ""
    finally:
        cfg_runtime.reset_current_account_id(token)


# ---------- get_chat_model: приоритет ключей ----------


def _settings(env_key: str = "sk-or-v1-env") -> Any:
    from core.config import CoreSettings

    return CoreSettings(
        _env_file=None, model_tier_basic="openai/gpt-5.6-luna", openrouter_api_key=env_key
    )


def test_get_chat_model_prefers_per_account_key_over_process_holder() -> None:
    from core.config import set_runtime_openrouter_key
    from core.platform.llm.openrouter_chat import get_chat_model

    set_runtime_openrouter_key("sk-or-v1-process")
    cfg_runtime.cache_account_openrouter_key(5, "sk-or-v1-account")
    token = cfg_runtime.set_current_account_id(5)
    try:
        model = get_chat_model("basic", settings=_settings())
        assert model.api_key == "sk-or-v1-account"
    finally:
        cfg_runtime.reset_current_account_id(token)


def test_get_chat_model_falls_back_to_process_holder_without_account_context() -> None:
    """Регрессия: без per-request контекста (фон/скрипт) старое поведение не сломано."""
    from core.config import set_runtime_openrouter_key
    from core.platform.llm.openrouter_chat import get_chat_model

    set_runtime_openrouter_key("sk-or-v1-process")
    model = get_chat_model("basic", settings=_settings())
    assert model.api_key == "sk-or-v1-process"


def test_get_chat_model_falls_back_to_env_when_nothing_set() -> None:
    from core.platform.llm.openrouter_chat import get_chat_model

    model = get_chat_model("basic", settings=_settings())
    assert model.api_key == "sk-or-v1-env"


def test_get_chat_model_ignores_other_accounts_cached_key() -> None:
    """Контекст account 5, в кэше только ключ account 6 — чужой ключ не утекает.

    И .env тоже не подставляем: attributed-запрос без своего ключа должен получить пустой
    api_key (member без BYOK не жжёт счёт оператора), а не sk-or-v1-env.
    """
    from core.platform.llm.openrouter_chat import get_chat_model

    cfg_runtime.cache_account_openrouter_key(6, "sk-or-v1-other-account")
    token = cfg_runtime.set_current_account_id(5)
    try:
        model = get_chat_model("basic", settings=_settings())
        assert model.api_key == ""
    finally:
        cfg_runtime.reset_current_account_id(token)


# ---------- core.platform.repo.settings.prime_runtime_openrouter_key_for_account ----------


@pytest.mark.asyncio
async def test_prime_reads_db_once_within_ttl_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.platform.repo import settings as repo_settings

    calls = {"n": 0}

    async def fake_get_setting(
        key: str, default: Any = None, *, account_id: int | None = None, db: Any = None
    ) -> Any:
        calls["n"] += 1
        assert key == "openrouter_api_key"
        assert account_id == 5
        return "sk-or-v1-fresh"

    monkeypatch.setattr(repo_settings, "get_setting", fake_get_setting)

    await repo_settings.prime_runtime_openrouter_key_for_account(5)
    await repo_settings.prime_runtime_openrouter_key_for_account(5)  # тёплый кэш — не бьёт в БД

    assert calls["n"] == 1
    assert cfg_runtime.account_openrouter_key_cache_stale(5) is False
    token = cfg_runtime.set_current_account_id(5)
    try:
        assert cfg_runtime.current_account_openrouter_key() == "sk-or-v1-fresh"
    finally:
        cfg_runtime.reset_current_account_id(token)


@pytest.mark.asyncio
async def test_prime_caches_absence_as_empty_not_as_repeated_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.platform.repo import settings as repo_settings

    calls = {"n": 0}

    async def fake_get_setting(
        key: str, default: Any = None, *, account_id: int | None = None, db: Any = None
    ) -> Any:
        calls["n"] += 1
        return default

    monkeypatch.setattr(repo_settings, "get_setting", fake_get_setting)

    await repo_settings.prime_runtime_openrouter_key_for_account(9)

    assert calls["n"] == 1
    assert cfg_runtime.account_openrouter_key_cache_stale(9) is False


# ---------- api.main middleware: сквозь реальный FastAPI app ----------


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    yield


def test_middleware_warms_account_cache_on_authed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/settings под валидным токеном аккаунта 501 прогревает per-account кэш ключа —
    доказывает, что middleware реально стоит в цепочке запроса, не только что функция есть.
    """
    from api import security
    from core.domains.profile import web_auth as wa
    from core.platform.repo import settings as repo_settings
    from tests.fake_accounts import FakeAccountsStore

    fake = FakeAccountsStore()
    fake.patch_accounts_module(monkeypatch, security)
    fake.patch_web_auth_module(monkeypatch, wa)
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(api_key=""))
    security.invalidate_web_auth_cache()

    async def fake_get_setting(
        key: str, default: Any = None, *, account_id: int | None = None, db: Any = None
    ) -> Any:
        _ = key, db
        return default

    async def fake_set_setting(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(repo_settings, "get_setting", fake_get_setting)
    monkeypatch.setattr(repo_settings, "set_setting", fake_set_setting)

    import asyncio

    async def _seed() -> str:
        account = await fake.upsert_account(telegram_user_id=501, role="member")
        issued = await fake.issue_web_auth_token(account.id)
        return issued.token

    token = asyncio.run(_seed())
    security.invalidate_web_auth_cache()

    assert cfg_runtime.account_openrouter_key_cache_stale(1) is True  # ничего не прогрето заранее

    from api.main import app

    app.router.lifespan_context = _noop_lifespan  # type: ignore[method-assign]
    with TestClient(app) as client:
        client.cookies.set(security.AUTH_COOKIE, token)
        response = client.get("/api/settings")

    assert response.status_code == 200
    assert cfg_runtime.account_openrouter_key_cache_stale(1) is False
