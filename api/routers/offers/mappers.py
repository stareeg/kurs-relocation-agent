"""Мапперы транспортных схем чата «Офферы» — зеркало `api/routers/market/mappers.py`."""

from __future__ import annotations

from collections.abc import Sequence

from api.schemas.attachments import attachment_meta_out
from api.schemas.offers import OffersChatHistory, OffersChatMessageOut
from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.offers.offers_chat import OffersChatMessage


def offers_chat_message_out(
    message: OffersChatMessage, attachments: Sequence[AttachmentMeta] = ()
) -> OffersChatMessageOut:
    return OffersChatMessageOut(
        id=message.id or 0,
        role=message.role,
        content=message.content,
        reply_to_message_id=message.reply_to_message_id,
        attachments=[attachment_meta_out(a) for a in attachments],
        created_at=message.created_at,
    )


def offers_chat_history(
    messages: Sequence[OffersChatMessage],
    message_attachments: dict[int, list[AttachmentMeta]] | None = None,
) -> OffersChatHistory:
    attachments_map = message_attachments or {}
    return OffersChatHistory(
        items=[offers_chat_message_out(m, attachments_map.get(m.id or 0, [])) for m in messages]
    )


__all__ = ["offers_chat_history", "offers_chat_message_out"]
