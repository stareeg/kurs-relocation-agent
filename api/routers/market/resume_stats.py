"""Приём и выдача статистики резюме: time-series отклика рынка.

Расширение на заходе на страницы резюме hh парсит счётчики/историю и шлёт сюда с
`X-API-Key` (auth навешан в `api/main.py`). Вкладка «Рынок» читает серию с посчитанной
динамикой.

PG — не жёсткая зависимость. Нет пула → приём отвечает `persisted=false` (не 500: расширение
шлёт авто на заходе, не должно спамить ошибками), серия → `available=false` и пусто.

M1 (plans/multitenancy_gaps_2026_08_06.md §3.1/§6): весь роутер — за `require_account_context`
— расширение шлёт `X-API-Key`/веб-токен аккаунта, `resume_stats`/`resume_views` больше не общий
счётчик на всю систему.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from api.schemas import (
    ResumeStatPoint,
    ResumeStatsIngest,
    ResumeStatsIngestResponse,
    ResumeStatsSeries,
    ResumeViewsIngest,
    ResumeViewsIngestResponse,
)
from api.security import AccountContext, require_account_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["resume-stats"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("/resume-stats", response_model=ResumeStatsIngestResponse)
async def ingest_resume_stats(
    body: ResumeStatsIngest, account: AccountContext = Depends(require_account_context)
) -> ResumeStatsIngestResponse:
    """Принять снимок агрегата резюме аккаунта запроса. Дневная идемпотентность — на стороне
    репозитория."""
    try:
        from core.domains.profile.resume_stats import ResumeStatSnapshot, save_resume_stat

        _, inserted = await save_resume_stat(
            ResumeStatSnapshot(**body.model_dump()), account_id=account.account_id
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → снимок не записан, не 500
        logger.debug("resume-stats: снимок не сохранён (нет PG?): %s", exc)
        return ResumeStatsIngestResponse(persisted=False, inserted=False)
    logger.info(
        "resume-stats снимок: показы=%s просмотры=%s приглашения=%s новый=%s",
        body.impressions,
        body.views,
        body.invitations,
        inserted,
    )
    return ResumeStatsIngestResponse(persisted=True, inserted=inserted)


@router.post("/resume-views", response_model=ResumeViewsIngestResponse)
async def ingest_resume_views(
    body: ResumeViewsIngest, account: AccountContext = Depends(require_account_context)
) -> ResumeViewsIngestResponse:
    """Принять строки истории просмотров аккаунта запроса. Дедуп по натуральному ключу — на
    стороне репозитория."""
    try:
        from core.domains.profile.resume_stats import ResumeView, save_resume_views

        rows = [
            ResumeView(
                viewed_at=r.viewed_at,
                employer=r.employer,
                vacancy_title=r.vacancy_title,
                vacancy_url=r.vacancy_url,
                resume_id=r.resume_id or body.resume_id,
                raw=r.raw,
            )
            for r in body.rows
        ]
        inserted = await save_resume_views(rows, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → строки не записаны, не 500
        logger.debug("resume-views: строки не сохранены (нет PG?): %s", exc)
        return ResumeViewsIngestResponse(persisted=False, inserted=0)
    logger.info("resume-views: получено=%s новых=%s", len(body.rows), inserted)
    return ResumeViewsIngestResponse(persisted=True, inserted=inserted)


@router.get("/resume-stats", response_model=ResumeStatsSeries)
async def get_resume_stats(
    from_days: int = 90,
    to_days: int = 0,
    account: AccountContext = Depends(require_account_context),
) -> ResumeStatsSeries:
    """Серия снимков аккаунта запроса за окно (по умолчанию 90 дней) + дельта
    первый↔последний. Нет PG → пусто.

    `from_days`/`to_days` — обе границы шкалы периода (план 2026-08-03), «дней назад от сегодня».
    """
    series = ResumeStatsSeries()
    try:
        from core.domains.profile.resume_stats import list_resume_stats

        clamped_from = max(1, min(from_days, 365))
        clamped_to = max(0, min(to_days, clamped_from - 1))
        since = _now() - timedelta(days=clamped_from)
        until = _now() - timedelta(days=clamped_to)
        records = await list_resume_stats(since=since, until=until, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → available=false, не 500
        logger.debug("resume-stats серия недоступна (нет PG?): %s", exc)
        return series

    series.available = True
    points = [
        ResumeStatPoint(
            captured_at=r.captured_at,
            resume_id=r.resume_id,
            impressions=r.impressions,
            views=r.views,
            invitations=r.invitations,
            recommended_vacancies=r.recommended_vacancies,
            views_delta=r.views_delta,
            invitations_delta=r.invitations_delta,
        )
        for r in records
        if r.captured_at is not None
    ]
    series.points = points
    if points:
        series.latest = points[-1]
    if len(points) >= 2:
        first, last = points[0], points[-1]
        series.impressions_change = last.impressions - first.impressions
        series.views_change = last.views - first.views
        series.invitations_change = last.invitations - first.invitations
    return series
