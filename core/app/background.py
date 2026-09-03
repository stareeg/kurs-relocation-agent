"""Регистрация обработчиков очереди и жизненный цикл воркера.

Связывает `platform.tasks` с доменными сценариями. Зовётся из lifespan API;
бот добавляет свои handlers/cron отдельно (`bot_app.services.scheduler`).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core.config import reset_current_account_id, set_current_account_id
from core.platform.db.pool import TimingPool
from core.platform.observability import event
from core.platform.tasks import (
    PgTaskStore,
    get_runtime,
    register_handler,
)
from core.platform.tasks.store import MemoryTaskStore

logger = logging.getLogger(__name__)


async def _enter_task_account_context(account_id: int) -> Any:
    """Хук воркера очереди (plans/multitenancy_gaps_2026_08_06.md §3.10): для account-задачи
    выставить тот же per-request ContextVar, что HTTP/бот-middleware выставляют на запрос/апдейт
    (`api.main`/`bot_app.run`) — иначе LLM-вызов из handler'а (attachment_read, salary_estimate)
    уходит по ключу владельца/последнего сохранившего, а не по ключу владельца ЭТОЙ задачи.
    """
    from core.platform.repo.settings import prime_runtime_openrouter_key_for_account

    try:
        await prime_runtime_openrouter_key_for_account(account_id)
    except Exception as exc:  # noqa: BLE001 — недоступный PG не должен ронять задачу
        logger.debug("background: prime openrouter key не удался: %s", exc)
    return set_current_account_id(account_id)


async def _exit_task_account_context(token: Any) -> None:
    reset_current_account_id(token)


async def _handle_salary_estimate(payload: Mapping[str, Any]) -> None:
    from core.domains.opportunities.salary_async import run_salary_estimate_from_payload

    await run_salary_estimate_from_payload(dict(payload))


async def _handle_attachment_read(payload: Mapping[str, Any]) -> None:
    from core.domains.assistant.attachments.tasks import run_attachment_read_from_payload

    await run_attachment_read_from_payload(dict(payload))


async def _handle_skip_reasons(payload: Mapping[str, Any]) -> None:
    from core.domains.opportunities.skip_reasons_async import run_skip_reasons_from_payload

    await run_skip_reasons_from_payload(dict(payload))


async def _handle_rescore_weights(payload: Mapping[str, Any]) -> None:
    from core.domains.opportunities.rescore import run_rescore_from_payload

    await run_rescore_from_payload(dict(payload))


async def _handle_cover_letter_pregen(payload: Mapping[str, Any]) -> None:
    from core.app.scenarios.cover_letter import run_cover_letter_pregen_from_payload

    await run_cover_letter_pregen_from_payload(dict(payload))


def register_core_handlers() -> None:
    """Обработчики, доступные и без Telegram (API-процесс)."""
    from core.app.scenarios.cover_letter import COVER_LETTER_PREGEN_KIND
    from core.domains.assistant.attachments.tasks import ATTACHMENT_READ_KIND
    from core.domains.opportunities.rescore import RESCORE_WEIGHTS_KIND
    from core.domains.opportunities.salary_async import SALARY_ESTIMATE_KIND
    from core.domains.opportunities.skip_reasons_async import SKIP_REASONS_KIND

    register_handler(SALARY_ESTIMATE_KIND, _handle_salary_estimate)
    register_handler(ATTACHMENT_READ_KIND, _handle_attachment_read)
    register_handler(SKIP_REASONS_KIND, _handle_skip_reasons)
    register_handler(RESCORE_WEIGHTS_KIND, _handle_rescore_weights)
    register_handler(COVER_LETTER_PREGEN_KIND, _handle_cover_letter_pregen)


async def start_background_runtime(pool: TimingPool | None) -> None:
    """Подключить store (PG или память), зарегистрировать handlers, поднять воркер."""
    runtime = get_runtime()
    runtime.set_account_context(_enter_task_account_context, _exit_task_account_context)
    if pool is not None:
        runtime.set_store(PgTaskStore(pool))
    else:
        runtime.set_store(MemoryTaskStore())
        event(
            logger,
            "ЗАДАЧА",
            "очередь в памяти: Postgres недоступен, задачи не переживают рестарт",
            level=logging.WARNING,
        )
    register_core_handlers()

    from core.domains.assistant.attachments.gc import register_attachments_gc_schedule
    from core.domains.market.snapshot_refresh import register_market_schedules
    from core.domains.multiplayer.gc import register_multiplayer_idle_gc_schedule
    from core.domains.opportunities.coverage_metrics import register_coverage_metrics_schedule
    from core.domains.opportunities.empty_stub_purge import register_empty_stub_purge_schedule

    await register_market_schedules()
    await register_empty_stub_purge_schedule()
    await register_attachments_gc_schedule()
    await register_coverage_metrics_schedule()
    await register_multiplayer_idle_gc_schedule()
    await runtime.start()


async def stop_background_runtime() -> None:
    runtime = get_runtime()
    if runtime.running:
        await runtime.stop()


__all__ = [
    "register_core_handlers",
    "start_background_runtime",
    "stop_background_runtime",
]
