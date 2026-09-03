"""Настройки пушей Telegram (`app_settings.telegram_prefs`).

Ключ jsonb без отдельной таблицы. Дефолты при отсутствии строки / мусоре в БД.
Чтение в боте — через `get_telegram_prefs()` (прямой `get_setting`, без кэша:
частота пушей мала). API/фронт — через `GET/PATCH /api/settings.telegram_prefs`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.platform.db.pool import Executor
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

KEY_PREFS = "telegram_prefs"

DigestMode = Literal["smart", "always", "off"]
WarmupSummaryMode = Literal["results", "always", "off"]
CardStyle = Literal["image", "text"]
BatchCleanupMode = Literal["ask", "auto", "off"]


class TelegramPrefs(BaseModel):
    """Предпочтения владельца по пушам и карточкам бота."""

    model_config = ConfigDict(extra="ignore")

    digest: DigestMode = "smart"
    warmup_summary: WarmupSummaryMode = "results"
    card_style: CardStyle = "image"
    # UI селектов убран: уборка всегда сразу после извлечения (режим «Сам»).
    batch_cleanup: BatchCleanupMode = "auto"


DEFAULT_TELEGRAM_PREFS = TelegramPrefs()


def default_telegram_prefs_dict() -> dict[str, Any]:
    """Сериализованные дефолты для `default_app_settings_values` / сидов."""
    return DEFAULT_TELEGRAM_PREFS.model_dump()


def prefs_from_mapping(raw: Any) -> TelegramPrefs:
    """Разобрать jsonb; нет / мусор / битые enum → дефолты (частичные ключи мержатся)."""
    if not isinstance(raw, dict):
        return TelegramPrefs()
    try:
        return TelegramPrefs.model_validate(raw)
    except Exception:
        logger.debug("telegram_prefs: некорректные данные, использую дефолты: %r", raw)
        return TelegramPrefs()


async def get_telegram_prefs(
    *, account_id: int | None, db: Executor | None = None
) -> TelegramPrefs:
    """Текущие prefs; нет строки / ошибка PG → дефолты. Без in-process кэша."""
    raw = await get_setting(KEY_PREFS, default=None, account_id=account_id, db=db)
    return prefs_from_mapping(raw)


async def set_telegram_prefs(
    prefs: TelegramPrefs, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Записать prefs целиком (частичный PATCH — на стороне API в TB-2.4)."""
    await set_setting(KEY_PREFS, prefs.model_dump(), account_id=account_id, db=db)


__all__ = [
    "KEY_PREFS",
    "BatchCleanupMode",
    "CardStyle",
    "DEFAULT_TELEGRAM_PREFS",
    "DigestMode",
    "TelegramPrefs",
    "WarmupSummaryMode",
    "default_telegram_prefs_dict",
    "get_telegram_prefs",
    "prefs_from_mapping",
    "set_telegram_prefs",
]
