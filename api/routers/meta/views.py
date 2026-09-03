"""Read-эндпоинты для фронта: kanban, метрики, сессия.

Все витрины деградируют мягко: нет PG → пустой ответ/нули, а не 500 (локальная разработка
без compose). Мутации доски — наоборот, честные ошибки; их сценарии живут в
`core.domains.opportunities.service`, роутер только раскладывает результат.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.errors import to_http
from api.schemas import (
    CostByDay,
    Job,
    JobApplyFieldsResponse,
    JobApplyFieldsUpdate,
    JobDeleteResponse,
    JobSkipResponse,
    JobSkipUpdate,
    JobsPage,
    JobStageResponse,
    JobStageUpdate,
    JobTrackResponse,
    JobTrackUpdate,
    MetricsResponse,
    SessionResponse,
    TierTokenTotals,
    TokenStats,
    UsageByAgent,
    VacancyActivityHistory,
)
from api.security import AccountContext, require_account_context
from core.app.channels import WEB, set_stage_via, skip_via, unskip_via
from core.domains.opportunities.jobs import (
    BOARD_COLUMNS,
    count_active_jobs,
    count_jobs_by_column,
    get_job_by_vacancy_id,
    list_job_links,
    list_jobs_page,
)
from core.domains.opportunities.jobs import Job as DomainJob
from core.domains.opportunities.service import delete_job_card, set_job_track, update_job_card
from core.kernel.errors import DomainError, NotFound
from core.platform.repo.usage import load_usage_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["views"])


async def _attach_job_links(jobs: list[DomainJob], *, account_id: int) -> None:
    """Дозаполнить `job.links` из `job_links` одним запросом (best-effort: нет PG → пусто)."""
    job_ids = [j.id for j in jobs if j.id is not None]
    if not job_ids:
        return
    try:
        links_by_job = await list_job_links(job_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — ссылки не критичны для доски
        logger.debug("job_links недоступны (нет PG?): %s", exc)
        return
    for job in jobs:
        if job.id is not None:
            job.links = links_by_job.get(job.id, [])


@router.get("/jobs", response_model=JobsPage)
async def get_jobs(
    min_score: int | None = None,
    status: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
    account: AccountContext = Depends(require_account_context),
) -> JobsPage:
    """Страница вакансий для kanban (курсорная пагинация вместо одного `limit`).

    Активные этапы воронки первыми, затем score/дата — как раньше. `column_counts` — точные
    тоталы по колонкам доски, считаются только на первой странице (`cursor` не передан), фронт
    держит их между догрузками. Нет PG → пустая страница, не 500.
    """
    try:
        page = await list_jobs_page(
            min_score=min_score,
            status=status,
            cursor=cursor,
            limit=min(limit, 500),
            account_id=account.account_id,
        )
        if cursor is None:
            page.column_counts = await count_jobs_by_column(account_id=account.account_id)
        await _attach_job_links(page.jobs, account_id=account.account_id)
        # B-03: транспортная JobsPage типизирует score как ScoreResult (не голый dict) — конверсия
        # через from_attributes, невалидный score мягко уходит в null (см. api.schemas.jobs.Job).
        return JobsPage.model_validate(page, from_attributes=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("jobs не загружены (нет PG?): %s", exc)
        return JobsPage(jobs=[], next_cursor=None, column_counts={})


@router.get("/jobs/by-vacancy/{vacancy_id}", response_model=Job)
async def get_job_by_vacancy(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> Job:
    """Точечный поиск вакансии по vacancy_id: фолбэк для deep-link (расширение, старая
    ссылка), когда вакансия за пределами уже догруженных курсором страниц доски.
    """
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
    if job is None:
        raise to_http(NotFound(f"Вакансия {vacancy_id} не найдена"))
    await _attach_job_links([job], account_id=account.account_id)
    return Job.model_validate(job, from_attributes=True)


@router.get("/jobs/by-vacancy/{vacancy_id}/events", response_model=VacancyActivityHistory)
async def get_vacancy_events(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> VacancyActivityHistory:
    """Лента действий по вакансии: воронка, скор, пропуск, этапы, оффер. Нет PG → пусто."""
    from core.app.scenarios.vacancy_activity import load_vacancy_activity

    try:
        items = await load_vacancy_activity(vacancy_id, account_id=account.account_id)
        return VacancyActivityHistory.from_items(vacancy_id, items)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая лента
        logger.debug("vacancy-events недоступны (нет PG?): %s", exc)
        return VacancyActivityHistory(vacancy_id=vacancy_id, items=[])


@router.get("/jobs/active-count")
async def get_jobs_active_count(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Число активных процессов (engaged + HR-диалог), без лимита выборки."""
    try:
        return {"count": await count_active_jobs(account_id=account.account_id)}
    except Exception as exc:  # noqa: BLE001
        logger.debug("jobs active-count недоступен (нет PG?): %s", exc)
        return {"count": 0}


