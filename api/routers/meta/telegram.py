"""Привязка Telegram из веба + пуш карточек.

Без aiogram: username бота — httpx `getMe` + кэш `telegram_bot_identity` в app_settings.
Токен и owner — `core.domains.profile.telegram_link`. api не импортирует bot_app.
Пуш — очередь `tg_push` (доставка handler'ом бота).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from api.config import get_settings
from api.schemas.telegram import (
    TelegramLinkTokenResponse,
    TelegramPushRequest,
    TelegramPushResponse,
    TelegramStatusResponse,
)
from api.security import AccountContext, require_account_context
from core.domains.opportunities.jobs import get_job_by_vacancy_id
from core.domains.profile import telegram_link as tg
from core.domains.profile import telegram_push as tg_push
from core.platform.http import get_http_client, request_timeout
from core.platform.repo.accounts import get_account_by_telegram_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_GETME_TIMEOUT_S = 15.0
_NOT_LINKED = "Привяжи Telegram в Параметрах"


async def fetch_bot_username(bot_token: str) -> str | None:
    """Живой вызов Telegram `getMe` → username без @; ошибка сети/токена → None."""
    token = bot_token.strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = await get_http_client().get(url, timeout=request_timeout(_GETME_TIMEOUT_S))
        resp.raise_for_status()
        data: Any = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("telegram getMe недоступен: %s", exc)
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        logger.warning("telegram getMe: ok=false")
        return None
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    raw = result.get("username")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().lstrip("@")


async def resolve_bot_username(bot_token: str) -> str | None:
    """Username бота: кэш app_settings → getMe (с записью кэша) → официальный бот из конфига.

    Фолбэк на TELEGRAM_BOT_USERNAME в кэш не пишем: кэш — только подтверждённый getMe.
    """
    cached = await tg.get_bot_identity()
    if cached is not None and cached.username:
        return cached.username
    username = await fetch_bot_username(bot_token)
    if username:
        await tg.set_bot_identity(username)
        return username
    fallback = get_settings().telegram_bot_username.strip().lstrip("@")
    return fallback or None


async def build_status_response() -> TelegramStatusResponse:
    token = get_settings().telegram_bot_token.strip()
    bot_configured = bool(token)
    bot_username = await resolve_bot_username(token) if bot_configured else None
    owner = await tg.get_owner()
    return TelegramStatusResponse(
        bot_configured=bot_configured,
        bot_username=bot_username,
        linked=owner is not None,
        linked_username=owner.telegram_username if owner else None,
    )


async def issue_link_token_response() -> TelegramLinkTokenResponse:
    token = get_settings().telegram_bot_token.strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Telegram-бот не настроен — задайте TELEGRAM_BOT_TOKEN в .env",
        )
    bot_username = await resolve_bot_username(token)
    if not bot_username:
        raise HTTPException(
            status_code=502,
            detail="Не удалось узнать username бота (getMe). Проверьте токен и сеть.",
        )
    issued = await tg.create_link_token()
    return TelegramLinkTokenResponse(
        deep_link=tg.build_deep_link(bot_username, issued.start_payload),
        expires_at=issued.expires_at,
    )


@router.get("/status", response_model=TelegramStatusResponse)
async def telegram_status() -> TelegramStatusResponse:
    """Состояние бота и привязки для UI «Параметры» / расширения."""
    return await build_status_response()


@router.post("/link-token", response_model=TelegramLinkTokenResponse)
async def create_telegram_link_token() -> TelegramLinkTokenResponse:
    """Выпустить одноразовый deep-link `t.me/<bot>?start=link_<token>` (TTL 10 мин)."""
    return await issue_link_token_response()


@router.delete("/link", status_code=204, response_model=None)
async def unlink_telegram(account: AccountContext = Depends(require_account_context)) -> None:
    """Отвязать СВОЙ аккаунт и сбросить pending-токен.

    M7: раньше безусловно гасило владельца — любой залогиненный member мог выключить чужой
    аккаунт (plans/multitenancy_gaps_2026_08_06.md §3.11).
    """
    await tg.unlink(account_id=account.account_id)


async def enqueue_push_response(
    body: TelegramPushRequest, *, account: AccountContext
) -> TelegramPushResponse:
    """Валидация «своя вакансия» → enqueue `tg_push` в чат самого вызывающего (идемпотентность
    на минуту). M7: раньше резолвило глобального владельца (`tg.get_owner()`) — member либо
    получал 404, либо пуш незаметно улетал в чат владельца."""
    caller = await get_account_by_telegram_user_id(account.telegram_user_id)
    if caller is None:
        raise HTTPException(status_code=409, detail=_NOT_LINKED)

    vid = body.vacancy_id.strip()
    if not vid:
        raise HTTPException(status_code=422, detail="vacancy_id пуст")

    job = await get_job_by_vacancy_id(vid, account_id=caller.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    task = await tg_push.enqueue_tg_push(body.kind, vid, account_id=caller.id)
    return TelegramPushResponse(
        queued=True,
        task_id=task.id,
        kind=body.kind,
        vacancy_id=vid,
    )


@router.post("/push", response_model=TelegramPushResponse)
async def telegram_push(
    body: TelegramPushRequest, account: AccountContext = Depends(require_account_context)
) -> TelegramPushResponse:
    """Поставить пуш СЕБЕ в очередь (карточка / скрининг / тех / оффер)."""
    return await enqueue_push_response(body, account=account)
