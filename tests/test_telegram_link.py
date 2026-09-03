"""TB-1: привязка Telegram (токен / access / push) — мокнутый repo, без PG.

TB-1.9 закрывает контракт фазы: генерация/TTL/одноразовость токена, линковка,
приоритет DB-owner над env для пушей, open-mode больше не «отвечаем всем».

Этап 2: «владелец» — строка `accounts` (`role='owner'`), не запись `telegram_owner` в
`app_settings`. `settings_store` (get_setting/set_setting) остаётся только для
`telegram_link_token`/`telegram_bot_identity` (по-прежнему глобальные, account_id=None);
владельца подменяет `FakeAccountsStore` (`tests/fake_accounts.py`), патченный в `tl` —
`bot_app.access`/`bot_app.config` смотрят на те же объекты (`get_owner` — тот же
объект-функция, что и `tl.get_owner`), поэтому один патч закрывает обе поверхности.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.domains.profile import telegram_link as tl
from tests.fake_accounts import FakeAccountsStore


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """In-memory подмена get_setting/set_setting — только ключи telegram_link_token и identity."""
    store: dict[str, Any] = {}

    async def fake_get(
        key: str, default: Any = None, *, account_id: Any = None, db: Any = None
    ) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(tl, "get_setting", fake_get)
    monkeypatch.setattr(tl, "set_setting", fake_set)
    return store


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch) -> FakeAccountsStore:
    """In-memory `accounts` — владелец (Этап 2, не через app_settings)."""
    fake = FakeAccountsStore()
    fake.patch_telegram_link_module(monkeypatch, tl)
    return fake


def test_generate_raw_token_is_urlsafe_and_fits_start_payload() -> None:
    token = tl.generate_raw_token()
    assert token
    assert all(c.isalnum() or c in "-_" for c in token)
    payload = f"{tl.LINK_PAYLOAD_PREFIX}{token}"
    assert len(payload) <= 64
    assert tl.extract_link_token(payload) == token


def test_extract_link_token_rejects_garbage() -> None:
    assert tl.extract_link_token("") is None
    assert tl.extract_link_token("vac_123") is None
    assert tl.extract_link_token("link_") is None
    assert tl.extract_link_token("link_abc/def") is None


def test_hash_token_is_stable_hex() -> None:
    assert tl.hash_token("abc") == tl.hash_token("abc")
    assert tl.hash_token("abc") != tl.hash_token("abd")
    assert len(tl.hash_token("abc")) == 64


@pytest.mark.asyncio
async def test_create_link_token_stores_only_sha256(settings_store: dict[str, Any]) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = await tl.create_link_token(now=now)

    assert issued.expires_at == now + tl.TOKEN_TTL
    assert issued.start_payload == f"link_{issued.token}"
    raw = settings_store[tl.KEY_LINK_TOKEN]
    assert isinstance(raw, dict)
    assert "token" not in raw
    assert raw["token_sha256"] == tl.hash_token(issued.token)
    assert issued.token not in str(raw)


@pytest.mark.asyncio
async def test_consume_token_links_owner_once(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = await tl.create_link_token(now=now)

    owner = await tl.consume_token(
        issued.token,
        user_id=42,
        chat_id=42,
        username="@Owner",
        now=now + timedelta(minutes=1),
    )
    assert owner is not None
    assert owner.telegram_user_id == 42
    assert owner.telegram_chat_id == 42
    assert owner.telegram_username == "Owner"

    stored = await tl.get_owner()
    assert stored is not None
    assert stored.telegram_user_id == 42
    assert settings_store.get(tl.KEY_LINK_TOKEN) is None

    # Одноразовость: повторный consume того же токена не проходит.
    again = await tl.consume_token(
        issued.token,
        user_id=99,
        chat_id=99,
        username="other",
        now=now + timedelta(minutes=2),
    )
    assert again is None
    stored_again = await tl.get_owner()
    assert stored_again is not None
    assert stored_again.telegram_user_id == 42


@pytest.mark.asyncio
async def test_consume_token_rejects_expired(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = await tl.create_link_token(now=now)

    expired = await tl.consume_token(
        issued.token,
        user_id=1,
        chat_id=1,
        now=now + tl.TOKEN_TTL + timedelta(seconds=1),
    )
    assert expired is None
    assert await tl.get_owner() is None
    assert settings_store.get(tl.KEY_LINK_TOKEN) is None


@pytest.mark.asyncio
async def test_consume_token_rejects_wrong_token(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    await tl.create_link_token(now=now)

    bad = await tl.consume_token("not-the-token", user_id=1, chat_id=1, now=now)
    assert bad is None
    # Неверный токен не сжигает pending — владелец сможет открыть ту же ссылку.
    assert settings_store.get(tl.KEY_LINK_TOKEN) is not None
    assert await tl.get_owner() is None


@pytest.mark.asyncio
async def test_create_replaces_previous_pending(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    first = await tl.create_link_token(now=now)
    second = await tl.create_link_token(now=now + timedelta(seconds=5))

    assert first.token != second.token
    assert await tl.consume_token(first.token, user_id=1, chat_id=1, now=now) is None
    owner = await tl.consume_token(second.token, user_id=2, chat_id=2, now=now)
    assert owner is not None
    assert owner.telegram_user_id == 2


@pytest.mark.asyncio
async def test_unlink_clears_owner_and_pending(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = await tl.create_link_token(now=now)
    owner = await tl.consume_token(issued.token, user_id=7, chat_id=7, now=now)
    assert owner is not None
    await tl.create_link_token(now=now)  # новый pending после линковки

    await tl.unlink(account_id=owner.id)
    assert await tl.get_owner() is None
    assert settings_store.get(tl.KEY_LINK_TOKEN) is None


@pytest.mark.asyncio
async def test_unlink_only_disables_own_account(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    """M7: `unlink` больше не гасит владельца безусловно — только переданный `account_id`
    (plans/multitenancy_gaps_2026_08_06.md §3.11)."""
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    owner = await tl.consume_token(
        (await tl.create_link_token(now=now)).token, user_id=1, chat_id=1, now=now, role="owner"
    )
    member = await tl.consume_token(
        (await tl.create_link_token(now=now)).token,
        user_id=2,
        chat_id=2,
        now=now,
        role="member",
    )
    assert owner is not None and member is not None

    await tl.unlink(account_id=member.id)

    still_owner = await tl.get_owner()
    assert still_owner is not None
    assert still_owner.telegram_user_id == 1
    refreshed_member = await accounts.get_account_by_telegram_user_id(2)
    assert refreshed_member is not None
    assert refreshed_member.status == "disabled"


@pytest.mark.asyncio
async def test_consume_token_role_member_when_not_allowlisted(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    """`consume_token(role=...)` прокидывает роль как есть — политику allowlist знает
    вызывающая сторона (bot_app), не этот домен-модуль."""
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = await tl.create_link_token(now=now)

    account = await tl.consume_token(
        issued.token, user_id=5, chat_id=5, now=now, role="member"
    )
    assert account is not None
    assert account.role == "member"
    assert await tl.get_owner() is None


@pytest.mark.asyncio
async def test_bot_identity_roundtrip(settings_store: dict[str, Any]) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    saved = await tl.set_bot_identity("@CareerCopilotBot", now=now)
    assert saved.username == "CareerCopilotBot"
    assert saved.fetched_at == now

    loaded = await tl.get_bot_identity()
    assert loaded is not None
    assert loaded.username == "CareerCopilotBot"

    await tl.clear_bot_identity()
    assert await tl.get_bot_identity() is None


def test_build_deep_link() -> None:
    link = tl.build_deep_link("@MyBot", "link_abc")
    assert link == "https://t.me/MyBot?start=link_abc"
    assert tl.build_deep_link("MyBot", "link_xyz") == "https://t.me/MyBot?start=link_xyz"


@pytest.mark.asyncio
async def test_resolve_bot_username_uses_cache_without_getme(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.routers.meta import telegram as api_tg

    await tl.set_bot_identity("CachedBot")
    calls = {"n": 0}

    async def boom(_token: str) -> str | None:
        calls["n"] += 1
        raise AssertionError("getMe не должен вызываться при живом кэше")

    monkeypatch.setattr(api_tg, "fetch_bot_username", boom)
    assert await api_tg.resolve_bot_username("tok") == "CachedBot"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_resolve_bot_username_fetches_and_caches(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.routers.meta import telegram as api_tg

    async def fake_fetch(token: str) -> str | None:
        assert token == "secret-token"
        return "FreshBot"

    monkeypatch.setattr(api_tg, "fetch_bot_username", fake_fetch)
    assert await api_tg.resolve_bot_username("secret-token") == "FreshBot"
    cached = await tl.get_bot_identity()
    assert cached is not None
    assert cached.username == "FreshBot"


@pytest.mark.asyncio
async def test_issue_link_token_requires_bot_token(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from api.routers.meta import telegram as api_tg

    monkeypatch.setattr(
        api_tg,
        "get_settings",
        lambda: type("S", (), {"telegram_bot_token": ""})(),
    )
    with pytest.raises(HTTPException) as exc:
        await api_tg.issue_link_token_response()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_issue_link_token_builds_deep_link(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.routers.meta import telegram as api_tg

    monkeypatch.setattr(
        api_tg,
        "get_settings",
        lambda: type("S", (), {"telegram_bot_token": "tok"})(),
    )

    async def fake_resolve(_token: str) -> str | None:
        return "CareerBot"

    monkeypatch.setattr(api_tg, "resolve_bot_username", fake_resolve)
    resp = await api_tg.issue_link_token_response()
    assert resp.deep_link.startswith("https://t.me/CareerBot?start=link_")
    payload = resp.deep_link.split("start=", 1)[1]
    assert tl.extract_link_token(payload) is not None
    assert len(payload) <= 64


@pytest.mark.asyncio
async def test_unlink_telegram_router_only_disables_caller(
    settings_store: dict[str, Any], accounts: FakeAccountsStore
) -> None:
    """M7: `DELETE /api/telegram/link` отвязывает СВОЙ аккаунт вызывающего, не владельца
    (plans/multitenancy_gaps_2026_08_06.md §3.11 — раньше любой залогиненный member мог
    одним запросом выключить владельца)."""
    from api.routers.meta import telegram as api_tg
    from api.security import AccountContext

    owner = await tl.set_owner(user_id=1, chat_id=1, username="Owner")
    member = await tl.consume_token(
        (await tl.create_link_token()).token, user_id=2, chat_id=2, role="member"
    )
    assert member is not None

    member_ctx = AccountContext(
        account_id=member.id, telegram_user_id=2, telegram_username=None, role="member"
    )
    await api_tg.unlink_telegram(account=member_ctx)

    still_owner = await tl.get_owner()
    assert still_owner is not None
    assert still_owner.telegram_user_id == owner.telegram_user_id
    refreshed_member = await accounts.get_account_by_telegram_user_id(2)
    assert refreshed_member is not None
    assert refreshed_member.status == "disabled"


def test_telegram_routes_registered() -> None:
    from api.routers.meta import telegram as api_tg

    paths = {getattr(r, "path", "") for r in api_tg.router.routes}
    assert "/api/telegram/status" in paths
    assert "/api/telegram/link-token" in paths
    assert "/api/telegram/link" in paths
    assert "/api/telegram/push" in paths


def test_api_telegram_does_not_import_bot_app() -> None:
    # Не `import api.routers.meta.telegram`: после загрузки api.routers атрибут `.meta`
    # перекрыт модулем meta.py (реэкспорт), и submodule-import ломается.
    src = (
        Path(__file__).resolve().parents[1] / "api" / "routers" / "meta" / "telegram.py"
    ).read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "bot_app" not in stripped
            assert "aiogram" not in stripped


# --- TB-1.3: /start link_<token> в боте -------------------------------------------------------


@pytest.mark.asyncio
async def test_is_link_start_payload_filter() -> None:
    from types import SimpleNamespace

    from bot_app.handlers.menu import IsLinkStartPayload

    filt = IsLinkStartPayload()
    assert await filt(SimpleNamespace(text="/start link_abc-DEF_12"))
    assert await filt(SimpleNamespace(text="/start@MyBot link_abc"))
    assert not await filt(SimpleNamespace(text="/start"))
    assert not await filt(SimpleNamespace(text="/start vac_123"))
    assert not await filt(SimpleNamespace(text="/start link_"))
    assert not await filt(SimpleNamespace(text=None))


@pytest.mark.asyncio
async def test_complete_telegram_link_success(
    settings_store: dict[str, Any], accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import bot_app.access as access
    from bot_app.handlers import menu as menu_mod

    access._cached_owner = "stale"
    access._cached_at_mono = 1.0
    issued = await tl.create_link_token()

    answers: list[dict[str, Any]] = []

    async def capture_answer(text: str, **kwargs: Any) -> None:
        answers.append({"text": text, **kwargs})

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="Owner"),
        chat=SimpleNamespace(id=42),
        answer=AsyncMock(side_effect=capture_answer),
    )
    monkeypatch.setattr(
        menu_mod,
        "get_bot_settings",
        lambda: SimpleNamespace(web_url="http://localhost:5173"),
    )
    # M7: роль решает env-allowlist, не факт привязки — форсируем user_id=42 в allowlist,
    # иначе роль плыла бы вместе с реальным .env этой машины (см. plan §3.11/§6).
    monkeypatch.setattr(
        access,
        "get_bot_settings",
        lambda: SimpleNamespace(admin_user_id=42, admin_user_ids="", admin_usernames=""),
    )
    show_calls: list[Any] = []

    async def capture_show(message: Any, ctx: Any = None, **kwargs: Any) -> None:
        show_calls.append({"message": message, "ctx": ctx, **kwargs})

    monkeypatch.setattr(menu_mod, "show_menu_for", AsyncMock(side_effect=capture_show))

    ok = await menu_mod.complete_telegram_link(message, issued.token)
    assert ok is True
    assert access._cached_owner is access._MISSING
    owner = await tl.get_owner()
    assert owner is not None
    assert owner.telegram_user_id == 42
    assert owner.role == "owner"
    assert len(answers) == 1
    assert answers[0]["text"].startswith("Привязано:")
    assert "@Owner" in answers[0]["text"]
    assert "http://localhost:5173" in answers[0]["text"]
    assert len(show_calls) == 1
    assert show_calls[0]["ctx"].kind == "idle"


@pytest.mark.asyncio
async def test_complete_telegram_link_stranger_becomes_member(
    settings_store: dict[str, Any], accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M7: веб-привязка чужого (не env-allowlist) Telegram-пользователя не даёт role='owner'
    (plans/multitenancy_gaps_2026_08_06.md §3.11 — раньше `consume_token` всегда заводил
    owner'а, что позволяло перехватить роль)."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import bot_app.access as access
    from bot_app.handlers import menu as menu_mod

    access.invalidate()
    issued = await tl.create_link_token()

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=999, username="stranger"),
        chat=SimpleNamespace(id=999),
        answer=AsyncMock(),
    )
    monkeypatch.setattr(
        menu_mod, "get_bot_settings", lambda: SimpleNamespace(web_url="http://localhost:5173")
    )
    # Ни env-allowlist, ни существующий DB-owner не совпадают с 999 → должно стать member.
    monkeypatch.setattr(
        access,
        "get_bot_settings",
        lambda: SimpleNamespace(admin_user_id=0, admin_user_ids="", admin_usernames=""),
    )
    show_calls: list[Any] = []

    async def capture_show(message: Any, ctx: Any = None, **kwargs: Any) -> None:
        show_calls.append({"message": message, "ctx": ctx, **kwargs})

    monkeypatch.setattr(menu_mod, "show_menu_for", AsyncMock(side_effect=capture_show))

    ok = await menu_mod.complete_telegram_link(message, issued.token)
    assert ok is True
    account = await accounts.get_account_by_telegram_user_id(999)
    assert account is not None
    assert account.role == "member"
    # Владельца системы это не заводит — get_owner() (role='owner') всё ещё пуст.
    assert await tl.get_owner() is None
    assert len(show_calls) == 1
    assert show_calls[0]["ctx"].kind == "member_home"


@pytest.mark.asyncio
async def test_complete_telegram_link_expired(
    settings_store: dict[str, Any], accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import bot_app.access as access
    from bot_app.handlers import menu as menu_mod

    access._cached_owner = "keep"
    answers: list[str] = []

    async def capture_answer(text: str, **kwargs: Any) -> None:
        answers.append(text)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1, username="x"),
        chat=SimpleNamespace(id=1),
        answer=AsyncMock(side_effect=capture_answer),
    )
    ok = await menu_mod.complete_telegram_link(message, "not-a-real-token")
    assert ok is False
    assert answers == [menu_mod._LINK_EXPIRED]
    assert access._cached_owner == "keep"
    assert await tl.get_owner() is None


def test_access_invalidate_clears_cache() -> None:
    import bot_app.access as access

    access._cached_owner = object()
    access._cached_at_mono = 42.0
    access.invalidate()
    assert access._cached_owner is access._MISSING
    assert access._cached_at_mono == 0.0


# --- TB-1.4: resolve_owner / allowlist / open-mode ------------------------------------------


@pytest.fixture
def access_clean(monkeypatch: pytest.MonkeyPatch, accounts: FakeAccountsStore):
    """Сброс кэша access + тот же FakeAccountsStore, что у telegram_link."""
    import bot_app.access as access

    access.invalidate()
    return access


def _bot_settings(**kwargs: Any):
    from bot_app.config import BotSettings

    return BotSettings(
        _env_file=None,
        admin_user_id=kwargs.get("admin_user_id", 0),
        admin_user_ids=kwargs.get("admin_user_ids", ""),
        admin_usernames=kwargs.get("admin_usernames", ""),
    )


@pytest.mark.asyncio
async def test_resolve_owner_caches(access_clean, accounts: FakeAccountsStore) -> None:
    access = access_clean
    calls = {"n": 0}
    real_get = tl.get_owner

    async def counting_get(**kwargs):
        calls["n"] += 1
        return await real_get(**kwargs)

    import bot_app.access as access_mod

    # patch module-level get_owner used by resolve_owner
    access_mod.get_owner = counting_get  # type: ignore[method-assign]

    await tl.set_owner(user_id=7, chat_id=7, username="u")
    a = await access.resolve_owner()
    b = await access.resolve_owner()
    assert a is not None and a.telegram_user_id == 7
    assert b is not None and b.telegram_user_id == 7
    assert calls["n"] == 1

    access.invalidate()
    c = await access.resolve_owner()
    assert c is not None and c.telegram_user_id == 7
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_is_allowed_admin_env_or_db(access_clean, accounts: FakeAccountsStore) -> None:
    access = access_clean
    env = _bot_settings(admin_user_id=100)

    assert await access.is_allowed_admin(user_id=100, username=None, settings=env)
    assert not await access.is_allowed_admin(user_id=999, username=None, settings=env)

    empty = _bot_settings()
    assert not await access.is_allowed_admin(user_id=50, username="x", settings=empty)

    await tl.set_owner(user_id=50, chat_id=50, username="Linked")
    access.invalidate()
    assert await access.is_allowed_admin(user_id=50, username=None, settings=empty)
    assert await access.is_allowed_admin(user_id=None, username="linked", settings=empty)
    # Env-владелец тоже допускается рядом с DB (мультиаккаунт / бутстрап).
    assert await access.is_allowed_admin(user_id=100, username=None, settings=env)


@pytest.mark.asyncio
async def test_open_mode_no_longer_allows_everyone(
    access_clean, accounts: FakeAccountsStore
) -> None:
    access = access_clean
    empty = _bot_settings()
    assert access.is_open_bot_mode(empty)
    assert not await access.is_access_configured(empty)
    assert not await access.is_allowed_admin(user_id=1, username="anyone", settings=empty)


@pytest.mark.asyncio
async def test_is_admin_filter_rejects_stranger_in_open_mode(
    access_clean, accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-1.9: пустой env + нет DB-owner → IsAdmin отсекает чужого (не open-всем)."""
    from types import SimpleNamespace

    import bot_app.access as access
    from bot_app.filters import IsAdmin

    monkeypatch.setattr(access, "get_bot_settings", lambda: _bot_settings())
    filt = IsAdmin()
    event = SimpleNamespace(from_user=SimpleNamespace(id=999, username="stranger"))
    assert await filt(event) is False

    await tl.set_owner(user_id=42, chat_id=42, username="Owner")
    access.invalidate()
    assert await filt(SimpleNamespace(from_user=SimpleNamespace(id=42, username="Owner")))
    assert not await filt(SimpleNamespace(from_user=SimpleNamespace(id=999, username="x")))
    assert not await filt(SimpleNamespace(from_user=None))


# --- TB-1.5: push_chat_id — DB-owner приоритетнее env ---------------------------------------


@pytest.mark.asyncio
async def test_push_chat_id_prefers_db_owner(
    access_clean, accounts: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bot_app.config import push_chat_id

    env = _bot_settings(admin_user_id=100)
    monkeypatch.setattr("bot_app.config.get_bot_settings", lambda: env)

    assert await push_chat_id(settings=env) == 100

    await tl.set_owner(user_id=50, chat_id=777, username="db")
    access_clean.invalidate()
    assert await push_chat_id(settings=env) == 777


@pytest.mark.asyncio
async def test_push_chat_id_none_when_unconfigured(
    access_clean, accounts: FakeAccountsStore
) -> None:
    from bot_app.config import push_chat_id

    empty = _bot_settings()
    assert await push_chat_id(settings=empty) is None
