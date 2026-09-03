"""Персист оценённой вакансии в Postgres (`jobs` + `application_stages`).

Обе записи идут в одном Unit of Work — падение на стадии не оставляет job без stage.
Postgres — единственный источник истины.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from core.config import CoreSettings, get_settings
from core.domains.opportunities.competition import compute_competition_insight
from core.domains.opportunities.dedup import find_duplicate, tokens_array
from core.domains.opportunities.events import publish_vacancy_deduplicated, publish_vacancy_scored
from core.domains.opportunities.jobs import Job, get_job_by_vacancy_id
from core.domains.opportunities.models import RemoteFeasibility, ScoreResult, VacancyInput
from core.domains.opportunities.ports import JobsRepository
from core.domains.opportunities.preferences_digest import learned_preferences_block_safe
from core.domains.opportunities.remote_feasibility import assess_remote_feasibility_safe
from core.domains.opportunities.repo import PgJobsRepository
from core.domains.opportunities.salary_async import schedule_salary_estimate
from core.domains.opportunities.scorer import score_vacancy
from core.domains.opportunities.skip_reasons_async import schedule_skip_reasons
from core.kernel import ports
from core.kernel.schemas.funnel import FunnelStatus
from core.kernel.schemas.track import SearchTrack
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)


async def _existing_track_override(
    vacancy_id: str | None, *, account_id: int
) -> SearchTrack | None:
    """Ручной трек карточки, если владелец его зафиксировал. None — классифицировать заново."""
    if not vacancy_id:
        return None
    try:
        existing = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception:  # noqa: BLE001 — нет PG → скоринг без override
        return None
    if not existing or not existing.track_override:
        return None
    if existing.track == "primary" or existing.track == "second_job":
        return existing.track
    return None


# Поля, которые дедупликация может дозаполнить у канонической вакансии (COALESCE-семантика).
_ENRICH_FIELDS: tuple[str, ...] = (
    "salary_text",
    "title",
    "company",
    "work_format",
    "published_at",
    "url",
    "vacancy_text",
)


def _enriched_fields(before: Job, after: Job) -> dict[str, Any]:
    """Какие поля дозаполнились при обогащении канона (для события VacancyDeduplicated)."""
    out: dict[str, Any] = {}
    for field in _ENRICH_FIELDS:
        b = getattr(before, field, None)
        a = getattr(after, field, None)
        if not b and a:
            out[field] = a
    return out


class ScoredJob(BaseModel):
    job: Job
    score: ScoreResult


def _score_from_job(job: Job) -> ScoreResult | None:
    """Реконструировать ``ScoreResult`` из уже сохранённого ``jobs.score`` канона.

    None — score пуст или не парсится (стаб/легаси-строка, см. Этап 8 §8.3): тогда экономить
    LLM-вызов не на чем, и вызывающий обязан посчитать скор как обычно.
    """
    if not job.score:
        return None
    try:
        return ScoreResult.model_validate(job.score)
    except Exception:  # noqa: BLE001 — не сорвать персист из-за мусора в старом jsonb
        return None


async def _attach_to_canonical(
    vac: VacancyInput, canonical: Job, *, repo: JobsRepository, account_id: int
) -> Job:
    """Дозаполнить каноническую вакансию + добавить ссылку источника ``vac``.

    Общая точка для до- и после-скоринговой дедупликации (`score_and_persist` §8.1 /
    `persist_scored_with_repo`) — иначе COALESCE-семантика обогащения и событие
    `VacancyDeduplicated` неизбежно разъехались бы при следующей правке одного из путей.
    """
    assert canonical.id is not None
    enriched = await repo.enrich_job(
        canonical.id,
        salary_text=vac.salary_text,
        title=vac.title,
        company=vac.company,
        work_format=vac.work_format,
        published_at=vac.published_at,
        url=vac.url,
        vacancy_text=vac.text,
    )
    enriched = enriched or canonical
    await repo.add_job_link(
        canonical.id,
        source=vac.source or "",
        vacancy_id=vac.vacancy_id,
        url=vac.url,
        is_primary=False,
    )
    publish_vacancy_deduplicated(
        vacancy_id=vac.vacancy_id or "",
        canonical_job_id=canonical.id,
        source=vac.source or "",
        enriched=_enriched_fields(canonical, enriched),
        account_id=account_id,
    )
    return enriched


async def _find_pre_score_duplicate(
    vac: VacancyInput, *, repo: JobsRepository, account_id: int
) -> ScoredJob | None:
    """Кросс-площадочный дубль ДО скоринга (Этап 8 §8.1).

    Раньше единственная проверка дедупа жила в `persist_scored_with_repo` — уже ПОСЛЕ того,
    как `score_and_persist` оплатил LLM-вызов за вакансию, чей текст уже лежит в базе под
    другим `vacancy_id`. Здесь — та же проверка, но раньше и с ранним выходом: если у канона
    уже есть валидный скор, новый вызов `score_vacancy` не нужен вовсе.

    None — дубля нет, либо есть, но канон ещё не оценён (пустой/нечитаемый `score`) — тогда
    вызывающий обязан посчитать скор как обычно (тот путь сам найдёт тот же дубль постфактум
    и приложит ссылку, см. `persist_scored_with_repo`).
    """
    if not vac.vacancy_id or not vac.text:
        return None
    if await repo.get_by_vacancy_id(vac.vacancy_id) is not None:
        return None
    try:
        candidates = await repo.find_duplicate_candidates(tokens_array(vac.text))
    except Exception as exc:  # noqa: BLE001 — дедуп best-effort, не валит скоринг/персист
        logger.debug("дедупликация недоступна для %s: %s", vac.vacancy_id, exc)
        return None
    canonical = find_duplicate(vac.text, candidates)
    if canonical is None or canonical.id is None:
        return None
    canonical_score = _score_from_job(canonical)
    if canonical_score is None:
        return None
    attached = await _attach_to_canonical(vac, canonical, repo=repo, account_id=account_id)
    return ScoredJob(job=attached, score=canonical_score)


def _build_job(
    vac: VacancyInput,
    score: ScoreResult,
    status: str,
    remote: RemoteFeasibility | None = None,
) -> Job:
    return Job(
        vacancy_id=vac.vacancy_id,
        url=vac.url,
        title=vac.title,
        company=vac.company,
        vacancy_text=vac.text,
        salary_text=vac.salary_text,
        area=vac.area,
        work_format=vac.work_format,
        work_schedule=vac.work_schedule,
        total_responses=vac.total_responses,
        letter_required=vac.letter_required,
        published_at=vac.published_at,
        cover_letter_text=vac.cover_letter_text,
        employer_id=vac.employer_id,
        source=vac.source,
        is_archived=vac.is_archived,
        status=status,
        overall_score=score.overall_score,
        recommendation=score.recommendation,
        work_city=score.work_city or None,
        score=score.model_dump(mode="json"),
        salary=score.salary.model_dump(mode="json"),
        remote_feasibility=remote.model_dump(mode="json") if remote else None,
        # Этап 6 §6.2: чистая функция от полей vac, что уже на руках — не нужен ни LLM-вызов,
        # ни отдельный параметр _build_job (в отличие от remote — тот async, этот нет).
        competition=compute_competition_insight(
            total_responses=vac.total_responses,
            published_at=vac.published_at,
            letter_required=vac.letter_required,
        ).model_dump(mode="json"),
        skills=vac.skills or [],
        specialization=vac.specialization,
        seniority=vac.seniority,
        track=score.track,
        work_terms=None,
    )


async def persist_scored_with_repo(
    vac: VacancyInput,
    score: ScoreResult,
    *,
    repo: JobsRepository,
    account_id: int,
    remote: RemoteFeasibility | None = None,
) -> ScoredJob:
    """Тело персиста через порт репозитория — для прод-UoW и memory-теста A-17.

    ``account_id`` дублирует то, что уже зашито в ``repo`` (`PgJobsRepository(db,
    account_id=...)`) — Protocol `JobsRepository` не несёт его в сигнатурах методов (см.
    repo.py), но событию `VacancyScored` он нужен явно, поэтому передаётся сюда отдельно, а не
    выковыривается из `repo` рефлексией.
    """
    existing = await repo.get_by_vacancy_id(vac.vacancy_id) if vac.vacancy_id else None
    status = (vac.status or "").strip() or (
        FunnelStatus.REJECTED.value if vac.is_archived else FunnelStatus.VIEWED.value
    )

    terms_dump = None
    if vac.vacancy_id:
        try:
            from core.domains.opportunities.work_terms import load_work_terms

            cached = await load_work_terms(vac.vacancy_id)
            if cached is not None:
                terms_dump = cached.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 — денорм best-effort
            logger.debug("work_terms кэш недоступен для %s: %s", vac.vacancy_id, exc)

    job_row = _build_job(vac, score, status, remote)
    if terms_dump is not None:
        job_row = job_row.model_copy(update={"work_terms": terms_dump})

    # S12: кросс-площадочная дедупликация. Если по vacancy_id записи нет — проверить, не та же
    # ли это вакансия на другой площадке (Jaccard по токенам > порога). Нашли → не создаём новую
    # строку `jobs`, а прикрепляем ссылку к канонической и дозаполняем её пустые поля.
    duplicate: Job | None = None
    if existing is None and vac.vacancy_id and vac.text:
        try:
            candidates = await repo.find_duplicate_candidates(tokens_array(vac.text))
            duplicate = find_duplicate(vac.text, candidates)
        except Exception as exc:  # noqa: BLE001 — дедуп best-effort, не валит скоринг/персист
            logger.debug("дедупликация недоступна для %s: %s", vac.vacancy_id, exc)

    if duplicate is not None and duplicate.id is not None:
        canonical = await _attach_to_canonical(vac, duplicate, repo=repo, account_id=account_id)
        # Пользователь видит каноническую карточку («вакансия уже есть»), а не дубль на доске.
        return ScoredJob(job=canonical, score=score)

    # Повторный скоринг уже известной вакансии не должен трогать её текущий статус воронки:
    # расширение шлёт `/score` и «Отметить отклик» (POST /funnel) как параллельные запросы
    # без гарантии порядка, а клик «Откликнуться» до завершения скоринга раньше терялся —
    # /score дописывал стадию «Просмотр» и откатывал jobs.status обратно поверх «Отклика».
    job = await repo.save(job_row, preserve_status=existing is not None)
    assert job.id is not None
    if existing is None:
        await repo.add_stage(job.id, status, source="scoring")

    # A-11: факт «вакансия оценена» — после обеих записей; без ожидания подписчиков.
    publish_vacancy_scored(
        vacancy_id=vac.vacancy_id or "",
        job_id=job.id,
        overall_score=score.overall_score,
        recommendation=score.recommendation,
        source=vac.source or "",
        account_id=account_id,
    )

    # Пропуск (skipped_vacancies) НЕ пишем по recommendation=skip: это решение «не подавать»,
    # а рекомендация модели — лишь совет. Авто-запись приравнивала совет к выбору пользователя,
    # что навсегда гасило вакансию в триаже расширения (тупик «Пропущено» без действий). Совет
    # модели остаётся в jobs.recommendation/score; пропуск фиксирует только явный POST /skip.

    return ScoredJob(job=job, score=score)


async def persist_scored(
    vac: VacancyInput,
    score: ScoreResult,
    *,
    account_id: int,
    remote: RemoteFeasibility | None = None,
    db: Executor | None = None,
    settings: CoreSettings | None = None,
) -> ScoredJob:
    """Сохранить оценённую вакансию в PG. Скоринг должен быть уже посчитан.

    `remote` - под-скор реальности удалёнки; None → колонка пустая
    (под-скор не считался или упал, best-effort).

    Без явного ``db`` обе записи (job + stage) идут в одном UoW. Явный ``db`` —
    для вызывающего, который уже держит connection/транзакцию (или пул).
    """
    _ = settings or get_settings()  # сохранён для сигнатуры CLI/тестов
    if db is not None:
        return await persist_scored_with_repo(
            vac,
            score,
            repo=PgJobsRepository(db, account_id=account_id),
            account_id=account_id,
            remote=remote,
        )
    async with ports.uow() as uow:
        return await persist_scored_with_repo(
            vac,
            score,
            repo=PgJobsRepository(uow.session, account_id=account_id),
            account_id=account_id,
            remote=remote,
        )


def schedule_post_persist_follow_ups(
    vac: VacancyInput, score: ScoreResult, *, account_id: int
) -> None:
    """Поставить фоновые LLM-догонки после успешного персиста — общая точка для ЛЮБОГО пути
    скоринга (расширение, discovery, HR outreach, Telegram-forward).

    Раньше `score_and_persist` не звал это вовсе — вакансии из discovery/outreach/forwarded
    с `estimate_pending=True` навсегда оставались без вилки (и без причин пропуска), а расширение
    (`score_and_store`) держало эти два вызова прямо в себе — риск разъехаться при правке одного
    пути и забыть другой. Без `vacancy_id` планировать нечего (идемпотентный ключ очереди строится
    на нём) — тихо выходим, как и раньше делали оба вызывающих по отдельности.
    """
    if not vac.vacancy_id:
        return
    if score.salary.estimate_pending:
        schedule_salary_estimate(vac.vacancy_id, vac.text, score, account_id=account_id)
    schedule_skip_reasons(vac.vacancy_id, vac.text, score, account_id=account_id)


async def score_and_persist(
    vac: VacancyInput,
    *,
    account_id: int,
    db: Executor | None = None,
    settings: CoreSettings | None = None,
) -> ScoredJob:
    """Скоринг + персист одним вызовом (точка входа для API/CLI/scheduler).

    Основной скоринг и под-скор удалёнки (feature_ideas 2.2) считаем параллельно - под-скор на
    дешёвом тире extract, его падение не валит основной путь (assess_*_safe возвращает None).

    `preferences` (Этап 7 §7.4, D12) — выученные предпочтения по истории решений владельца
    (preferences_digest.py): читаются best-effort ДО скоринга, т.к. идут динамическим хвостом
    в его system-промпт (`score_vacancy(..., preferences=...)`). Ни одного LLM-вызова — только
    Postgres, не нарушает бюджет §1.13; падение отдаёт "" (промпт как раньше), не роняет скоринг.

    Дедуп (Этап 8 §8.1) проверяется ДО скоринга: этот вызов, в отличие от расширения
    (`service.score_and_store`), не обязан отдать свежий скор синхронно вызывающему (discovery/
    outreach/forwarded — фоновые пути), поэтому уже оценённый кросс-площадочный дубль экономит
    целый LLM-вызов вместо того, чтобы обнаружиться постфактум в `persist_scored`.
    """
    if vac.vacancy_id and vac.text:
        pre_dup: ScoredJob | None
        if db is not None:
            pre_dup = await _find_pre_score_duplicate(
                vac, repo=PgJobsRepository(db, account_id=account_id), account_id=account_id
            )
        else:
            async with ports.uow() as uow:
                pre_dup = await _find_pre_score_duplicate(
                    vac,
                    repo=PgJobsRepository(uow.session, account_id=account_id),
                    account_id=account_id,
                )
        if pre_dup is not None:
            return pre_dup

    preferences = await learned_preferences_block_safe(account_id, db=db)
    existing_override = await _existing_track_override(vac.vacancy_id, account_id=account_id)
    score, remote = await asyncio.gather(
        score_vacancy(
            vac.text,
            account_id=account_id,
            is_archived=vac.is_archived,
            salary_use_llm=None,
            vacancy_id=vac.vacancy_id,
            company=vac.company,
            salary_text=vac.salary_text,
            skills=vac.skills,
            specialization=vac.specialization,
            seniority=vac.seniority,
            preferences=preferences,
            employment_type=vac.employment_type,
            location_raw=vac.location_raw,
            remote_type=vac.remote_type,
            track_override=existing_override,
        ),
        assess_remote_feasibility_safe(vac.text),
    )
    scored = await persist_scored(
        vac, score, account_id=account_id, remote=remote, db=db, settings=settings
    )
    schedule_post_persist_follow_ups(vac, score, account_id=account_id)
    return scored
