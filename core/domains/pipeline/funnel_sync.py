"""Инструмент `funnel_sync` (задача 2.2, подшаг 3): синхронизация стадии воронки.

Обёртка над таксономией воронки из `core.kernel.schemas.funnel` (перенесена в core в S8). Мастер
стадий — новая модель: `application_stages` в Postgres.

Логика: HH-статус → канонический FunnelStatus → сравнить с текущей стадией вакансии →
если изменилось, записать новую стадию (`add_stage`). Расхождение (регресс стадии или
терминальный отказ/архив) отдаётся как `replanning_event` — вход для planner-узла (2.3,
В5.6): рассинхрон статусов → событие репланинга.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from core.domains.opportunities.jobs import add_stage, get_job_by_vacancy_id, list_stages
from core.kernel.schemas.funnel import FunnelStatus, funnel_status_rank, resolve_funnel_status
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)


class FunnelSyncResult(BaseModel):
    vacancy_id: str
    job_id: int | None = None
    previous_stage: str | None = None
    new_stage: str
    changed: bool = False
    discrepancy: bool = False
    # Событие репланинга для planner-узла (2.3); None, если расхождения нет.
    replanning_event: dict | None = None


def _is_discrepancy(prev: str | None, new: str) -> bool:
    """Расхождение, требующее репланинга: регресс стадии или терминальный отказ/архив.

    Прямое продвижение (Просмотр → Отклик → Скрининг…) — ожидаемо, не расхождение.
    """
    new_canon = resolve_funnel_status(new) or new
    if new_canon in (FunnelStatus.REJECTED, FunnelStatus.ARCHIVE):
        return True
    if not prev:
        return False
    return funnel_status_rank(new_canon) < funnel_status_rank(prev)


async def funnel_sync(
    vacancy_id: str,
    hh_status_raw: str,
    *,
    source: str = "funnel_sync",
    account_id: int,
    db: Executor | None = None,
) -> FunnelSyncResult:
    """Свести HH-статус вакансии в стадию воронки новой модели.

    Возвращает результат с флагом `discrepancy` и (при расхождении) `replanning_event`.
    Если вакансии нет в `jobs` — пишем результат без записи стадии (нечего обновлять).
    """
    db = db or get_pool()

    new_stage = resolve_funnel_status(hh_status_raw) or hh_status_raw.strip()
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    if job is None or job.id is None:
        logger.info("funnel_sync: вакансия %s не в jobs — стадию не пишу", vacancy_id)
        return FunnelSyncResult(vacancy_id=vacancy_id, new_stage=new_stage)

    stages = await list_stages(job.id, account_id=account_id, db=db)
    prev = stages[-1].stage if stages else job.status
    prev_canon = (resolve_funnel_status(prev) or prev) if prev else None
    changed = prev_canon != new_stage
    discrepancy = changed and _is_discrepancy(prev, new_stage)

    if changed:
        await add_stage(job.id, new_stage, source=source, account_id=account_id, db=db)

    replanning_event = None
    if discrepancy:
        replanning_event = {
            "type": "funnel_discrepancy",
            "vacancy_id": vacancy_id,
            "from": prev_canon,
            "to": new_stage,
        }

    if changed:
        event(
            logger,
            "ЗАДАЧА",
            "funnel_sync: %s %s → %s%s",
            vacancy_id,
            prev_canon or "-",
            new_stage,
            " (расхождение)" if discrepancy else "",
            vacancy_id=vacancy_id,
            previous_stage=prev_canon,
            new_stage=new_stage,
            discrepancy=discrepancy,
            level=logging.WARNING if discrepancy else logging.INFO,
        )

    return FunnelSyncResult(
        vacancy_id=vacancy_id,
        job_id=job.id,
        previous_stage=prev_canon,
        new_stage=new_stage,
        changed=changed,
        discrepancy=discrepancy,
        replanning_event=replanning_event,
    )
