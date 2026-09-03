"""AUTH-1/Этап 2: периметр API и ручки /auth/* — матрица путей без PG (мокнутый repo).

Ключевые инварианты «без мёртвых путей»:
- пока web-токен не выпускался (ни одним аккаунтом), периметр открыт (bootstrap) — даже при
  заданном API_KEY (старая ловушка «ключ есть, пароля нет → тупик логина» невозможна);
- как только токен выпущен, периметр закрыт: пускают cookie / X-Auth-Token / X-API-Key
  (как web-токен ИЛИ статический ключ из .env);
- логаут отзывает токен, но НЕ открывает периметр;
- /auth/token читает запись свежей (мимо TTL-кэша) — токен из бота принимается сразу.

Identity (`accounts`) теперь идёт напрямую в SQL (Этап 2), не через `get_setting`/
`set_setting` — подменяется `FakeAccountsStore` (`tests/fake_accounts.py`), а не
`settings_store`-словарём, как раньше. `settings_store` остаётся для настроек «Параметров»
(openrouter_api_key/onboarding), которые всё ещё идут через `core.platform.repo.settings`.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException, Response

import core.platform.repo.settings as repo_settings
from api import security
from api.config import Settings
from api.routers.meta import auth as auth_routes
from core.domains.profile import telegram_link as tl
from core.domains.profile import web_auth as wa
from tests.fake_accounts import FakeAccountsStore


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """In-memory app_settings для onboarding/openrouter_api_key (core.platform.repo.settings)."""
    data: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return data.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        data[key] = value

    monkeypatch.setattr(repo_settings, "get_setting", fake_get)
    monkeypatch.setattr(repo_settings, "set_setting", fake_set)
    # telegram_link.py по-прежнему ходит в core.platform.repo.settings за telegram_link_token/
    # telegram_bot_identity (account_id=None, глобальные ключи) — своя локальная привязка имени.
    monkeypatch.setattr(tl, "get_setting", fake_get)
    monkeypatch.setattr(tl, "set_setting", fake_set)
    security.invalidate_web_auth_cache()
    yield data
    security.invalidate_web_auth_cache()


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> FakeAccountsStore:
    """In-memory `accounts` — identity/web-токен (Этап 2, не через app_settings)."""
    _ = store
    fake = FakeAccountsStore()
    fake.patch_web_auth_module(monkeypatch, wa)
    fake.patch_accounts_module(monkeypatch, security)
    fake.patch_accounts_module(monkeypatch, auth_routes)
    security.invalidate_web_auth_cache()
    yield fake
    security.invalidate_web_auth_cache()


def _api_settings(api_key: str = "", bot_token: str = "") -> Settings:
    return Settings(_env_file=None, api_key=api_key, telegram_bot_token=bot_token)


@pytest.fixture
def no_env_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "get_settings", _api_settings)
    monkeypatch.setattr(auth_routes, "get_settings", _api_settings)


async def _authed(**kwargs: Any) -> bool:
    """require_account → True/False вместо AccountContext|None/исключения (для матрицы)."""
    try:
        await security.require_account(
            x_api_key=kwargs.get("x_api_key"),
            x_auth_token=kwargs.get("x_auth_token"),
            copilot_auth=kwargs.get("cookie"),
        )
        return True
    except HTTPException as exc:
        assert exc.status_code == 401
        return False


# ---------- require_account: bootstrap ----------


@pytest.mark.asyncio
async def test_perimeter_open_until_first_token(accounts: FakeAccountsStore, no_env_auth: None) -> None:
    assert await _authed() is True


@pytest.mark.asyncio
async def test_perimeter_open_even_with_api_key_configured(
    accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Старый тупик другого локального запуска: API_KEY был задан, а логиниться нечем.
    # Теперь API_KEY не закрывает периметр — закрывает только выпущенный web-токен.
    monkeypatch.setattr(security, "get_settings", lambda: _api_settings(api_key="static-key"))
    assert await _authed() is True


# ---------- require_account: закрытый периметр ----------


@pytest.mark.asyncio
async def test_closed_perimeter_requires_credentials(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    account = await accounts.upsert_account(telegram_user_id=1)
    issued = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    assert await _authed() is False
    assert await _authed(cookie="wrong") is False
    assert await _authed(cookie=issued.token) is True
    assert await _authed(x_auth_token=issued.token) is True
    # Расширение может слать тот же токен в X-API-Key — одна учётка везде.
    assert await _authed(x_api_key=issued.token) is True


@pytest.mark.asyncio
async def test_extension_header_auth_auto_confirms_without_manual_click(
    accounts: FakeAccountsStore, store: dict[str, Any], no_env_auth: None
) -> None:
    # Баг 2026-08-05: «Расширение установлено» на фронте было самоотчётом, который ничего не
    # проверял — друг мог отметить шаг, даже когда расширение реально не достучалось до бэка.
    # Теперь флаг ставит сам бэкенд, увидев запрос, авторизованный НЕ по cookie (веб всегда
    # шлёт cookie; X-Auth-Token/X-API-Key — только расширение/скрипты, api/security.py).
    account = await accounts.upsert_account(telegram_user_id=1)
    issued = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    assert store.get("onboarding") is None

    # Веб-запрос по cookie — не расширение, флаг не трогаем.
    assert await _authed(cookie=issued.token) is True
    assert store.get("onboarding") is None

    # Тот же токен, но в X-Auth-Token (путь расширения) — авто-подтверждение.
    assert await _authed(x_auth_token=issued.token) is True
    assert store["onboarding"]["extension_confirmed"] is True


@pytest.mark.asyncio
async def test_env_api_key_still_works_when_closed(
    accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "get_settings", lambda: _api_settings(api_key="static-key"))
    account = await accounts.upsert_account(telegram_user_id=1)
    await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    assert await _authed(x_api_key="static-key") is True
    assert await _authed(x_api_key="other") is False


@pytest.mark.asyncio
async def test_reissue_keeps_old_cookie_valid(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    """Part C: перевыпуск — новая сессия, не замена. Другое устройство/браузер с прежней
    cookie не должно вылетать из системы, когда пользователь просто взял новый токен себе
    на второе устройство (регрессия на исходный запрос — «поддержка нескольких устройств»)."""
    account = await accounts.upsert_account(telegram_user_id=1)
    first = await wa.issue_web_auth_token(account.id)
    second = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    assert await _authed(cookie=first.token) is True
    assert await _authed(cookie=second.token) is True


@pytest.mark.asyncio
async def test_logout_revokes_but_keeps_perimeter_closed(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    account = await accounts.upsert_account(telegram_user_id=1)
    issued = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    response = Response()
    await auth_routes.logout(response, copilot_auth=issued.token)

    assert await _authed(cookie=issued.token) is False  # токен отозван
    assert await _authed() is False  # и периметр НЕ открылся заново
    set_cookie = response.headers.get("set-cookie") or ""
    assert security.AUTH_COOKIE in set_cookie  # cookie снесена (Max-Age=0/expires)


@pytest.mark.asyncio
async def test_logout_does_not_revoke_other_sessions(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    """Логаут — «с этого устройства», не «отовсюду»: другая активная сессия того же
    аккаунта должна пережить логаут первой."""
    account = await accounts.upsert_account(telegram_user_id=1)
    first = await wa.issue_web_auth_token(account.id)
    second = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    await auth_routes.logout(Response(), copilot_auth=first.token)

    assert await _authed(cookie=first.token) is False
    assert await _authed(cookie=second.token) is True


# ---------- POST /auth/token ----------


@pytest.mark.asyncio
async def test_login_sets_yearlong_cookie(accounts: FakeAccountsStore, no_env_auth: None) -> None:
    account = await accounts.upsert_account(telegram_user_id=42, telegram_username="owner")
    issued = await wa.issue_web_auth_token(account.id)
    security.invalidate_web_auth_cache()

    response = Response()
    status = await auth_routes.perform_token_login(
        f" {issued.token} ", response, user_agent=None
    )

    assert status.authed is True
    assert status.is_admin is True
    assert status.auth_token_configured is True
    assert status.account_username == "owner"
    set_cookie = response.headers.get("set-cookie") or ""
    assert f"{security.AUTH_COOKIE}={issued.token}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Max-Age={security.AUTH_COOKIE_MAX_AGE_S}" in set_cookie


@pytest.mark.asyncio
async def test_login_rejects_wrong_and_missing_token(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    # Токен ещё не выпущен → понятная подсказка «нажми кнопку в боте».
    with pytest.raises(HTTPException) as exc_info:
        await auth_routes.perform_token_login("abc", Response(), user_agent=None)
    assert exc_info.value.status_code == 401
    assert "не выпущен" in str(exc_info.value.detail)

    account = await accounts.upsert_account(telegram_user_id=1)
    await wa.issue_web_auth_token(account.id)
    with pytest.raises(HTTPException) as exc_info:
        await auth_routes.perform_token_login("wrong", Response(), user_agent=None)
    assert exc_info.value.status_code == 401
    assert "не подходит" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_login_rejects_revoked_token(accounts: FakeAccountsStore, no_env_auth: None) -> None:
    account = await accounts.upsert_account(telegram_user_id=1)
    issued = await wa.issue_web_auth_token(account.id)
    await wa.revoke_session_by_token(issued.token)

    with pytest.raises(HTTPException) as exc_info:
        await auth_routes.perform_token_login(issued.token, Response(), user_agent=None)
    assert exc_info.value.status_code == 401
    assert "отозван" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_login_sees_fresh_token_despite_ttl_cache(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    # require_account закэшировал «записи нет» (bootstrap) — логин обязан читать свежую запись.
    assert await _authed() is True
    account = await accounts.upsert_account(telegram_user_id=1)
    issued = await wa.issue_web_auth_token(account.id)

    response = Response()
    status = await auth_routes.perform_token_login(issued.token, response, user_agent=None)
    assert status.authed is True


# ---------- POST /auth/token: переносимый токен ----------


@pytest.mark.asyncio
async def test_login_portable_token_bootstraps_install(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    # Гость центрального бота вставляет переносимый токен в СВОЮ свежую установку:
    # установка привязывается к его аккаунту, периметр закрывается.
    token = wa.build_portable_token(user_id=10, username="friend")

    response = Response()
    status = await auth_routes.perform_token_login(token, response, user_agent=None)

    assert status.authed is True
    assert status.auth_token_configured is True
    assert status.account_username == "friend"
    security.invalidate_web_auth_cache()
    assert await _authed(cookie=token) is True
    assert await _authed() is False  # bootstrap закончился


@pytest.mark.asyncio
async def test_login_portable_rotates_same_account(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    # Логаут не превращает установку в кирпич: новый переносимый токен ТОГО ЖЕ
    # аккаунта принимается (перевыпуск в боте), старый гаснет.
    first = wa.build_portable_token(user_id=10, username="friend")
    await auth_routes.perform_token_login(first, Response(), user_agent=None)
    await auth_routes.logout(Response(), copilot_auth=first)

    second = wa.build_portable_token(user_id=10, username="friend")
    status = await auth_routes.perform_token_login(second, Response(), user_agent=None)

    assert status.authed is True
    security.invalidate_web_auth_cache()
    assert await _authed(cookie=second) is True
    assert await _authed(cookie=first) is False


@pytest.mark.asyncio
async def test_login_portable_rejects_foreign_account(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    # Занятую установку чужим переносимым токеном не увести.
    owner_account = await accounts.upsert_account(telegram_user_id=1, telegram_username="owner")
    await wa.issue_web_auth_token(owner_account.id)
    stranger = wa.build_portable_token(user_id=999, username="stranger")

    with pytest.raises(HTTPException) as exc_info:
        await auth_routes.perform_token_login(stranger, Response(), user_agent=None)

    assert exc_info.value.status_code == 401
    assert "другого" in str(exc_info.value.detail)
    record = await accounts.get_account_by_id(owner_account.id)
    assert record is not None
    assert record.telegram_user_id == 1  # запись владельца не перезаписана


# ---------- GET /auth/status ----------


@pytest.mark.asyncio
async def test_auth_status_bootstrap(accounts: FakeAccountsStore, no_env_auth: None) -> None:
    status = await auth_routes.auth_status(x_api_key=None, x_auth_token=None, copilot_auth=None)
    assert status.authed is True  # периметр открыт
    assert status.is_admin is False
    assert status.auth_token_configured is False
    assert status.openrouter_key_configured is False
    assert status.extension_confirmed is False
    assert status.bot_configured is False


@pytest.mark.asyncio
async def test_auth_status_reflects_onboarding_flags(
    accounts: FakeAccountsStore, store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "get_settings", _api_settings)
    monkeypatch.setattr(
        auth_routes, "get_settings", lambda: _api_settings(bot_token="123:abc")
    )
    store["openrouter_api_key"] = "sk-or-v1-x"
    store["onboarding"] = {"extension_confirmed": True}
    await tl.set_bot_identity("copilot_bot")
    owner_account = await accounts.upsert_account(telegram_user_id=42, telegram_username="owner")
    issued = await wa.issue_web_auth_token(owner_account.id)
    security.invalidate_web_auth_cache()

    anon = await auth_routes.auth_status(x_api_key=None, x_auth_token=None, copilot_auth=None)
    assert anon.authed is False
    assert anon.is_admin is False
    assert anon.auth_token_configured is True
    assert anon.openrouter_key_configured is True
    assert anon.extension_confirmed is True
    assert anon.bot_configured is True
    assert anon.bot_username == "copilot_bot"

    authed = await auth_routes.auth_status(
        x_api_key=None, x_auth_token=None, copilot_auth=issued.token
    )
    assert authed.authed is True
    assert authed.is_admin is True
    assert authed.account_username == "owner"


@pytest.mark.asyncio
async def test_auth_status_member_is_not_admin(
    accounts: FakeAccountsStore, no_env_auth: None
) -> None:
    member = await accounts.upsert_account(
        telegram_user_id=7, telegram_username="friend", role="member"
    )
    issued = await wa.issue_web_auth_token(member.id)
    security.invalidate_web_auth_cache()
    status = await auth_routes.auth_status(
        x_api_key=None, x_auth_token=None, copilot_auth=issued.token
    )
    assert status.authed is True
    assert status.is_admin is False
    assert status.account_username == "friend"
