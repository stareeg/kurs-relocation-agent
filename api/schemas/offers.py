"""Транспортные схемы офферов.

Доменные/HTTP-модели уже живут в ``core.domains.offers.models`` — реэкспорт
для единообразия ``api.schemas.<domain>`` и импортов роутера.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.attachments import AttachmentOut
from core.domains.offers.models import (
    OfferCompareRequest,
    OfferCompareResponse,
    OfferCreateRequest,
    OfferNegotiateResponse,
    OfferParseApiRequest,
    OfferParseRequest,
    OfferRecord,
    OfferReorderRequest,
    OfferUpdateRequest,
)


class OffersChatMessageOut(BaseModel):
    """Реплика чата вкладки «Офферы». role: user (владелец) | assistant (LLM)."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    reply_to_message_id: int | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    created_at: datetime | None = None


class OffersChatHistory(BaseModel):
    """История чата по офферам аккаунта запроса (хронологически). Нет PG → []."""

    items: list[OffersChatMessageOut] = Field(default_factory=list)


__all__ = [
    "OfferCompareRequest",
    "OfferCompareResponse",
    "OfferCreateRequest",
    "OfferNegotiateResponse",
    "OfferParseApiRequest",
    "OfferParseRequest",
    "OfferRecord",
    "OfferReorderRequest",
    "OfferUpdateRequest",
    "OffersChatHistory",
    "OffersChatMessageOut",
]
