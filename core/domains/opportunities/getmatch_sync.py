"""S3: свежесть синка getmatch /applications → Postgres.

Расширение синкает отклики getmatch только при ручном открытии страницы `/applications`
(нет фонового heartbeat — read-only на внешнем сайте). Если владелец не заходил неделю,
статусы в `jobs`/`application_stages` устаревают, а KPI воронки getmatch и
`source_funnel` врут. Эта таблица — одна строка (`id=1` фикс), `last_sync_at` обновляется
при каждом синке с `gm_*`-айтемами. Pulse читает её и уведомляет владельца.

Похожий приём используется в `legend` (0033) и `market_snapshots` (0024): single-row upsert,
не накапливаем историю — текущее состояние важнее.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)


async def mark_getmatch_sync(*, db: Executor | None = None) -> None:
    """Зафиксировать «только что был успешный синк getmatch /applications».

    Вызывается из `core.domains.pipeline.negotiations` после применения пакета с `gm_*`-айди. Best-effort:
    нет PG / нет таблицы → debug-лог, не роняет синк (источник истины — `application_stages`).
    """
    db = db or get_pool()
    try:
        await db.execute("update getmatch_sync_freshness set last_sync_at = now() where id = 1")
    except Exception as exc:  # noqa: BLE001 — таблицы нет/PG недоступен → не падаем
        logger.debug("getmatch_sync_freshness: не обновлено: %s", exc)


async def get_getmatch_last_sync_at(*, db: Executor | None = None) -> datetime | None:
    """Время последнего успешного синка getmatch или None, если синков ещё не было.

    Нет PG / нет таблицы → None (pulse покажет нейтральное «ещё не синкалось»).
    """
    db = db or get_pool()
    try:
        row = await db.fetchrow("select last_sync_at from getmatch_sync_freshness where id = 1")
    except Exception as exc:  # noqa: BLE001 — нет PG → None, не роняем pulse
        logger.debug("getmatch_sync_freshness: чтение недоступно: %s", exc)
        return None
    if row is None:
        return None
    ts = row["last_sync_at"]
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


__all__ = ["mark_getmatch_sync", "get_getmatch_last_sync_at"]
