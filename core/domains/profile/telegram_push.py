"""Очередь «отправить себе в Telegram» из веба.

API кладёт задачу `tg_push` в `platform.tasks`; доставку делает процесс бота
(handler — TB-6.2). Идемпотентный ключ на минуту гасит даблклик кнопки.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from core.platform.tasks import TaskRecord, enqueue

TG_PUSH_KIND = "tg_push"
ADMIN_MESSAGE_KIND = "admin_message"
# Заявка на ключ OpenRouter с сайта — единственный пуш, который идёт ОПЕРАТОРУ, а не автору
# действия (payload без account_id → получателя резолвит push_handler._resolve_recipient).
KEY_REQUEST_KIND = "key_request"

PushKind = Literal[
    "vacancy_card", "screening_pack", "prep_questions", "offer_summary", "screening_chat_summary"
]

PUSH_KINDS: frozenset[str] = frozenset(
    {"vacancy_card", "screening_pack", "prep_questions", "offer_summary", "screening_chat_summary"}
)

# Пользовательский жест из веба — выше фоновых cron'ов (100), рядом с salary_estimate.
_PUSH_PRIORITY = 40


def push_idempotency_key(kind: str, vacancy_id: str, *, at: datetime | None = None) -> str:
    """Ключ `tg_push:{kind}:{vacancy_id}:{minute}` — минута UTC (YYYYMMDDHHMM)."""
    when = at or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    minute = when.astimezone(UTC).strftime("%Y%m%d%H%M")
    return f"{TG_PUSH_KIND}:{kind}:{vacancy_id}:{minute}"


async def enqueue_tg_push(
    kind: PushKind,
    vacancy_id: str,
    *,
    account_id: int,
    at: datetime | None = None,
    text: str | None = None,
) -> TaskRecord:
    """Поставить пуш в очередь (валидация «своя вакансия» — на стороне API).

    `account_id` — СВОЙ аккаунт вызывающего (plans/multitenancy_gaps_2026_08_06.md §3.11),
    не глобальный владелец: несёт его и в `payload` (доставка читает оттуда получателя —
    `bot_app.services.push_handler`), и как поле задачи (фильтр `/api/background-tasks`,
    приоритет ключа OpenRouter в контексте задачи, M6).

    `text` — готовый текст для kind'ов, чей контент собирается один раз на клике (например
    LLM-саммари чата), а не пересобирается заново в момент доставки, как остальные kind'ы.
    """
    vid = vacancy_id.strip()
    when = at or datetime.now(UTC)
    payload: dict[str, Any] = {"kind": kind, "vacancy_id": vid, "account_id": account_id}
    if text is not None:
        payload["text"] = text
    return await enqueue(
        TG_PUSH_KIND,
        payload=payload,
        priority=_PUSH_PRIORITY,
        idempotency_key=push_idempotency_key(kind, vid, at=when),
        max_attempts=3,
        account_id=account_id,
    )


__all__ = [
    "ADMIN_MESSAGE_KIND",
    "PUSH_KINDS",
    "TG_PUSH_KIND",
    "PushKind",
    "enqueue_tg_push",
    "push_idempotency_key",
]
