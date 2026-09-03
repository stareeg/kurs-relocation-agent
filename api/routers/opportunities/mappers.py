"""Проекции домена opportunities в транспортные схемы.

Роутер обязан оставаться в 15 строках, а `ScoreResponse` — это 18 полей-в-поле. Место такой
раскладки — рядом с роутером: это транспорт, не доменное знание.
"""

from __future__ import annotations

from api.schemas import (
    CompanyRegistryItem,
    CompanyRegistryResponse,
    ScoreResponse,
)
from core.domains.opportunities.competition import compute_competition_insight
from core.domains.opportunities.models import VacancyInput
from core.domains.opportunities.service import ScoreOutcome


def score_response(vac: VacancyInput, outcome: ScoreOutcome) -> ScoreResponse:
    """Метаданные берём из сохранённой строки, если она есть, иначе из входа расширения."""
    job = outcome.job
    source = job if job is not None else vac
    return ScoreResponse(
        id=job.id if job is not None else None,
        vacancy_id=source.vacancy_id,
        url=source.url,
        title=source.title,
        company=source.company,
        salary_text=source.salary_text,
        area=source.area,
        work_format=source.work_format,
        work_schedule=source.work_schedule,
        total_responses=source.total_responses,
        letter_required=source.letter_required,
        published_at=source.published_at,
        employer_id=source.employer_id,
        source=source.source,
        is_archived=source.is_archived,
        status=source.status,
        scored_at=job.scored_at if job is not None else None,
        persisted=outcome.persisted,
        score=outcome.score,
        remote_feasibility=outcome.remote,
        # Этап 6 §6.2: чистая функция, дешевле хранить в ScoreOutcome — не персистится (PG
        # недоступен) считается точно так же, как персистится (_build_job).
        competition=compute_competition_insight(
            total_responses=source.total_responses,
            published_at=source.published_at,
            letter_required=source.letter_required,
        ),
    )


def company_registry_response(rows) -> CompanyRegistryResponse:
    """Агрегаты + вердикт → реестр компаний на «Рынке»."""
    return CompanyRegistryResponse(
        items=[
            CompanyRegistryItem(
                company=r.company,
                vacancy_count=r.vacancy_count,
                avg_score=r.avg_score,
                best_stage=r.best_stage,
                last_seen_at=r.last_seen_at,
                verdict=r.verdict,
            )
            for r in rows
        ]
    )


def job_to_score_response(job) -> ScoreResponse:
    """Собрать ScoreResponse из сохранённой строки Job (для GET /vacancies/{id}/record).

    Авто-разворот в расширении: когда локального кэша расширения нет, оно тянет
    запись отсюда и сразу показывает результаты скоринга. Вызывающий (роутер)
    гарантирует, что `job.score` не None — иначе 404 на уровне эндпоинта.
    """
    from core.domains.opportunities.models import CompetitionInsight, RemoteFeasibility, ScoreResult

    # Роутер отсёк вакансии без score (404), но для pyright фиксируем инвариант.
    assert job.score is not None
    score = ScoreResult.model_validate(job.score)
    remote = (
        RemoteFeasibility.model_validate(job.remote_feasibility) if job.remote_feasibility else None
    )
    competition = CompetitionInsight.model_validate(job.competition) if job.competition else None
    return ScoreResponse(
        id=job.id,
        vacancy_id=job.vacancy_id,
        url=job.url,
        title=job.title,
        company=job.company,
        salary_text=job.salary_text,
        area=job.area,
        work_format=job.work_format,
        work_schedule=job.work_schedule,
        total_responses=job.total_responses,
        letter_required=job.letter_required,
        published_at=job.published_at,
        employer_id=job.employer_id,
        source=job.source,
        is_archived=job.is_archived,
        status=job.status,
        scored_at=job.scored_at,
        persisted=True,
        score=score,
        remote_feasibility=remote,
        competition=competition,
    )


__all__ = ["company_registry_response", "job_to_score_response", "score_response"]
