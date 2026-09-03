"""Конверсия воронки по источнику: hh / getmatch / habr / tg.

Группировка — те же метки, что в UI и веб (`resolve_job_source_group`).
Срез по источнику показываем только при n ≥ min_sample (по умолчанию 5): иначе шум.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel, Field

from core.domains.opportunities.jobs import (
    SOURCE_GROUP_GETMATCH,
    SOURCE_GROUP_HABR,
    SOURCE_GROUP_HH,
    SOURCE_GROUP_TELEGRAM,
    resolve_job_source_group,
)
from core.domains.pipeline.analytics import FunnelAnalytics, compute_funnel_analytics

MIN_SOURCE_SAMPLE = 5

SOURCE_GROUP_ORDER: tuple[str, ...] = (
    SOURCE_GROUP_HH,
    SOURCE_GROUP_GETMATCH,
    SOURCE_GROUP_HABR,
    SOURCE_GROUP_TELEGRAM,
)

SOURCE_GROUP_LABELS: dict[str, str] = {
    SOURCE_GROUP_HH: "HeadHunter",
    SOURCE_GROUP_GETMATCH: "getmatch",
    SOURCE_GROUP_HABR: "Хабр Карьера",
    SOURCE_GROUP_TELEGRAM: "Telegram",
}


class SourceFunnelSlice(BaseModel):
    """Конверсия воронки для одной UI-группы источника."""

    source: str  # hh | getmatch | tg
    label: str
    total: int = 0
    applied: int = 0
    responded: int = 0
    interviewing: int = 0
    offers: int = 0
    response_rate: float | None = None
    offer_rate: float | None = None


class SourceFunnelReport(BaseModel):
    """Сравнение конверсии по источникам для вкладки «Рынок».

    `available=true` — есть хотя бы одна группа с n ≥ min_sample. Иначе фронт прячет
    блок. Тонкие группы при available=true остаются в slices с rates=None.
    """

    available: bool = False
    min_sample: int = MIN_SOURCE_SAMPLE
    slices: list[SourceFunnelSlice] = Field(default_factory=list)
    note: str | None = None


def compute_source_funnel(
    jobs: list[tuple[int, str | None, str | None, str | None]],
    stages: list[tuple[int, str, datetime]],
    *,
    min_sample: int = MIN_SOURCE_SAMPLE,
) -> SourceFunnelReport:
    """Чистый расчёт по (job_id, status, source, vacancy_id) + история стадий.

    `available=true`, если хотя бы одна группа набрала min_sample. Группы с меньшей
    выборкой всё равно попадают в `slices` (счётчики есть, rates = None) — фронт
    рисует полосу без процентов и показывает note. Пустые группы не отдаём.
    """
    by_group: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    for job_id, status, source, vacancy_id in jobs:
        group = resolve_job_source_group(source, vacancy_id)
        by_group[group].append((job_id, status))

    slices: list[SourceFunnelSlice] = []
    enough_any = False
    for group in SOURCE_GROUP_ORDER:
        group_jobs = by_group.get(group, [])
        if not group_jobs:
            continue
        job_ids = {j[0] for j in group_jobs}
        group_stages = [s for s in stages if s[0] in job_ids]
        funnel: FunnelAnalytics = compute_funnel_analytics(group_jobs, group_stages)
        enough = len(group_jobs) >= min_sample
        if enough:
            enough_any = True
        slices.append(
            SourceFunnelSlice(
                source=group,
                label=SOURCE_GROUP_LABELS.get(group, group),
                total=len(group_jobs),
                applied=funnel.applied,
                responded=funnel.responded,
                interviewing=funnel.interviewing,
                offers=funnel.offers,
                # Мало выборки — проценты шумят, счётчики оставляем для полосы.
                response_rate=funnel.response_rate if enough else None,
                offer_rate=funnel.offer_rate if enough else None,
            )
        )

    if enough_any:
        return SourceFunnelReport(available=True, min_sample=min_sample, slices=slices)

    return SourceFunnelReport(
        available=False,
        min_sample=min_sample,
        # Срезы не отдаём — при available=false фронт прячет блок целиком.
        note=(
            f"Мало данных по источникам — нужно минимум {min_sample} вакансий в группе "
            "(HeadHunter / getmatch / Хабр Карьера / Telegram), чтобы сравнивать конверсию."
        ),
    )


__all__ = [
    "MIN_SOURCE_SAMPLE",
    "SourceFunnelReport",
    "SourceFunnelSlice",
    "compute_source_funnel",
]
