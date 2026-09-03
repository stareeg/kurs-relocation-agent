"""Аутентификация фронта: вход по токену из Telegram-бота (Этап 2).

`GET /auth/status` — публичный статус входа и онбординга (только булевы флаги): фронт по нему
гейтит разделы и ведёт онбординг Параметры → Расширение → Резюме без мёртвых путей.
`POST /auth/token` — вставленный токен → httponly-cookie на год. Принимает и переносимые
гостевые токены центрального бота (`cc.…`): свежая установка привязывается к
аккаунту из токена, уже привязанная — принимает только токены того же аккаунта.
`POST /auth/logout` — отзыв ОДНОЙ сессии (той, что в cookie; перевыпуск — кнопкой в боте) +
снос cookie.

`GET /auth/sessions` / `POST /auth/sessions/{id}/revoke` / `POST /auth/sessions/revoke-all` —
блок «Устройства» в Параметрах (Part C): у аккаунта может быть несколько одновременно активных
сессий (по одной на устройство/браузер), список + отзыв по одной + отзыв всех разом.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response

from api.config import get_settings
from api.schemas import (
    AuthStatusResponse,
    DeviceSession,
    DeviceSessionsResponse,
    LogoutResponse,
    RevokeAllSessionsResponse,
    RevokeSessionResponse,
    TokenLoginRequest,
)
from api.security import (
    AUTH_COOKIE,
    AUTH_COOKIE_MAX_AGE_S,
    AccountContext,
    client_ip,
    invalidate_web_auth_cache,
    require_account_context,
    resolve_request_account,
)
from core.domains.profile import telegram_link as tg
from core.domains.profile import web_auth
from core.platform.observability import event
from core.platform.repo.accounts import get_account_by_id, get_owner_account, telegram_username_map
from core.platform.repo.settings import is_extension_confirmed, is_openrouter_key_configured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


async def build_auth_status(
    *,
    authed: bool,
    account_id: int | None,
    telegram_username: str | None,
    role: str | None = None,
) -> AuthStatusResponse:
    """Собрать статус входа/онбординга. Только чтение PG; живых вызовов Telegram нет.

    `openrouter_key_configured`/`extension_confirmed`/`account_username` резолвятся по
    залогиненному аккаунту, а до логина/в bootstrap-окне (`account_id=None`) — по владельцу
    (тот же смысл, что был у единственной глобальной записи до Этапа 2: анонимный визит на
    `/auth/status` видит общее состояние онбординга инсталляции, не только «свою» персону).

    `is_admin` смотрит на роль ИМЕННО предъявленного аккаунта, не на подставленного owner:
    иначе аноним увидел бы пункт «Админ» в меню.

    `bot_username` — из кэша getMe (`telegram_bot_identity`), а до первого запуска бота —
    официальный бот из конфига (TELEGRAM_BOT_USERNAME): ссылка t.me/… на фронте есть всегда,
    пользователи не создают своих ботов.
    """
    is_admin = bool(authed and role == "owner")
    settings = get_settings()
    identity = await tg.get_bot_identity()
    fallback_username = settings.telegram_bot_username.strip().lstrip("@")
    if account_id is None:
        owner = await get_owner_account()
        if owner is not None:
            account_id, telegram_username = owner.id, owner.telegram_username
    return AuthStatusResponse(
        authed=authed,
        auth_token_configured=await web_auth.any_web_auth_token_issued(),
        openrouter_key_configured=await is_openrouter_key_configured(account_id=account_id),
        extension_confirmed=await is_extension_confirmed(account_id=account_id),
        bot_configured=bool(settings.telegram_bot_token.strip()),
        bot_username=(identity.username if identity else None) or fallback_username or None,
        account_username=telegram_username,
        is_admin=is_admin,
    )


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(
    x_api_key: str | None = Header(default=None),
    x_auth_token: str | None = Header(default=None),
    x_extension_version: str | None = Header(default=None, alias="X-Extension-Version"),
    copilot_auth: str | None = Cookie(default=None),
) -> AuthStatusResponse:
    """Публичная ручка: жива ли авторизация запроса + флаги онбординга."""
    account, authed = await resolve_request_account(
        x_api_key, x_auth_token, copilot_auth, x_extension_version=x_extension_version
    )
    return await build_auth_status(
        authed=authed,
        account_id=account.account_id if account else None,
        telegram_username=account.telegram_username if account else None,
        role=account.role if account else None,
    )


async def perform_token_login(
    raw_token: str, response: Response, *, user_agent: str | None = None, ip: str | None = None
) -> AuthStatusResponse:
    """Сверить вставленный токен с записью бота → httponly-cookie на год.

    Чтение записи — свежее (мимо кэша require_account): токен, выпущенный ботом секунду назад,
    должен приниматься сразу. Невалидный токен → 401 с подсказкой, что делать; каждый отказ
    логируется (WARNING, с IP) — раньше неудачные попытки входа не оставляли следа вообще.

    Переносимый токен (`cc.…`, — выдан центральным ботом гостю): свежая установка
    принимает его и заводит СВОЙ аккаунт (`role='owner'`) из идентичности токена; уже
    привязанная установка принимает новый переносимый токен ТОГО ЖЕ аккаунта (перевыпуск в
    боте, вход после логаута). Чужой аккаунт — 401: чужим переносимым токеном занятую
    установку не увести.
    """
    token = raw_token.strip()
    account = await web_auth.find_account_by_raw_token(token)

    if account is None:
        portable = web_auth.parse_portable_token(token)
        if portable is not None:
            existing_owner = await get_owner_account()
            if existing_owner is not None and existing_owner.telegram_user_id != portable.user_id:
                event(
                    logger,
                    "АВТОРИЗАЦИЯ",
                    "вход отклонён (переносимый токен чужого аккаунта) ip=%s",
                    ip or "-",
                    level=logging.WARNING,
                    reason="foreign_portable_token",
                    ip=ip,
                )
                raise HTTPException(
                    status_code=401,
                    detail="Токен выпущен для другого Telegram-аккаунта — "
                    "эта установка уже привязана к своему владельцу",
                )
            account = await web_auth.adopt_portable_token(token, portable)

    if account is None:
        owner = await get_owner_account()
        if owner is None:
            event(
                logger,
                "АВТОРИЗАЦИЯ",
                "вход отклонён (токен ещё не выпущен) ip=%s",
                ip or "-",
                level=logging.WARNING,
                reason="not_issued_yet",
                ip=ip,
            )
            raise HTTPException(
                status_code=401,
                detail="Токен ещё не выпущен — нажмите «Токен авторизации» в Telegram-боте",
            )
        revoked = await web_auth.token_ever_issued(token)
        detail = (
            "Токен отозван — сгенерируйте новый в боте (кнопка «Токен авторизации»)"
            if revoked
            else "Токен не подходит — сгенерируйте новый в боте (кнопка «Токен авторизации»)"
        )
        event(
            logger,
            "АВТОРИЗАЦИЯ",
            "вход отклонён (%s) ip=%s",
            "токен отозван" if revoked else "токен неверный",
            ip or "-",
            level=logging.WARNING,
            reason="revoked" if revoked else "invalid",
            ip=ip,
        )
        raise HTTPException(status_code=401, detail=detail)

    response.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=AUTH_COOKIE_MAX_AGE_S,
        secure=get_settings().web_cookie_secure,
    )
    # Декоративная подпись строки в блоке «Устройства» — не критичный путь, не блокирует логин.
    await web_auth.record_login_metadata(token, user_agent=user_agent, ip=ip)
    invalidate_web_auth_cache()
    event(
        logger,
        "АВТОРИЗАЦИЯ",
        "вход по токену account_id=%s ip=%s",
        account.id,
        ip or "-",
        account_id=account.id,
        ip=ip,
    )
    return await build_auth_status(
        authed=True,
        account_id=account.id,
        telegram_username=account.telegram_username,
        role=account.role,
    )


@router.post("/auth/token", response_model=AuthStatusResponse)
async def login_with_token(
    body: TokenLoginRequest,
    response: Response,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> AuthStatusResponse:
    """Логин по токену из Telegram-бота."""
    return await perform_token_login(
        body.token, response, user_agent=user_agent, ip=client_ip(request)
    )


@router.post("/auth/logout", response_model=LogoutResponse)
async def logout(
    response: Response, copilot_auth: str | None = Cookie(default=None)
) -> LogoutResponse:
    """Выход «с этого устройства»: отозвать ТОЛЬКО сессию предъявленной cookie (остальные
    активные сессии аккаунта не трогает — для полного выхода см. `/auth/sessions/revoke-all`)
    и снести cookie. Best-effort: недоступный PG не мешает выйти локально (cookie снимается
    всегда)."""
    try:
        await web_auth.revoke_session_by_token(copilot_auth)
    except Exception as exc:  # noqa: BLE001 — логаут не должен падать из-за PG
        logger.warning("auth: отзыв токена при логауте не удался: %s", exc)
    invalidate_web_auth_cache()
    response.delete_cookie(AUTH_COOKIE)
    return LogoutResponse()


# ---------- Устройства (Part C) ----------


def _device_session(
    session: web_auth.SessionRecord,
    *,
    current_token_hash: str | None,
    usernames: dict[int, str | None],
) -> DeviceSession:
    is_current = current_token_hash is not None and secrets.compare_digest(
        session.token_sha256, current_token_hash
    )
    username = (
        usernames.get(session.issued_via_telegram_user_id)
        if session.issued_via_telegram_user_id is not None
        else None
    )
    return DeviceSession(
        id=session.id,
        issued_at=session.issued_at.isoformat(),
        is_current=is_current,
        telegram_username=username,
        login_user_agent=session.login_user_agent,
    )


@router.get("/auth/sessions", response_model=DeviceSessionsResponse)
async def list_sessions(
    account: AccountContext = Depends(require_account_context),
    copilot_auth: str | None = Cookie(default=None),
) -> DeviceSessionsResponse:
    """Активные сессии текущего аккаунта — блок «Устройства» в Параметрах."""
    record = await get_account_by_id(account.account_id)
    usernames = await telegram_username_map(record) if record is not None else {}
    sessions = await web_auth.list_sessions(account.account_id)
    current_hash = web_auth.hash_token(copilot_auth) if copilot_auth else None
    return DeviceSessionsResponse(
        sessions=[
            _device_session(s, current_token_hash=current_hash, usernames=usernames)
            for s in sessions
        ]
    )


@router.post("/auth/sessions/{session_id}/revoke", response_model=RevokeSessionResponse)
async def revoke_one_session(
    session_id: int,
    account: AccountContext = Depends(require_account_context),
) -> RevokeSessionResponse:
    """Отозвать ОДНУ сессию — только свою (`revoke_session` проверяет account_id)."""
    ok = await web_auth.revoke_session(session_id, account_id=account.account_id)
    invalidate_web_auth_cache()
    return RevokeSessionResponse(ok=ok)


@router.post("/auth/sessions/revoke-all", response_model=RevokeAllSessionsResponse)
async def revoke_all_sessions_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> RevokeAllSessionsResponse:
    """«Выйти на всех устройствах» — включая то, с которого пришёл запрос (вынуждает
    re-login отовсюду, cookie этой вкладки снести должен фронт после успешного ответа)."""
    revoked = await web_auth.revoke_all_sessions(account.account_id)
    invalidate_web_auth_cache()
    return RevokeAllSessionsResponse(revoked=revoked)
