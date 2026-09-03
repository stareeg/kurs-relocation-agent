"""Плановое обновление снапшотов «Рынка»: фон считает, роутер отдаёт мгновенно.

Сетка/пульс (Postgres-агрегаты, без LLM) пересчитываются каждые `MARKET_SNAPSHOT_INTERVAL_SEC`
самопланирующейся фоновой задачей: обработчик после каждого прогона сам кладёт свой
следующий запуск в очередь — `CronSpec` даёт только суточную гранулярность, для более частого
интервала это проще, чем менять планировщик. Идемпотентность — по ключу с бакетом времени
(`{kind}:{bucket}`), тот же приём, что `CronSpec` использует для дат: рестарт процесса внутри
уже забронированного интервала не плодит параллельные цепочки.

L-26: пересчитывается не оба среза на каждый тик, а только те, что реально грязные
(`snapshot_dirty.kinds_to_recompute`) — обычно за 5 минут между тиками ничего не меняется (личный
инструмент, а не сервис с потоком трафика). Чистые срезы получают дешёвый `touch_snapshot`
(продлить `computed_at`), чтобы фронт не показывал «протухший» бейдж по срезу, который на самом
деле не устарел, а просто не пересчитывался за ненадобностью.

LLM-сводка «Ситуация» дороже (реальный OpenRouter-вызов) — обновляется раз в сутки обычным
`CronSpec`, как дайджест/прогрев бота.

M5 (plans/multitenancy_gaps_2026_08_06.md §1): оба фона — системный путь без HTTP/бот-
контекста (план §1 явно называет «маркет-агрегацию» примером системного пути наравне с GC
вложений) — резолвят account_id владельца сами (`resolve_default_account_id`).
Precompute сегодня остаётся per-owner: друг,
у которого свой кэш ещё не бутстрапнут фоном, получает живой расчёт на своей `account_id`
(роутер фолбэкает на live — см. `api/routers/market/analytics.py`), просто без прогретого кэша.
Полный цикл по всем активным аккаунтам — тот же приём, что M8 заводит для дайджеста бота
(`bot_app/services/scheduler.py`), сюда не входит.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from core.platform.observability import event
from core.platform.tasks import CronSpec, add_cron, enqueue, get_runtime, register_handler

logger = logging.getLogger(__name__)

MARKET_SNAPSHOT_KIND = "market_snapshot_refresh"
MARKET_SNAPSHOT_INTERVAL_SEC = 5 * 60
# Запас в 3 цикла обновления: один пропущенный тик (временная нагрузка/рестарт воркера) не должен
# сразу помечать снапшот как устаревший — только если фон реально отстал.
MARKET_SNAPSHOT_STALE_AFTER_SEC = 3 * MARKET_SNAPSHOT_INTERVAL_SEC

SITUATION_REFRESH_KIND = "situation_refresh"
SITUATION_REFRESH_SCHEDULE_ID = "situation_refresh"
_SITUATION_REFRESH_HOUR = 6
_SITUATION_REFRESH_MINUTE = 30
_DAILY_MISFIRE_GRACE_SEC = 3600
# Раз в сутки + запас на misfire/пропущенный день, прежде чем показывать «обновляется».
SITUATION_STALE_AFTER_SEC = 36 * 3600


def _is_stale(computed_at: datetime | None, *, after_sec: float) -> bool:
    if computed_at is None:
        return True
    at = computed_at if computed_at.tzinfo else computed_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - at).total_seconds() > after_sec


def is_market_snapshot_stale(computed_at: datetime | None) -> bool:
    return _is_stale(computed_at, after_sec=MARKET_SNAPSHOT_STALE_AFTER_SEC)


def is_situation_stale(computed_at: datetime | None) -> bool:
    return _is_stale(computed_at, after_sec=SITUATION_STALE_AFTER_SEC)


def _bucket_key(kind: str, *, at: datetime, interval_sec: int) -> str:
    """`{kind}:{номер интервала}` — стабилен в пределах одного окна, меняется в следующем."""
    epoch = int(at.timestamp())
    bucket = epoch - (epoch % interval_sec)
    return f"{kind}:{bucket}"


async def _refresh_market_snapshots(_payload: Mapping[str, Any]) -> None:
    """Пересчитать грязные срезы, продлить чистые, сохранить; перепланировать свой запуск."""
    try:
        from core.domains.market import snapshot_dirty as dirty
        from core.domains.market.analytics_cache import save_snapshot, touch_snapshot
        from core.domains.market.market_grid import get_market_grid
        from core.domains.market.market_snapshot import record_daily_pulse_state
        from core.domains.market.pulse import get_market_pulse
        from core.domains.market.search_metrics import get_search_metrics
        from core.platform.repo.accounts import resolve_default_account_id

        account_id = await resolve_default_account_id()
        if account_id is None:
            event(logger, "ЗАДАЧА", "снапшоты «Рынка»: пропуск — нет аккаунта-владельца")
            return

        to_compute = dirty.kinds_to_recompute(safety_net_sec=MARKET_SNAPSHOT_STALE_AFTER_SEC)
        clean = [k for k in dirty.ALL_KINDS if k not in to_compute]

        if not to_compute:
            await asyncio.gather(
                *(touch_snapshot(k, account_id=account_id) for k in dirty.ALL_KINDS)
            )
            event(logger, "ЗАДАЧА", "снапшоты «Рынка»: вход не менялся, пересчёт пропущен")
        else:
            kind_coros: list[tuple[str, Any]] = []
            if dirty.GRID in to_compute:
                kind_coros.append((dirty.GRID, get_market_grid(account_id=account_id)))
            if dirty.PULSE in to_compute:
                kind_coros.append((dirty.PULSE, get_market_pulse(account_id=account_id)))
            if dirty.SEARCH in to_compute:
                kind_coros.append((dirty.SEARCH, get_search_metrics(account_id=account_id)))

            values = await asyncio.gather(*(coro for _, coro in kind_coros))
            results = dict(zip((k for k, _ in kind_coros), values, strict=True))

            await asyncio.gather(
                *(
                    save_snapshot(k, v.model_dump(mode="json"), account_id=account_id)
                    for k, v in results.items()
                ),
                *(touch_snapshot(k, account_id=account_id) for k in clean),
            )
            if dirty.PULSE in results:
                pulse_now = results[dirty.PULSE]
                # Расширенный снимок (воронка/гейты/деньги/форматы) для линейных графиков во
                # времени — собираем overview и дописываем в тот же дневной снимок. Лучший
                # вариант пересчёта полного overview уже здесь (5-минутный интервал это
                # позволяет), live-фолбэк /pulse пишет только базовый снимок (без overview).
                overview = None
                try:
                    from core.domains.market.overview import get_market_overview

                    overview = await get_market_overview(account_id=account_id)
                except Exception as exc:  # noqa: BLE001 — overview best-effort, снимок не падает
                    event(logger, "ЗАДАЧА", "overview для снимка не собран: %s", exc)
                await record_daily_pulse_state(pulse_now, account_id=account_id, overview=overview)
            dirty.mark_computed(*to_compute)
            event(
                logger,
                "ЗАДАЧА",
                "снапшоты «Рынка» обновлены: %s (без изменений: %s)",
                ",".join(sorted(to_compute)),
                ",".join(sorted(clean)) or "—",
            )
    finally:
        # В finally — чтобы сбой одного прогона не остановил всю цепочку планирования.
        next_run = datetime.now(UTC) + timedelta(seconds=MARKET_SNAPSHOT_INTERVAL_SEC)
        await enqueue(
            MARKET_SNAPSHOT_KIND,
            run_at=next_run,
            idempotency_key=_bucket_key(
                MARKET_SNAPSHOT_KIND, at=next_run, interval_sec=MARKET_SNAPSHOT_INTERVAL_SEC
            ),
            priority=150,
        )


async def _refresh_situation(_payload: Mapping[str, Any]) -> None:
    """Раз в сутки: свежая LLM-сводка «Ситуация» вместо ручной кнопки (владелец согласился на
    регулярный платный вызов OpenRouter ради мгновенного открытия «Рынка»)."""
    from core.domains.market.situation import (
        SCHEMA_VERSION,
        generate_situation_narrative,
        narrative_to_storage,
    )
    from core.domains.market.situation_store import save_situation
    from core.platform.repo.accounts import resolve_default_account_id

    account_id = await resolve_default_account_id()
    if account_id is None:
        logger.info("situation_refresh: пропуск — нет аккаунта-владельца")
        return

    try:
        narrative = await generate_situation_narrative(account_id=account_id)
    except ValueError as exc:
        # Недостаточно данных (ещё ничего не заскорено) — не ошибка, тихий пропуск.
        logger.info("situation_refresh: пропуск (%s)", exc)
        return
    await save_situation(
        narrative.conclusion,
        narrative_to_storage(narrative),
        account_id=account_id,
        schema_version=SCHEMA_VERSION,
    )
    event(logger, "ЗАДАЧА", "сводка «Ситуация» обновлена по расписанию")


async def register_market_schedules() -> None:
    """Зарегистрировать handlers + завести цепочку grid/pulse/search и суточный cron ситуации.

    Вызывается из `core.app.background.start_background_runtime` — доступно и без Telegram.
    """
    register_handler(MARKET_SNAPSHOT_KIND, _refresh_market_snapshots)
    register_handler(SITUATION_REFRESH_KIND, _refresh_situation)
    add_cron(
        CronSpec(
            schedule_id=SITUATION_REFRESH_SCHEDULE_ID,
            hour=_SITUATION_REFRESH_HOUR,
            minute=_SITUATION_REFRESH_MINUTE,
            kind=SITUATION_REFRESH_KIND,
            priority=120,
            misfire_grace_sec=_DAILY_MISFIRE_GRACE_SEC,
        )
    )
    # Цепочка сама себя перепланирует бесконечно (см. `_refresh_market_snapshots`) — если она уже
    # где-то в очереди (предыдущий процесс, dev `--reload`), новый кик не нужен: иначе на каждый
    # рестарт заводился бы ещё один параллельный вечный цикл пересчёта.
    if not await get_runtime().store.has_pending_of_kind(MARKET_SNAPSHOT_KIND):
        now = datetime.now(UTC)
        await enqueue(
            MARKET_SNAPSHOT_KIND,
            run_at=now,
            idempotency_key=_bucket_key(
                MARKET_SNAPSHOT_KIND, at=now, interval_sec=MARKET_SNAPSHOT_INTERVAL_SEC
            ),
            priority=150,
        )
    event(
        logger,
        "ЗАПУСК",
        "шедулер «Рынка»: grid/pulse/search каждые %sс, ситуация в %02d:%02d",
        MARKET_SNAPSHOT_INTERVAL_SEC,
        _SITUATION_REFRESH_HOUR,
        _SITUATION_REFRESH_MINUTE,
    )


__all__ = [
    "MARKET_SNAPSHOT_INTERVAL_SEC",
    "MARKET_SNAPSHOT_KIND",
    "MARKET_SNAPSHOT_STALE_AFTER_SEC",
    "SITUATION_REFRESH_KIND",
    "SITUATION_REFRESH_SCHEDULE_ID",
    "SITUATION_STALE_AFTER_SEC",
    "is_market_snapshot_stale",
    "is_situation_stale",
    "register_market_schedules",
]
