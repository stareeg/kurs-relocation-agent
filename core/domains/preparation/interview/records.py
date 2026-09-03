"""Сборка `VacancyRecord` из Postgres-`Job` для prep/debrief.

Q&A-путь (`core.domains.preparation.asker.record_from_request_fallback`) строит запись из payload расширения;
бот же знает только vacancy_id и тянет вакансию из `jobs` (источник истины). `job.score` —
полный ScoreResult-словарь (jsonb); если пусто (вакансия без скоринга) — подставляем
дефолтную оценку, как делает Q&A-fallback, чтобы промпт не падал.
"""

from __future__ import annotations

from core.domains.opportunities.jobs import Job, get_job_by_vacancy_id
from core.domains.preparation.models import ScoreResult, VacancyRecord
from core.platform.db.pool import Executor


def _fallback_score(salary_text: str | None) -> ScoreResult:
    """Дефолтная оценка для вакансии без скоринга (порт смысла Q&A-fallback)."""
    return ScoreResult.model_validate(
        {
            "overall_score": 0,
            "recommendation": "maybe",
            "remote_abroad_compat": {"level": "risky", "reasoning": "нет оценки"},
            "grade_match": {"level": "match", "reasoning": "нет оценки"},
            "salary": {
                "meets_min": False,
                "value_or_range": salary_text or "",
                "estimated_range": "",
                "note": "оценка недоступна",
            },
            "role_content_match": {"score": 0, "matched_niche": [], "reasoning": ""},
            "burnout_risk": {"level": "medium", "reasoning": "нет оценки"},
            "company_type": "unknown",
            "pros": ["—"],
            "cons": ["—"],
            "red_flags": [],
            "one_line_verdict": "Оценка недоступна — разбор только по тексту вакансии",
        }
    )


def record_from_job(job: Job) -> VacancyRecord:
    """Job (PG) → VacancyRecord (вход prep/debrief). score из jsonb, иначе дефолт."""
    score = ScoreResult.model_validate(job.score) if job.score else _fallback_score(job.salary_text)
    return VacancyRecord(
        id=job.id,
        vacancy_id=job.vacancy_id,
        vacancy_text=job.vacancy_text,
        url=job.url,
        title=job.title,
        company=job.company,
        salary_text=job.salary_text,
        area=job.area,
        work_schedule=job.work_schedule,
        total_responses=job.total_responses,
        letter_required=job.letter_required,
        published_at=job.published_at,
        cover_letter_text=job.cover_letter_text,
        employer_id=job.employer_id,
        source=job.source,
        is_archived=job.is_archived,
        status=job.status,
        score=score,
    )


async def load_record(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> VacancyRecord | None:
    """Вакансия из `jobs` по HH vacancy_id → VacancyRecord; None, если в БД нет."""
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    return record_from_job(job) if job is not None else None
