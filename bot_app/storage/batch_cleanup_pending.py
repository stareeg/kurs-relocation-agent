"""In-memory очередь message_id пересланных постов для уборки.

Живёт до клика «Подчистить» / следующего батча / TTL 1ч. Рестарт бота = кнопки
мертвы — приемлемо: окно ask короткое, auto-режим не зависит от pending.
(HR-кнопки — наоборот в PG: `hr_pending` / TB-7.3.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

_TTL_SEC = 3600


@dataclass
class PendingBatchCleanup:
    message_ids: list[int]
    created_at: float = field(default_factory=time.time)


_PENDING: dict[int, PendingBatchCleanup] = {}


def _gc() -> None:
    cutoff = time.time() - _TTL_SEC
    expired = [cid for cid, v in _PENDING.items() if v.created_at < cutoff]
    for cid in expired:
        _PENDING.pop(cid, None)


def save(chat_id: int, message_ids: list[int]) -> None:
    """Запомнить id форвардов чата (перезаписывает предыдущий pending)."""
    _gc()
    ids = [int(m) for m in message_ids if m]
    if not ids:
        _PENDING.pop(int(chat_id), None)
        return
    _PENDING[int(chat_id)] = PendingBatchCleanup(message_ids=ids)


def peek(chat_id: int) -> list[int] | None:
    _gc()
    ctx = _PENDING.get(int(chat_id))
    if ctx is None:
        return None
    return list(ctx.message_ids)


def pop(chat_id: int) -> list[int] | None:
    _gc()
    ctx = _PENDING.pop(int(chat_id), None)
    if ctx is None:
        return None
    return list(ctx.message_ids)


def clear(chat_id: int) -> None:
    _PENDING.pop(int(chat_id), None)
