"""Аватар владельца: фото профиля Telegram при входе + ручная замена файлом.

Один владелец на инсталляцию (как `telegram_owner`) — храним в `app_settings`, не заводим
отдельную таблицу. Два ключа вместо одного: `custom` (ручная загрузка) и `telegram`
(автоподтяжка при выдаче токена, `bot_app.services.avatar_sync`) — ручная картинка не должна
молча слетать при следующем входе через бота, поэтому `set_telegram_avatar` не трогает её,
пока она есть. Эффективный аватар — `custom ?? telegram ?? None` (фронт рисует дефолтную
иконку при `None`).

Байты нормализуем тем же конвейером, что вложения чатов (`core.platform.images`): downscale +
перекодирование в WebP — именно это и есть «грамотное сжатие» с фронта UX6-13 просил бэкенд
подстраховать, а не только доверять клиентскому канвасу.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.platform.db.pool import Executor
from core.platform.images import decode_and_normalize
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

KEY_CUSTOM = "owner_avatar_custom"
KEY_TELEGRAM = "owner_avatar_telegram"

AvatarSource = Literal["custom", "telegram"]

# Аватар — маленькая круглая иконка в сайдбаре, не нужен полноразмерным вложениям чатов.
_MAX_SIDE_PX = 512


class AvatarImage(BaseModel):
    """Нормализованные байты (WebP, base64) + мета — хранится в `app_settings` как есть."""

    model_config = ConfigDict(extra="ignore")

    source: AvatarSource
    mime: str
    data_b64: str
    width: int
    height: int
    updated_at: datetime


def _record_from_mapping(raw: object, source: AvatarSource) -> AvatarImage | None:
    if not isinstance(raw, dict):
        return None
    try:
        return AvatarImage.model_validate({**raw, "source": source})
    except Exception:
        return None


async def _store(
    key: str,
    source: AvatarSource,
    raw: bytes,
    *,
    account_id: int | None,
    db: Executor | None = None,
) -> AvatarImage:
    normalized = await asyncio.to_thread(decode_and_normalize, raw, max_side=_MAX_SIDE_PX)
    record = AvatarImage(
        source=source,
        mime=normalized.mime,
        data_b64=base64.b64encode(normalized.data).decode("ascii"),
        width=normalized.width,
        height=normalized.height,
        updated_at=datetime.now(UTC),
    )
    await set_setting(
        key, record.model_dump(mode="json", exclude={"source"}), account_id=account_id, db=db
    )
    return record


async def set_custom_avatar(
    raw: bytes, *, account_id: int | None, db: Executor | None = None
) -> AvatarImage:
    """Ручная загрузка файлом — приоритет над Telegram навсегда, пока не удалят
    (`clear_custom_avatar`). `UnsupportedImageError` (core.platform.images) пробрасывается как
    есть — вызывающая сторона (роутер) превращает её в 400."""
    return await _store(KEY_CUSTOM, "custom", raw, account_id=account_id, db=db)


async def clear_custom_avatar(*, account_id: int | None, db: Executor | None = None) -> None:
    """Убрать ручную картинку — эффективный аватар падает обратно на Telegram/дефолт."""
    await set_setting(KEY_CUSTOM, None, account_id=account_id, db=db)


async def set_telegram_avatar(
    raw: bytes, *, account_id: int | None, db: Executor | None = None
) -> AvatarImage | None:
    """Автоподтяжка при выдаче токена (`bot_app.services.avatar_sync`).

    Не перетирает ручную картинку — если владелец сам выбрал файл, свежее фото профиля
    Telegram при следующем входе не должно молча его заменить.
    """
    custom = await get_setting(KEY_CUSTOM, default=None, account_id=account_id, db=db)
    if custom is not None:
        return None
    return await _store(KEY_TELEGRAM, "telegram", raw, account_id=account_id, db=db)


async def get_effective_avatar(
    *, account_id: int | None, db: Executor | None = None
) -> AvatarImage | None:
    """custom → telegram → None (фронт рисует дефолтную иконку пользователя)."""
    custom = _record_from_mapping(
        await get_setting(KEY_CUSTOM, default=None, account_id=account_id, db=db), "custom"
    )
    if custom is not None:
        return custom
    return _record_from_mapping(
        await get_setting(KEY_TELEGRAM, default=None, account_id=account_id, db=db), "telegram"
    )


__all__ = [
    "AvatarImage",
    "AvatarSource",
    "clear_custom_avatar",
    "get_effective_avatar",
    "set_custom_avatar",
    "set_telegram_avatar",
]
