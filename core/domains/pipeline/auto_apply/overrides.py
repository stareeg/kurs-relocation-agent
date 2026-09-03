"""Ручной оверрайд бакета очереди автооткликов (auto/manual_review) — Фаза E редизайна
«Расширения» (пункт 4, plans/... квик-экшен «переместить»).

`classify_for_auto_apply` (gate.py) — чистая функция, бакет выводится из score vs порогов на
каждый запрос (`queue.py::preview_queue`, «живой пересчёт без персиста»). Ручной выбор владельца
живёт отдельно, по образцу skipped_vacancies — отдельная таблица
(`0131_auto_apply_queue_override.sql`), не колонка в `jobs`.

`reason` (миграция 0153) — опциональное пояснение, почему система сама переложила вакансию
в «Ручной разбор» после неудачного автоотклика; ручной квик-экшен оставляет `reason=null`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.platform.db.pool import Executor, get_pool

QueueOverride = Literal["auto", "manual_review"]


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    """Оверрайд бакета + опциональная причина (для UI «Ручной разбор»)."""

    override: QueueOverride
    reason: str | None = None


async def get_overrides(
    job_ids: list[int], *, account_id: int, db: Executor | None = None
) -> dict[int, OverrideRecord]:
    """Оверрайды для набора job_id разом — вызывающая сторона (preview_queue) уже держит список
    кандидатов, не нужен отдельный запрос на вакансию."""
    if not job_ids:
        return {}
    executor = db or get_pool()
    rows = await executor.fetch(
        "select job_id, override, reason from auto_apply_queue_overrides "
        "where account_id = $1 and job_id = any($2::bigint[])",
        account_id,
        job_ids,
    )
    return {
        int(row["job_id"]): OverrideRecord(
            override=row["override"],
            reason=row["reason"],
        )
        for row in rows
    }


async def set_override(
    job_id: int,
    override: QueueOverride,
    *,
    account_id: int,
    reason: str | None = None,
    db: Executor | None = None,
) -> None:
    """Владелец перемещает вакансию между «Сам откликнется»/«На ручной разбор» — держится, пока
    её не пересоздадут заново (следующий вызов) или вакансия не выпадет из воронки (job удалён —
    ON DELETE CASCADE).

    `reason` пишется только при системном переносе после сбоя автоотклика; ручной клик в UI
    передаёт `None` и затирает прошлую причину (владелец сам решил бакет заново).
    """
    executor = db or get_pool()
    await executor.execute(
        "insert into auto_apply_queue_overrides (job_id, account_id, override, reason) "
        "values ($1, $2, $3, $4) "
        "on conflict (job_id) do update set "
        "override = excluded.override, reason = excluded.reason, created_at = now()",
        job_id,
        account_id,
        override,
        reason,
    )


__all__ = ["OverrideRecord", "QueueOverride", "get_overrides", "set_override"]
