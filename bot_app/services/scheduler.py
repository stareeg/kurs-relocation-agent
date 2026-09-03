"""Расписание бота через единую очередь `platform.tasks`.

Cron-тикер кладёт задачи в Postgres-очередь (идемпотентный ключ на дату); перезапуск
процесса не теряет уже поставленную задачу. Обработчики регистрируются здесь — большинству
нужен `Bot`, но не всем (`interview_stages_sweep` — чистый SQL, живёт в очереди из удобства,
делит cron-слот 9:00).

Все рассылки (дайджест, discovery, attention_reminders) product-но выключены — доставка
каждому пользователю вручную через фронтенд. Остались ежедневная уборка `tg_cleanup`
4:30, авто-завершение просроченных этапов собеседований `interview_stages_sweep` 9:00
(plans/local_context_blind_spots_2026_08_12.md §8) и on-demand `tg_push` из веба —
без cron, только register_handler.

Если рассылки когда-нибудь вернутся — доставку активным аккаунтам заводить через
`bot_app.services.notify.broadcast_to_active_accounts`
(plans/multitenancy_gaps_2026_08_06.md §5.5), не веткой в каждом сервисе.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from aiogram import Bot

from bot_app.services.push_handler import register_tg_push
from bot_app.storage.message_registry import due_cleanup
from core.platform.observability import event
from core.platform.tasks import CronSpec, add_cron, register_handler

logger = logging.getLogger(__name__)

KIND_TG_CLEANUP = "tg_cleanup"
KIND_INTERVIEW_STAGES_SWEEP = "interview_stages_sweep"

_DAILY_MISFIRE_GRACE_SEC = 3600


async def _run_tg_cleanup(_payload: Mapping[str, Any]) -> None:
    """Ежедневная уборка: due_cleanup → delete_message + expire hr_pending.

    Строки уже вынуты из реестра; сбой Telegram (>48ч / нет прав) только логируем.
    """
    from bot_app.storage import hr_pending

    expired_pending = await hr_pending.expire_due()
    if expired_pending:
        logger.info("tg_cleanup: hr_pending expired=%s", expired_pending)

    bot: Bot | None = _BOT
    if bot is None:
        return
    items = await due_cleanup()
    if not items:
        logger.info("tg_cleanup: нечего удалять")
        return
    deleted = 0
    for item in items:
        try:
            await bot.delete_message(item.chat_id, item.message_id)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 — >48ч / уже удалено / нет прав
            logger.debug(
                "tg_cleanup delete_message failed chat=%s msg=%s: %s",
                item.chat_id,
                item.message_id,
                exc,
            )
    event(
        logger,
        "ЗАДАЧА",
        "tg_cleanup: из реестра %s, удалено в TG %s",
        len(items),
        deleted,
    )


async def _run_interview_stages_sweep(_payload: Mapping[str, Any]) -> None:
    """Просроченные `scheduled`-этапы → `completed`, кросс-аккаунтно, без LLM (§8 плана).

    Ничего не решает — дата уже прошла, чистый UPDATE (`interview_stages.complete_past_stages`).
    Не зависит от `Bot`: делит cron-слот с `tg_cleanup` (9:00), но сам ничего не шлёт.
    """
    from core.domains.preparation.interview_stages import complete_past_stages

    completed_n = await complete_past_stages()
    event(
        logger,
        "ЗАДАЧА",
        "interview_stages_sweep: завершено просроченных этапов %s",
        completed_n,
    )


_BOT: Bot | None = None


def register_bot_schedules(bot: Bot) -> None:
    """Зарегистрировать handlers + ежедневный cron уборки в общей очереди."""
    global _BOT
    _BOT = bot
    register_handler(KIND_TG_CLEANUP, _run_tg_cleanup)
    register_handler(KIND_INTERVIEW_STAGES_SWEEP, _run_interview_stages_sweep)
    register_tg_push(bot)
    add_cron(
        CronSpec(
            schedule_id=KIND_TG_CLEANUP,
            hour=4,
            minute=30,
            kind=KIND_TG_CLEANUP,
            priority=110,
            misfire_grace_sec=_DAILY_MISFIRE_GRACE_SEC,
        )
    )
    add_cron(
        CronSpec(
            schedule_id=KIND_INTERVIEW_STAGES_SWEEP,
            hour=9,
            minute=0,
            kind=KIND_INTERVIEW_STAGES_SWEEP,
            priority=110,
            misfire_grace_sec=_DAILY_MISFIRE_GRACE_SEC,
        )
    )
    event(
        logger,
        "ЗАПУСК",
        "шедулер очереди: tg_cleanup 4:30, interview_stages_sweep 9:00, tg_push on-demand",
    )


__all__ = [
    "KIND_TG_CLEANUP",
    "KIND_INTERVIEW_STAGES_SWEEP",
    "register_bot_schedules",
]
