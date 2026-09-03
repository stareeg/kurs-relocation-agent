"""Реестр исходящих сообщений бота в Postgres (`tg_ui_messages`).

Нужен для «живого» меню (последнее на чат) и отложенной уборки progress/digest/service.
Все операции best-effort: падение PG → пустой результат / None, вызывающий путь не ломается.

M5 (plans/multitenancy_gaps_2026_08_06.md §2, «низкий приоритет»): таблица де-факто уже
изолирована по `chat_id` (один Telegram-чат = один аккаунт) — здесь только резолв `account_id`
для FK/единообразия при записи, не полноценная per-account фильтрация чтения (её `chat_id` даёт
и так). Резолв — внутри `track()`, а не параметром из вызывающих: `track_kind=` дёргается из
глубины `telegram_send.safe_reply/safe_send` десятками мест, протаскивать `account_id` через все
них ради вспомогательного реестра не стоило бы своей цены.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

MessageKind = Literal["menu", "card", "progress", "digest", "service", "hr_card"]

KIND_MENU: MessageKind = "menu"
KIND_CARD: MessageKind = "card"
KIND_PROGRESS: MessageKind = "progress"
KIND_DIGEST: MessageKind = "digest"
KIND_SERVICE: MessageKind = "service"
KIND_HR_CARD: MessageKind = "hr_card"

# TB-4.5: progress/service всегда получают cleanup_after, даже без ttl у вызывающего.
_DEFAULT_KIND_TTL_SEC: dict[str, float] = {
    KIND_PROGRESS: 3600.0,
    KIND_SERVICE: 3600.0,
}

_RETURNING = "id, chat_id, message_id, kind, vacancy_id, cleanup_after, created_at"


@dataclass(frozen=True)
class TrackedMessage:
    """Строка реестра после pop / due_cleanup."""

    id: int
    chat_id: int
    message_id: int
    kind: str
    vacancy_id: str | None
    cleanup_after: datetime | None
    created_at: datetime | None = None


def _resolve_cleanup_after(
    ttl: timedelta | float | int | None,
    *,
    kind: str,
) -> datetime | None:
    effective = ttl
    if effective is None:
        default_sec = _DEFAULT_KIND_TTL_SEC.get(kind)
        if default_sec is None:
            return None
        effective = default_sec
    delta = effective if isinstance(effective, timedelta) else timedelta(seconds=float(effective))
    return datetime.now(UTC) + delta


def _row_to_tracked(row: Any) -> TrackedMessage:
    d = row_to_dict(row)
    return TrackedMessage(
        id=int(d["id"]),
        chat_id=int(d["chat_id"]),
        message_id=int(d["message_id"]),
        kind=str(d["kind"]),
        vacancy_id=d.get("vacancy_id"),
        cleanup_after=d.get("cleanup_after"),
        created_at=d.get("created_at"),
    )


async def track(
    chat_id: int,
    message_id: int,
    kind: str,
    *,
    vacancy_id: str | None = None,
    ttl: timedelta | float | int | None = None,
    db: Executor | None = None,
) -> int | None:
    """Записать исходящее сообщение. Возвращает id строки или None при сбое PG."""
    cleanup_after = _resolve_cleanup_after(ttl, kind=kind)
    try:
        from core.platform.repo.accounts import (
            get_account_by_telegram_chat_id,
            resolve_default_account_id,
        )

        pool = db or get_pool()
        account = await get_account_by_telegram_chat_id(chat_id, db=pool)
        account_id = (
            account.id if account is not None else await resolve_default_account_id(db=pool)
        )
        if account_id is None:
            return None
        row_id = await pool.fetchval(
            """
            insert into tg_ui_messages
                (chat_id, message_id, kind, vacancy_id, cleanup_after, account_id)
            values ($1, $2, $3, $4, $5, $6)
            returning id
            """,
            chat_id,
            message_id,
            kind,
            vacancy_id,
            cleanup_after,
            account_id,
        )
        return int(row_id) if row_id is not None else None
    except Exception as exc:  # noqa: BLE001 — реестр не должен ронять отправку
        logger.debug(
            "tg_ui_messages track failed chat=%s msg=%s kind=%s: %s",
            chat_id,
            message_id,
            kind,
            exc,
        )
        return None


async def pop_kind(
    chat_id: int,
    kind: str,
    *,
    db: Executor | None = None,
) -> list[TrackedMessage]:
    """Удалить из реестра все сообщения kind в чате; вернуть их (для delete_message)."""
    try:
        pool = db or get_pool()
        rows = await pool.fetch(
            f"""
            delete from tg_ui_messages
            where chat_id = $1 and kind = $2
            returning {_RETURNING}
            """,
            chat_id,
            kind,
        )
        return [_row_to_tracked(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tg_ui_messages pop_kind failed chat=%s kind=%s: %s",
            chat_id,
            kind,
            exc,
        )
        return []


async def pop_by_vacancy(
    chat_id: int,
    kind: str,
    vacancy_id: str,
    *,
    db: Executor | None = None,
) -> list[TrackedMessage]:
    """Удалить из реестра сообщения kind+vacancy_id; newest first."""
    vid = (vacancy_id or "").strip()
    if not vid:
        return []
    try:
        pool = db or get_pool()
        rows = await pool.fetch(
            f"""
            delete from tg_ui_messages
            where chat_id = $1 and kind = $2 and vacancy_id = $3
            returning {_RETURNING}
            """,
            chat_id,
            kind,
            vid,
        )
        items = [_row_to_tracked(r) for r in rows]
        items.sort(
            key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return items
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tg_ui_messages pop_by_vacancy failed chat=%s kind=%s vid=%s: %s",
            chat_id,
            kind,
            vid,
            exc,
        )
        return []


async def due_cleanup(*, db: Executor | None = None) -> list[TrackedMessage]:
    """Вынуть из реестра строки с cleanup_after <= now() (для cron-уборки TB-3.7)."""
    try:
        pool = db or get_pool()
        rows = await pool.fetch(
            f"""
            delete from tg_ui_messages
            where cleanup_after is not null and cleanup_after <= now()
            returning {_RETURNING}
            """
        )
        return [_row_to_tracked(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("tg_ui_messages due_cleanup failed: %s", exc)
        return []


async def untrack(
    chat_id: int,
    message_id: int,
    *,
    db: Executor | None = None,
) -> int:
    """Удалить строки реестра для конкретного TG-сообщения. Число удалённых / 0 при сбое."""
    try:
        pool = db or get_pool()
        rows = await pool.fetch(
            """
            delete from tg_ui_messages
            where chat_id = $1 and message_id = $2
            returning id
            """,
            chat_id,
            message_id,
        )
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tg_ui_messages untrack failed chat=%s msg=%s: %s",
            chat_id,
            message_id,
            exc,
        )
        return 0


async def retrack(
    chat_id: int,
    message_id: int,
    kind: str,
    *,
    vacancy_id: str | None = None,
    ttl: timedelta | float | int | None = None,
    db: Executor | None = None,
) -> int | None:
    """Сменить kind/ttl у уже отправленного сообщения (edit-in-place → финал)."""
    await untrack(chat_id, message_id, db=db)
    return await track(
        chat_id,
        message_id,
        kind,
        vacancy_id=vacancy_id,
        ttl=ttl,
        db=db,
    )


__all__ = [
    "KIND_CARD",
    "KIND_DIGEST",
    "KIND_HR_CARD",
    "KIND_MENU",
    "KIND_PROGRESS",
    "KIND_SERVICE",
    "MessageKind",
    "TrackedMessage",
    "due_cleanup",
    "pop_by_vacancy",
    "pop_kind",
    "retrack",
    "track",
    "untrack",
]
