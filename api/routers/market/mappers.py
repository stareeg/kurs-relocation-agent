"""Мапперы транспортных схем `market` — вынесены из `analytics.py`, чтобы обработчики роутера
оставались тонкими (A-12). Зеркало `api/routers/assistant/mappers.py::prep_chat_history` для
чата «Рынка» (Заход 6, п.7: паритет с чатом по вакансии)."""

from __future__ import annotations

from collections.abc import Sequence

from api.schemas.attachments import attachment_meta_out
from api.schemas.market import MarketChatHistory, MarketChatMessageOut
from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.market.market_chat import MarketChatMessage


def market_chat_message_out(
    message: MarketChatMessage, attachments: Sequence[AttachmentMeta] = ()
) -> MarketChatMessageOut:
    return MarketChatMessageOut(
        id=message.id or 0,
        role=message.role,
        content=message.content,
        reply_to_message_id=message.reply_to_message_id,
        attachments=[attachment_meta_out(a) for a in attachments],
        created_at=message.created_at,
    )


def market_chat_history(
    messages: Sequence[MarketChatMessage],
    message_attachments: dict[int, list[AttachmentMeta]] | None = None,
) -> MarketChatHistory:
    attachments_map = message_attachments or {}
    return MarketChatHistory(
        items=[market_chat_message_out(m, attachments_map.get(m.id or 0, [])) for m in messages]
    )


__all__ = ["market_chat_history", "market_chat_message_out"]
