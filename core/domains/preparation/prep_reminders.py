"""Планирование prep-напоминаний: доменная часть без aiogram.

Отправка и callback-кнопки остаются в `bot_app.services.prep_scheduler`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from core.domains.preparation.interview_stages import InterviewStage
from core.domains.preparation.models import PrepStage
from core.domains.preparation.prep import PrepReminder, schedule_reminder
from core.platform.observability import event

logger = logging.getLogger(__name__)

_REMINDER_LEAD = timedelta(hours=1)

# stage_type из enrichment → PrepStage
_STAGE_MAP: dict[str, PrepStage] = {
    "hr_screening": "screening",
    "live_coding": "tech",
    "theory": "tech",
    "system_design": "system_design",
    "business_case": "business_case",
    "soft_skills": "final",
    "manager": "final",
    "final": "final",
}


async def schedule_prep_reminder(
    *,
    interview_id: int | None,
    vacancy_id: str,
    company: str,
    position: str,
    stage: InterviewStage,
    chat_id: int,
    account_id: int,
) -> int | None:
    """Пинг за 1 час до собеса. ``chat_id`` — канал доставки (Telegram admin)."""
    if not stage.scheduled_at or not vacancy_id:
        return None

    fire_at = stage.scheduled_at - _REMINDER_LEAD
    now = datetime.now(tz=stage.scheduled_at.tzinfo or UTC)
    if fire_at <= now:
        logger.info("Prep reminder: собес уже близко (<1ч) или в прошлом — пропускаем")
        return None

    prep_stage = _STAGE_MAP.get(stage.stage_type, "screening")
    reminder: PrepReminder = await schedule_reminder(
        interview_id=interview_id,
        vacancy_id=vacancy_id,
        company=company,
        position=position,
        stage=prep_stage,
        interview_dt=stage.scheduled_at,
        fire_at=fire_at,
        chat_id=chat_id,
        account_id=account_id,
    )
    event(
        logger,
        "ЗАДАЧА",
        "prep-напоминание #%s на %s (за час до %s)",
        reminder.id,
        fire_at.isoformat(),
        stage.scheduled_at.isoformat(),
    )
    return reminder.id


async def schedule_prep_reminders_from_actions(
    analysis: object,
    actions: object,
    *,
    chat_id: int | None,
    account_id: int,
) -> None:
    """После ``apply_hr_actions`` — запланировать пинги (нужен chat_id канала)."""
    if chat_id is None:
        logger.warning("Prep reminder: chat_id не задан, пропускаем")
        return
    stages = getattr(actions, "prep_reminder_stages", None) or ()
    vacancy_id = getattr(analysis, "vacancy_id", "") or ""
    if not stages or not vacancy_id:
        return
    company = getattr(analysis, "company", "") or ""
    position = getattr(analysis, "position", "") or ""
    for stage in stages:
        try:
            await schedule_prep_reminder(
                interview_id=getattr(stage, "id", None),
                vacancy_id=vacancy_id,
                company=company,
                position=position,
                stage=stage,
                chat_id=chat_id,
                account_id=account_id,
            )
        except Exception as exc:  # noqa: BLE001 — напоминание best-effort
            logger.warning("schedule_prep_reminder failed: %s", exc)


__all__ = [
    "schedule_prep_reminder",
    "schedule_prep_reminders_from_actions",
]
