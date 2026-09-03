"""Q&A по вакансии — путь расширения.

Кросс-доменный сценарий: ответ — `preparation.asker`, enrichment/этапы —
`preparation.interview_stages`, запись обмена в единый разговор — `pipeline`.
Раньше склейка жила в `api/routers/opportunities/vacancies.py`.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from core.domains.assistant.models import AskMessage
from core.kernel.errors import InvalidInput, LlmError, UpstreamError

logger = logging.getLogger(__name__)

_MIN_TEXT = 50


class AskResult(BaseModel):
    """Ответ LLM + откуда взяли enrichment (request / db)."""

    vacancy_id: str
    answer: str
    context_source: str = "request"


async def _fallback_from_stored_job(
    vacancy_id: str,
    *,
    account_id: int,
    title: str | None,
    company: str | None,
    salary_text: str | None,
    score,
):
    """Подтягивает текст/метаданные/скор уже проскоренной вакансии из Postgres.

    Нужен для страниц расширения без разметки JD в DOM (напр. hh.ru
    `/applicant/vacancy_response` — форма «доп. вопрос при отклике», куда HH иногда уводит
    вместо AJAX-отклика на месте) — вакансия там уже сохранена при исходном скоринге, и Q&A
    не должен упираться в пустой DOM-парс расширения.
    """
    from core.domains.opportunities.jobs import get_job_by_vacancy_id
    from core.domains.opportunities.models import ScoreResult

    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → остаёмся с тем, что прислал клиент
        logger.debug("Q&A: фолбэк на сохранённую вакансию недоступен: %s", exc)
        return "", title, company, salary_text, score

    if job is None:
        return "", title, company, salary_text, score

    if score is None and job.score:
        try:
            score = ScoreResult.model_validate(job.score)
        except Exception as exc:  # noqa: BLE001 — битый jsonb → без скора, не без ответа
            logger.debug("Q&A: score вакансии %s не провалидировался: %s", vacancy_id, exc)

    return (
        (job.vacancy_text or "").strip(),
        title or job.title,
        company or job.company,
        salary_text or job.salary_text,
        score,
    )


async def ask(
    vacancy_id: str,
    *,
    question: str,
    vacancy_text: str | None,
    title: str | None = None,
    company: str | None = None,
    salary_text: str | None = None,
    score=None,
    history: list[AskMessage] | None = None,
    account_id: int,
) -> AskResult:
    """Ответ LLM по вакансии с учётом текста, оценки, enrichment и резюме кандидата."""
    text = (vacancy_text or "").strip()
    if len(text) < _MIN_TEXT:
        text, title, company, salary_text, score = await _fallback_from_stored_job(
            vacancy_id,
            account_id=account_id,
            title=title,
            company=company,
            salary_text=salary_text,
            score=score,
        )
    if len(text) < _MIN_TEXT:
        raise InvalidInput("vacancy_text не передан или слишком короткий")

    from core.domains.preparation.asker import ask_about_vacancy, record_from_request_fallback

    record = record_from_request_fallback(
        vacancy_id,
        vacancy_text=text,
        title=title or "",
        company=company or "",
        salary_text=salary_text or "",
        score=score,
    )
    msgs = list(history or [])

    bundle = None
    context_source = "request"
    try:
        from core.domains.preparation.interview_stages import load_bundle

        pg_bundle = await load_bundle(vacancy_id, account_id=account_id)
        if pg_bundle.enrichment is not None or pg_bundle.stages:
            bundle = pg_bundle
            context_source = "db"
    except Exception as exc:  # noqa: BLE001 — нет PG → Q&A по тексту вакансии
        logger.debug("Q&A enrichment из Postgres недоступен: %s", exc)

    logger.info(
        "Q&A vacancy_id=%s question_len=%d history=%d enrichment=%s",
        vacancy_id,
        len(question),
        len(msgs),
        bundle is not None,
    )

    try:
        answer = await ask_about_vacancy(record, question, msgs, bundle=bundle)
    except LlmError as exc:
        logger.error("Q&A OpenRouter error: %s", exc)
        raise UpstreamError(str(exc)) from exc

    if answer:
        try:
            from core.domains.pipeline.hr_threads import append_llm_exchange

            await append_llm_exchange(
                vacancy_id,
                question=question,
                answer=answer,
                company=company or "",
                account_id=account_id,
            )
        except Exception as exc:  # noqa: BLE001 — персист best-effort, ответ уже готов
            logger.debug("Q&A: обмен не записан в разговор (нет PG?): %s", exc)

    return AskResult(vacancy_id=vacancy_id, answer=answer, context_source=context_source)


__all__ = ["AskResult", "ask"]
