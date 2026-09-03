"""События домена opportunities: что публикует и на что подписан (шина — A-11).

Публикаторы зовут хелперы отсюда, а не собирают событие на месте: так call-site остаётся
одной строкой, а набор полей события меняется в одном файле.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import (
    ApplicationStageChanged,
    ResumeUpdated,
    SearchTrackChanged,
    VacancyDeduplicated,
    VacancyScored,
)
from core.kernel.ids import VacancyId

logger = logging.getLogger(__name__)

PUBLISHES: tuple[type, ...] = (VacancyScored, ApplicationStageChanged, VacancyDeduplicated)


async def on_vacancy_scored(evt: VacancyScored) -> None:
    """Новая/переоценённая вакансия → требуемые навыки в фон (kэш по `text_hash`).

    Повторный скоринг того же текста не делает нового LLM-вызова (кэш `get_or_extract_requirements`
    по `vacancy_id` + `text_hash`). Само событие не несёт `vacancy_text` (A-11: события — только
    идентификаторы), поэтому текст догружается репозиторием того же домена.
    """
    if not evt.vacancy_id:
        return
    from core.domains.opportunities.jobs import get_job_by_vacancy_id
    from core.domains.opportunities.requirements import get_or_extract_requirements

    job = await get_job_by_vacancy_id(evt.vacancy_id, account_id=evt.account_id)
    if job is None or not job.vacancy_text:
        return
    # vacancy_skill_requirements остаётся глобальным кэшем (плана) — account_id не нужен.
    await get_or_extract_requirements(evt.vacancy_id, job.vacancy_text)

    # Э2.1: условия работы — только при включённом втором треке (кост-гард). Кэш по
    # text_hash: повторный скоринг того же текста нового LLM-вызова не делает.
    try:
        from core.domains.career.track_state import get_current_tracks

        tracks = await get_current_tracks(account_id=evt.account_id)
    except Exception as exc:  # noqa: BLE001 — нет журнала → не экстрагируем
        logger.debug("треки поиска недоступны в on_vacancy_scored: %s", exc)
        return
    if not tracks.second_job_enabled:
        return
    from core.domains.opportunities.rescore import apply_extracted_work_terms
    from core.domains.opportunities.work_terms import get_or_extract_work_terms

    terms = await get_or_extract_work_terms(evt.vacancy_id, job.vacancy_text)
    if job.work_terms is not None:
        return
    await apply_extracted_work_terms(job, terms, account_id=evt.account_id)


def on_resume_updated(evt: ResumeUpdated) -> None:
    """Резюме сохранено → веса/role_kind рубрики могли измениться (Этап 5 §5.1/§5.2): уже
    проскоренные вакансии перескориваются без LLM, чтобы доска не сравнивала их по разным
    линейкам (D7, plans/scoring_precision_2026_08_17.md). Bootstrap-путь (`account_id=0`) не
    планируем — некому: аккаунтов ещё нет.
    """
    if not evt.account_id:
        return
    from core.domains.opportunities.rescore import schedule_rescore_all

    schedule_rescore_all(evt.account_id)


def on_search_track_changed(evt: SearchTrackChanged) -> None:
    """Набор треков сменился → рубрика доски могла разъехаться: тот же полный перескор,
    что и при правке резюме. Bootstrap (`account_id=0`) не планируем.
    """
    if not evt.account_id:
        return
    from core.domains.opportunities.rescore import schedule_rescore_all

    schedule_rescore_all(evt.account_id)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (VacancyScored, on_vacancy_scored),
    (ResumeUpdated, on_resume_updated),
    (SearchTrackChanged, on_search_track_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)


def publish_vacancy_scored(
    *,
    vacancy_id: str,
    job_id: int | None = None,
    overall_score: float | None = None,
    recommendation: str = "",
    source: str = "",
    account_id: int,
) -> None:
    """Вакансия оценена и сохранена. Без ожидания: подписчики тут — прогрев и аналитика."""
    ports.events().publish(
        VacancyScored(
            vacancy_id=VacancyId(vacancy_id),
            job_id=job_id,
            overall_score=overall_score,
            recommendation=recommendation,
            source=source,
            account_id=account_id,
        )
    )


def publish_vacancy_deduplicated(
    *,
    vacancy_id: str,
    canonical_job_id: int | None = None,
    source: str = "",
    enriched: dict[str, Any] | None = None,
    account_id: int,
) -> None:
    """Та же вакансия найдена на другой площадке — ссылка прикреплена к канону, поля дозаполнены.

    Без ожидания: подписчики (career-лента) — аналитика/память, а не эффект, видимый в ответе.
    """
    ports.events().publish(
        VacancyDeduplicated(
            vacancy_id=VacancyId(vacancy_id),
            canonical_job_id=canonical_job_id,
            source=source,
            enriched=enriched or {},
            account_id=account_id,
        )
    )


async def publish_application_stage_changed(
    *,
    vacancy_id: str,
    job_id: int | None,
    stage: str,
    previous_stage: str = "",
    source: str = "",
    account_id: int,
) -> None:
    """Стадия воронки сменилась.

    С ожиданием: на этом событии висят эффекты, которые должны быть видны сразу после ответа
    (отметка пройденного HR-скрининга при переходе в «Техничку»), — раньше их вызывали отсюда
    прямым импортом чужого домена.
    """
    await ports.events().publish_and_wait(
        ApplicationStageChanged(
            vacancy_id=VacancyId(vacancy_id),
            job_id=job_id,
            stage=stage,
            previous_stage=previous_stage,
            source=source,
            account_id=account_id,
        )
    )


__all__ = [
    "ApplicationStageChanged",
    "PUBLISHES",
    "ResumeUpdated",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "VacancyDeduplicated",
    "VacancyScored",
    "on_resume_updated",
    "on_search_track_changed",
    "on_vacancy_scored",
    "publish_application_stage_changed",
    "publish_vacancy_deduplicated",
    "publish_vacancy_scored",
]
