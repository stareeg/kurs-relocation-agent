"""Возраст вакансий в активных этапах воронки (план D-04): «Где стоит» на новом экране «Рынок».

По каждому активному этапу (скрининг/техничка/финал/оффер) — распределение по возрастным
корзинам (правка 2.2 плана) и общий топ самых залежавшихся вакансий. Возраст вакансии в этапе —
время с последнего перехода `application_stages`, не с момента отклика: ступень могла смениться
несколько раз. Порог «залежалось» — не константа, а медиана возраста этапа × 2 (кандидато-
независимая величина, правило «без хардкода владельца»).

`compute_stage_aging` — чистая функция над уже вытянутыми строками, тестируется без БД.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from statistics import median

from pydantic import BaseModel, Field

from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

# Тот же порядок и подписи активных этапов, что во второй строке воронки (overview.py).
ACTIVE_STAGES: tuple[tuple[FunnelStatus, str], ...] = (
    (FunnelStatus.SCREENING, "скрининг"),
    (FunnelStatus.TECH, "техничка"),
    (FunnelStatus.FINAL, "финал"),
    (FunnelStatus.OFFER, "оффер"),
)
_ACTIVE_STAGE_VALUES: frozenset[str] = frozenset(s.value for s, _ in ACTIVE_STAGES)

# Возрастные корзины (правка 2.2): одна полоса на этап, порядковая рампа светлее→темнее.
AGE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("до 7 дней", 0, 7),
    ("1–2 недели", 7, 14),
    ("2–3 недели", 14, 21),
    ("больше 3 недель", 21, None),
)

_STALLED_LIMIT = 5


class AgeBucketCount(BaseModel):
    label: str
    count: int = 0


class StageAgeRow(BaseModel):
    """Одна строка «Где стоит»: сколько вакансий в этапе и их разбивка по возрасту."""

    stage: str
    label: str
    total: int = 0
    buckets: list[AgeBucketCount] = Field(default_factory=list)


class StalledJob(BaseModel):
    """Одна строка списка «кто именно» залежался (пункт 2.2)."""

    job_id: int
    company: str = ""
    title: str = ""
    stage: str
    stage_label: str
    days: int
    score: int | None = None


class StageAging(BaseModel):
    """Ответ «Где стоит»: возраст в этапах + топ самых залежавшихся.

    `stalled` — top-5 для UI карточки; `stalled_count` — полное число (снапшот «Карьеры», Э9.2).
    """

    available: bool = False
    total_active: int = 0
    rows: list[StageAgeRow] = Field(default_factory=list)
    stalled: list[StalledJob] = Field(default_factory=list)
    stalled_count: int = 0


def _bucket_label(days: int) -> str:
    for label, lo, hi in AGE_BUCKETS:
        if days >= lo and (hi is None or days < hi):
            return label
    return AGE_BUCKETS[-1][0]


def compute_stage_aging(
    jobs: list[tuple[int, str | None, str | None, str | None, int | None]],
    stage_rows: list[tuple[int, str, datetime]],
    *,
    now: datetime | None = None,
) -> StageAging:
    """Чистый расчёт — тестируется без БД.

    `jobs` — (id, status, company, title, overall_score) уже отфильтрованных активных
    (не пропущенных) вакансий. `stage_rows` — вся история `application_stages` (job_id, stage,
    changed_at) для этих же вакансий. Возраст = время с последней строки истории по вакансии
    (последний переход, не обязательно совпадающий с текущим `status`, если история отстаёт).
    """
    now = now or datetime.now(UTC)

    last_change: dict[int, datetime] = {}
    for job_id, _stage, changed_at in stage_rows:
        if changed_at is None:
            continue
        if job_id not in last_change or changed_at > last_change[job_id]:
            last_change[job_id] = changed_at

    by_stage: dict[str, list[tuple[int, str, str, int | None, int]]] = {
        stage.value: [] for stage, _ in ACTIVE_STAGES
    }
    for job_id, status, company, title, score in jobs:
        resolved = resolve_funnel_status(status)
        if resolved not in _ACTIVE_STAGE_VALUES:
            continue
        entered_at = last_change.get(job_id)
        if entered_at is None:
            continue
        days = max(0, (now - entered_at).days)
        by_stage[resolved].append((job_id, company or "", title or "", score, days))

    rows: list[StageAgeRow] = []
    stalled: list[StalledJob] = []
    total_active = 0
    for stage, label in ACTIVE_STAGES:
        entries = by_stage[stage.value]
        total_active += len(entries)
        counts = {bucket_label: 0 for bucket_label, _, _ in AGE_BUCKETS}
        for *_rest, days in entries:
            counts[_bucket_label(days)] += 1
        rows.append(
            StageAgeRow(
                stage=stage.value,
                label=label,
                total=len(entries),
                buckets=[
                    AgeBucketCount(label=bucket_label, count=counts[bucket_label])
                    for bucket_label, _, _ in AGE_BUCKETS
                ],
            )
        )

        if not entries:
            continue
        threshold = median(days for *_rest, days in entries) * 2
        for job_id, company, title, score, days in entries:
            if days > 0 and days >= threshold:
                stalled.append(
                    StalledJob(
                        job_id=job_id,
                        company=company,
                        title=title,
                        stage=stage.value,
                        stage_label=label,
                        days=days,
                        score=score,
                    )
                )

    stalled.sort(key=lambda item: item.days, reverse=True)
    return StageAging(
        available=True,
        total_active=total_active,
        rows=rows,
        stalled=stalled[:_STALLED_LIMIT],
        stalled_count=len(stalled),
    )


async def get_stage_aging(*, account_id: int, db: Executor | None = None) -> StageAging:
    """Собрать «Где стоит» аккаунта из Postgres. Read-only, без LLM. Нет PG → `available=False`, не 500."""
    try:
        pool = db
        if pool is None:
            from core.platform.db.pool import get_pool

            pool = get_pool()
    except Exception as exc:  # noqa: BLE001 — нет PG → available=False, не 500
        logger.debug("stage-aging недоступен (нет PG?): %s", exc)
        return StageAging()

    try:
        job_rows = await pool.fetch(
            "select id, status, company, title, overall_score, "
            "exists(select 1 from skipped_vacancies sv where sv.vacancy_id = jobs.vacancy_id "
            "and sv.account_id = jobs.account_id) "
            "as is_skipped "
            "from jobs where account_id = $1",
            account_id,
        )
        active_ids = {int(r["id"]) for r in job_rows if not r["is_skipped"]}
        jobs = [
            (
                int(r["id"]),
                r["status"],
                r["company"],
                r["title"],
                r["overall_score"],
            )
            for r in job_rows
            if int(r["id"]) in active_ids
        ]
        stage_rows_raw = await pool.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        )
        stage_rows = [
            (int(r["job_id"]), str(r["stage"]), r["changed_at"])
            for r in stage_rows_raw
            if int(r["job_id"]) in active_ids
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("stage-aging: строки недоступны: %s", exc)
        return StageAging()

    return compute_stage_aging(jobs, stage_rows)


__all__ = [
    "ACTIVE_STAGES",
    "AGE_BUCKETS",
    "AgeBucketCount",
    "StageAgeRow",
    "StageAging",
    "StalledJob",
    "compute_stage_aging",
    "get_stage_aging",
]
