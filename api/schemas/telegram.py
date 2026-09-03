"""Транспортные схемы API: привязка Telegram, prefs и пуш из веба."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TelegramStatusResponse(BaseModel):
    """Статус бота и привязки владельца для страницы «Параметры»."""

    bot_configured: bool
    bot_username: str | None = None
    linked: bool
    linked_username: str | None = None


class TelegramLinkTokenResponse(BaseModel):
    """Одноразовый deep-link для /start link_<token> (TTL 10 мин)."""

    deep_link: str
    expires_at: datetime


TelegramPushKind = Literal[
    "vacancy_card",
    "screening_pack",
    "prep_questions",
    "offer_summary",
    "screening_chat_summary",
]


class TelegramPushRequest(BaseModel):
    """Запрос «отправить себе в Telegram» из веба."""

    kind: TelegramPushKind
    vacancy_id: str = Field(min_length=1)


class TelegramPushResponse(BaseModel):
    """Задача поставлена в очередь `tg_push` (доставка — процесс бота)."""

    queued: bool = True
    task_id: int
    kind: TelegramPushKind
    vacancy_id: str


DigestMode = Literal["smart", "always", "off"]
WarmupSummaryMode = Literal["results", "always", "off"]
CardStyle = Literal["image", "text"]
BatchCleanupMode = Literal["ask", "auto", "off"]


class TelegramPrefs(BaseModel):
    """Пуши и карточки бота (`app_settings.telegram_prefs`)."""

    model_config = ConfigDict(extra="ignore")

    digest: DigestMode = "smart"
    warmup_summary: WarmupSummaryMode = "results"
    card_style: CardStyle = "image"
    batch_cleanup: BatchCleanupMode = "auto"


__all__ = [
    "BatchCleanupMode",
    "CardStyle",
    "DigestMode",
    "TelegramLinkTokenResponse",
    "TelegramPrefs",
    "TelegramPushKind",
    "TelegramPushRequest",
    "TelegramPushResponse",
    "TelegramStatusResponse",
    "WarmupSummaryMode",
]
