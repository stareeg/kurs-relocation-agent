"""Транспортные схемы API: auth по токену из Telegram-бота."""

from __future__ import annotations

from pydantic import BaseModel, Field

# --- Auth ---


class TokenLoginRequest(BaseModel):
    """Логин: сырой токен, выданный ботом (кнопка «Токен авторизации»)."""

    token: str = Field(min_length=1)


class AuthStatusResponse(BaseModel):
    """Статус входа и онбординга — публичная ручка, только булевы флаги (без секретов).

    Фронт по ней решает: пускать в разделы (`authed` + оба токена настроены), куда
    редиректить при старте (Параметры → Расширение → Резюме) и что показывать в форме входа.
    """

    authed: bool
    auth_token_configured: bool
    openrouter_key_configured: bool
    extension_confirmed: bool
    bot_configured: bool
    bot_username: str | None = None
    # username Telegram-аккаунта, которому выпущен токен («вход как @user»).
    account_username: str | None = None
    # True только если запрос уже авторизован аккаунтом role=owner. Анонимный /auth/status
    # подставляет owner для флагов онбординга — is_admin при этом обязан остаться false.
    is_admin: bool = False


class LogoutResponse(BaseModel):
    ok: bool = True


class SessionResponse(BaseModel):
    """Лёгкий пинг сессии: без БД, только факт авторизации."""

    authed: bool = True


# --- Устройства (Part C: многоустройственные сессии) ---


class DeviceSession(BaseModel):
    """Одна активная сессия входа — строка в блоке «Устройства» (Параметры). Не выдумываем
    название устройства: `login_user_agent` — то, что реально пришло в заголовке, или `None`."""

    id: int
    issued_at: str
    is_current: bool
    telegram_username: str | None = None
    login_user_agent: str | None = None


class DeviceSessionsResponse(BaseModel):
    sessions: list[DeviceSession]


class RevokeSessionResponse(BaseModel):
    ok: bool


class RevokeAllSessionsResponse(BaseModel):
    revoked: int


__all__ = [
    "AuthStatusResponse",
    "DeviceSession",
    "DeviceSessionsResponse",
    "LogoutResponse",
    "RevokeAllSessionsResponse",
    "RevokeSessionResponse",
    "SessionResponse",
    "TokenLoginRequest",
]
