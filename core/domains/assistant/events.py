"""События домена assistant: что публикует и на что подписан (шина — A-11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import AttachmentAnalyzed

PUBLISHES: tuple[type, ...] = (AttachmentAnalyzed,)
SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = ()
SUBSCRIBES: tuple[type, ...] = ()


def publish_attachment_analyzed(*, attachment_id: int, kind: str) -> None:
    """Вложение распознано (или распознавание провалилось) — фронт освежает чип/ленту.

    Без ожидания: единственный эффект — инвалидация query key `["attachment", id]`
    (`frontend/src/app/use-live-invalidation.ts`), синхронных обязательств нет.
    """
    ports.events().publish(AttachmentAnalyzed(attachment_id=attachment_id, kind=kind))


__all__ = [
    "AttachmentAnalyzed",
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "publish_attachment_analyzed",
]