@router.get("/jobs/stage-counts")
async def get_jobs_stage_counts(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Тоталы по колонкам kanban — для бейджей вне доски (например, шелл), без
    вытягивания страницы вакансий целиком, как делал `column_counts` внутри `/api/jobs`.
    """
    try:
        return await count_jobs_by_column(account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("jobs stage-counts недоступен (нет PG?): %s", exc)
        return dict.fromkeys(BOARD_COLUMNS, 0)


@router.patch("/jobs/{job_id}/stage", response_model=JobStageResponse)
async def update_job_stage(
    job_id: int,
    body: JobStageUpdate,
    account: AccountContext = Depends(require_account_context),
) -> JobStageResponse:
    """Сменить стадию вакансии в kanban-доске: нет PG → 503, нет вакансии → 404, стадия → 400."""
    try:
        job = await set_stage_via(WEB, job_id, body.stage, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobStageResponse(id=job.id or 0, vacancy_id=job.vacancy_id, status=job.status or "")


@router.post("/jobs/{job_id}/skip", response_model=JobSkipResponse)
async def skip_job(
    job_id: int,
    body: JobSkipUpdate,
    account: AccountContext = Depends(require_account_context),
) -> JobSkipResponse:
    """Пометить вакансию «Пропущено» с kanban-доски (перетащили карточку в колонку «Пропущено»)."""
    try:
        job = await skip_via(WEB, job_id, body.reason, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobSkipResponse(id=job.id or 0, vacancy_id=job.vacancy_id, skipped=True)


@router.delete("/jobs/{job_id}/skip", response_model=JobSkipResponse)
async def unskip_job(
    job_id: int, account: AccountContext = Depends(require_account_context)
) -> JobSkipResponse:
    """Снять пропуск с kanban-доски (перетащили карточку из «Пропущено» в активный этап)."""
    try:
        job = await unskip_via(WEB, job_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobSkipResponse(id=job.id or 0, vacancy_id=job.vacancy_id, skipped=False)


@router.delete("/jobs/{job_id}", response_model=JobDeleteResponse)
async def delete_job(
    job_id: int, account: AccountContext = Depends(require_account_context)
) -> JobDeleteResponse:
    """Удалить вакансию целиком с доски (кнопка «Удалить» в дровере — кривая карточка)."""
    try:
        job = await delete_job_card(job_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobDeleteResponse(id=job.id or 0, vacancy_id=job.vacancy_id, deleted=True)


@router.patch("/jobs/{job_id}", response_model=JobApplyFieldsResponse)
async def update_job_apply_fields(
    job_id: int,
    body: JobApplyFieldsUpdate,
    account: AccountContext = Depends(require_account_context),
) -> JobApplyFieldsResponse:
    """Поля карточки вакансии: заметка, дата отклика, флаг письма, сопроводительное (None = не менять)."""
    try:
        job = await update_job_card(job_id, **body.model_dump(), account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobApplyFieldsResponse(
        id=job.id or 0,
        vacancy_id=job.vacancy_id,
        note=job.note,
        applied_at=job.applied_at,
        letter_required=job.letter_required,
        cover_letter_text=job.cover_letter_text,
        work_format=job.work_format,
    )


@router.patch("/jobs/{job_id}/track", response_model=JobTrackResponse)
async def patch_job_track(
    job_id: int,
    body: JobTrackUpdate,
    account: AccountContext = Depends(require_account_context),
) -> JobTrackResponse:
    """Ручная поправка трека карточки: побеждает вывод агента, рескор не перетирает."""
    try:
        job = await set_job_track(job_id, body.track, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return JobTrackResponse(
        id=job.id or 0,
        vacancy_id=job.vacancy_id,
        track=job.track or body.track,
        track_override=job.track_override,
        overall_score=job.overall_score,
        recommendation=job.recommendation,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    account: AccountContext = Depends(require_account_context),
) -> MetricsResponse:
    """Агрегаты llm_usage аккаунта запроса (стоимость по агентам и по дням).

    Строго по аккаунту, без операторского исключения (решение владельца 2026-08-06, план §3.8,
    §9 п.3) — «эта ручка отвечает про меня» для всех, включая владельца.
    """
    usage = await load_usage_metrics(account_id=account.account_id)
    return MetricsResponse(
        today_cost_usd=usage.today_cost_usd,
        total_cost_usd=usage.total_cost_usd,
        token_stats=TokenStats(
            today_basic=TierTokenTotals(**usage.today_basic.model_dump()),
            today_advanced=TierTokenTotals(**usage.today_advanced.model_dump()),
            month_basic=TierTokenTotals(**usage.month_basic.model_dump()),
            month_advanced=TierTokenTotals(**usage.month_advanced.model_dump()),
        ),
        usage_by_agent=[UsageByAgent(**row.model_dump()) for row in usage.usage_by_agent],
        cost_by_day=[CostByDay(**row.model_dump()) for row in usage.cost_by_day],
    )


@router.get("/session", response_model=SessionResponse)
async def get_session() -> SessionResponse:
    """Пинг сессии для фронта: `{authed: true}` без обращения к БД.

    Сам факт ответа 200 при `require_auth` значит, что cookie/ключ валидны.
    """
    return SessionResponse(authed=True)
