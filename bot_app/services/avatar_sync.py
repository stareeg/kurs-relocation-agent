"""Автоподтяжка фото профиля Telegram в аватар владельца.

Вызывается из хендлеров выдачи токена (`handlers/menu.py`, `cb_auth_token`/`cmd_token`) — тот
самый момент авторизации, о котором просил план. Best-effort: нет фото, сеть легла, PG
недоступен — тихо ничего не делает, не должно ронять выдачу токена ради необязательной картинки.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from core.domains.profile import avatar
from core.platform.repo.accounts import get_account_by_telegram_user_id

logger = logging.getLogger(__name__)


async def sync_owner_avatar_from_telegram(bot: Bot, user_id: int) -> None:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos.photos:
            return
        largest = photos.photos[0][-1]
        buf = await bot.download(largest)
        raw = await asyncio.to_thread(lambda b: b.read() if b is not None else b"", buf)
        if not raw:
            return
        account = await get_account_by_telegram_user_id(user_id)
        await avatar.set_telegram_avatar(raw, account_id=account.id if account else None)
    except Exception as exc:  # noqa: BLE001 — аватар необязателен, вход не должен от него зависеть
        logger.warning("avatar: не удалось подтянуть фото Telegram user_id=%s: %s", user_id, exc)


__all__ = ["sync_owner_avatar_from_telegram"]
