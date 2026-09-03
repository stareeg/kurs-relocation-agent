"""Сценарии домена opportunities — точка входа для скоринга, discovery, персиста, доски.

Роутер `POST /score`, расширение, batch discovery и CLI зовут отсюда (или из
публичного `__init__`). Сценарии доски переехали сюда из `api/routers`: смена стадии,
пропуск, поля карточки, статус воронки — всё это правки `jobs` + история `application_stages`,
то есть данные этого домена, а не транспорт.

Раскладка деградации сохранена дословно: чтение витрин молчит и отдаёт пустое, запись без
Postgres бросает `StorageUnavailable` (иначе UI соврал бы владельцу про сохранение).
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel

from core.domains.opportunities.discovery import (
    DiscoveredVacancy,
    hh_discovery,
    run_batch_discovery_stream,
)
from core.domains.opportunities.jobs import (
    SOURCE_HH_APPLY_STUB,
    Job,
    add_stage,
    backfill_vacancy_identity,
    delete_job,
    get_job,
    get_job_by_vacancy_id,
    job_record_needs_vacancy_text,
    save_job,
    update_apply_fields,
    update_job_track,
)
from core.domains.opportunities.models import RemoteFeasibility, ScoreResult, VacancyInput
from core.domains.opportunities.persist import (
    ScoredJob,
    persist_scored,
    schedule_post_persist_follow_ups,
    score_and_persist,
)
from core.domains.opportunities.recalibrate import rescore_from_hr_facts, rescore_from_hr_facts_safe
from core.domains.opportunities.remote_feasibility import (
    assess_remote_feasibility,
    assess_remote_feasibility_safe,
)
from core.domains.opportunities.scorer import score_vacancy
from core.domains.opportunities.skip_reasons import canonical_skip_reason
from core.domains.opportunities.skipped import (
    SkippedVacancy,
    delete_skipped,
    get_skipped,
    save_skipped,
)
from core.domains.opportunities.sources import to_vacancy_input
from core.kernel import ports
from core.kernel.errors import InvalidInput, NotFound, StorageUnavailable, UpstreamError
from core.kernel.schemas.funnel import all_funnel_status_values
from core.kernel.schemas.track import SearchTrack
from core.platform.observability import event

logger = logging.getLogger(__name__)

_NO_PG = "Postgres недоступен"


class ScoreOutcome(BaseModel):
    """Итог синхронного скоринга: оценка есть всегда, строка в БД — если Postgres поднят."""

    score: ScoreResult
    remote: RemoteFeasibility | None = None
    job: Job | None = None
    persisted: bool = False


async def score_from_source(
    source_name: str,
    query: str,
    *,
    llm: ports.LlmPort | None = None,
    persist: bool = True,
    account_id: int,
) -> list[ScoreOutcome]:
    """`VacancySource.fetch` → скоринг. Тест-двойник: `persist=False` + `llm=`."""
    source = ports.vacancy_source(source_name)
    raws = await source.fetch(query)
    outcomes: list[ScoreOutcome] = []
    for raw in raws:
        vac = to_vacancy_input(raw)
        if persist and llm is None:
            outcomes.append(await score_and_store(vac, account_id=account_id))
            continue
        try:
            score, remote = await asyncio.gather(
                score_vacancy(
                    vac.text,
                    account_id=account_id,
                    llm=llm,
                    vacancy_id=vac.vacancy_id,
                    company=vac.company,
                    salary_text=vac.salary_text,
                    skills=vac.skills,
                    specialization=vac.specialization,
                    seniority=vac.seniority,
                    employment_type=vac.employment_type,
                    location_raw=vac.location_raw,
                    remote_type=vac.remote_type,
                ),
                assess_remote_feasibility_safe(vac.text, llm=llm),
            )
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        outcomes.append(ScoreOutcome(score=score, remote=remote, persisted=False))
    return outcomes


async def score_and_store(vac: VacancyInput, *, account_id: int) -> ScoreOutcome:
    """Оценить вакансию и best-effort сохранить (горячий путь расширения, `POST /score`).

    Под-скор удалёнки считается параллельно и всегда best-effort (`assess_*_safe` → None),
    поэтому упасть может только сам скоринг. Нет Postgres → оценку всё равно отдаём: расширение
    показывает результат, персист догонит на следующем заходе.
    """
    try:
        track_override: SearchTrack | None = None
        if vac.vacancy_id:
            try:
                existing = await get_job_by_vacancy_id(vac.vacancy_id, account_id=account_id)
                found = existing.track if existing and existing.track_override else None
                if found == "primary" or found == "second_job":
                    track_override = found
            except Exception:  # noqa: BLE001 — нет PG → скоринг без override
                track_override = None
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
                employment_type=vac.employment_type,
                location_raw=vac.location_raw,
                remote_type=vac.remote_type,
                track_override=track_override,
            ),
            assess_remote_feasibility_safe(vac.text),
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — LLM/сеть; исторически 502 для расширения
        raise UpstreamError(str(exc)) from exc

    outcome = ScoreOutcome(score=score, remote=remote)
    try:
        scored = await persist_scored(vac, score, account_id=account_id, remote=remote)
        outcome.job = scored.job
        outcome.persisted = True
    except Exception as exc:  # noqa: BLE001 — без PG отдаём скоринг без сохранения
        event(
            logger,
            "БД",
            "скоринг не сохранён: %s: %s",
            vac.vacancy_id or "без id",
            exc,
            level=logging.WARNING,
            vacancy_id=vac.vacancy_id or "",
        )

    # Общая точка для обеих LLM-догонок (вилка + причины пропуска) — см. persist.py,
    # тот же вызов использует score_and_persist (discovery/outreach/forwarded).
    if outcome.persisted:
        schedule_post_persist_follow_ups(vac, score, account_id=account_id)
    return outcome


async def skip_and_store(
    vacancy_id: str,
    skip_reason: str,
    *,
    url: str | None = None,
    title: str | None = None,
    company: str | None = None,
    overall_score: int | None = None,
    recommendation: str | None = None,
    canonical_reason: str | None = None,
    account_id: int,
) -> SkippedVacancy:
    """Пропуск из расширения (`POST /skip`), обычно без предварительного `/score`.

    До 2026-08-18 сюда же заводился пустой jobs-stub (`SOURCE_SKIP_STUB`) — «быстрый пропуск»
    (чипы `SELF_SKIP_REASONS`, доступны ещё до того, как долетел /score) писал карточку без
    текста JD на доску «Вакансии», чтобы клик визуально подтверждался. С автооткликами и
    надёжным парсингом страницы вакансии смысл в этой карточке-инвалиде отпал — расширение и
    так умеет открыть вакансию и прочитать текст, а десятки пустых карточек в «Просмотрено»
    только мешали. Пропуск остаётся только в `skipped_vacancies` (список пропущенных — там же
    подтверждение владельцу), без записи в `jobs`.
    """
    return await save_skipped(
        vacancy_id,
        skip_reason,
        url=url,
        title=title,
        company=company,
        overall_score=overall_score,
        recommendation=recommendation,
        account_id=account_id,
        canonical_reason=canonical_reason,
    )


class FunnelSnapshot(BaseModel):
    """Статус воронки + факт/причина пропуска — снимок для `GET /funnel/{id}`."""

    status: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    # Числовой id строки jobs (для cover-letter API), None — вакансии в БД нет.
    job_id: int | None = None


async def get_funnel_snapshot(vacancy_id: str, *, account_id: int) -> FunnelSnapshot:
    """Статус воронки + пропуск (если есть) по `vacancy_id`, Postgres — источник истины.

    `skip_reason` — канонический (см. `canonical_skip_reason`): расширение хранит его
    per-vacancy только локально (skipReasonCache), должен переживать перезагрузку/новую вкладку.
    """
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    skipped_record = await get_skipped(vacancy_id, account_id=account_id)
    skip_reason = None
    if skipped_record is not None:
        skip_reason = skipped_record.canonical_reason or canonical_skip_reason(
            skipped_record.skip_reason
        )
    return FunnelSnapshot(
        status=job.status if job is not None and job.status else None,
        skipped=skipped_record is not None,
        skip_reason=skip_reason,
        job_id=job.id if job is not None else None,
    )


async def set_funnel_status(
    vacancy_id: str,
    status: str,
    *,
    cover_letter: str | None = None,
    published_at=None,
    title: str | None = None,
    company: str | None = None,
    vacancy_text: str | None = None,
    account_id: int,
) -> tuple[str, int | None]:
    """Сменить статус воронки по `vacancy_id` (кнопки расширения «Отметить отклик» / «Оффер»).

    Вакансия должна быть оценена (`/score` её создал); если нет — заводим минимальный stub,
    чтобы клик «Откликнуться» без скоринга не потерялся. `title`/`company` из DOM расширения
    заполняют stub, чтобы карточка на доске не была пустой до следующего скоринга.
    `vacancy_text` — текст JD из DOM (stub создаётся с реальным текстом, чтобы кнопка
    «Сопроводительное» могла сгенерировать письмо без предварительного /score).

    Возвращает (статус, job_id) — job_id нужен расширению для вызова cover-letter API.
    """
    clean = status.strip()
    if clean not in _valid_statuses():
        raise InvalidInput(f"неизвестный статус воронки: {status}")

    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
        if job is None:
            vtext = (vacancy_text or "").strip()
            job = await save_job(
                Job(
                    vacancy_id=vacancy_id,
                    vacancy_text=vtext,
                    url=f"https://hh.ru/vacancy/{vacancy_id}",
                    title=(title or "").strip() or None,
                    company=(company or "").strip() or None,
                    status=clean,
                    source=SOURCE_HH_APPLY_STUB,
                ),
                account_id=account_id,
            )
        elif job.id is not None and job_record_needs_vacancy_text(job):
            # Stub уже существовал (skip_stub / синк hh_negotiations-getmatch без текста) —
            # клик «Откликнуться» на реальной странице несёт свежий текст из DOM, раньше он
            # молча терялся (см. backfill_vacancy_identity). Дозаполняем, если есть что писать.
            vtext = (vacancy_text or "").strip()
            if vtext:
                await backfill_vacancy_identity(
                    job.id,
                    vacancy_text=vtext,
                    title=title,
                    company=company,
                    account_id=account_id,
                )
                job.vacancy_text = vtext
                if title:
                    job.title = title
                if company:
                    job.company = company
        assert job.id is not None
        await update_apply_fields(
            job.id,
            cover_letter_text=cover_letter,
            published_at=published_at,
            account_id=account_id,
        )
        # Архив/разархив HR-треда по «Отказ»/возврату в активную стадию — подписчик pipeline на
        # ApplicationStageChanged (см. core/domains/pipeline/events.py), не здесь: add_stage
        # публикует событие синхронно (publish_and_wait), эффект уже применён к этому моменту.
        await add_stage(job.id, clean, source="api_funnel", account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без PG воронка не работает (источник истины)
        logger.error("Воронка: запись в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    return clean, job.id


async def set_job_stage(
    job_id: int,
    stage: str,
    *,
    source: str = "api_kanban",
    account_id: int,
) -> Job:
    """Сменить стадию вакансии на kanban-доске: история `application_stages` + зеркало статуса.

    `source` — метка канала (web → api_kanban, telegram → telegram_bot, …); см. A-27.
    В отличие от read-витрин не деградирует молча: нет PG → 503, нет вакансии → 404,
    неизвестная стадия → 400 (иначе доска соврёт владельцу про успех).
    """
    clean = stage.strip()
    if clean not in _valid_statuses():
        raise InvalidInput(f"неизвестная стадия воронки: {stage}")

    job = await _require_job(job_id, account_id=account_id)
    try:
        # Архив/разархив HR-треда по «Отказ»/возврату в активную стадию — подписчик pipeline на
        # ApplicationStageChanged (см. core/domains/pipeline/events.py), не здесь: add_stage
        # публикует событие синхронно (publish_and_wait), эффект уже применён к этому моменту.
        await add_stage(job.id or 0, clean, source=source or "api_kanban", account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Kanban: запись стадии в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    job.status = clean
    return job


async def skip_job(job_id: int, reason: str, *, account_id: int) -> Job:
    """Пометить вакансию «Пропущено» с доски.

    Решение «не подавать» ортогонально статусу воронки: `jobs.status` не трогаем, пишем только
    в `skipped_vacancies`.
    """
    job = await _require_job(job_id, account_id=account_id)
    if not job.vacancy_id:
        raise InvalidInput("у вакансии нет vacancy_id — пропуск невозможен")
    try:
        await save_skipped(
            job.vacancy_id,
            reason,
            url=job.url,
            title=job.title,
            company=job.company,
            overall_score=job.overall_score,
            recommendation=job.recommendation,
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Kanban skip: запись пропуска в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    await _archive_threads_best_effort(job.vacancy_id, account_id=account_id)
    return job


async def _archive_threads_best_effort(vacancy_id: str, *, account_id: int) -> None:
    """Пропуск на доске → диалог в архив Чатов (бейджи «напомнить» больше не горят).

    Симметричного вызова на «Отказ» здесь больше нет — `add_stage` публикует
    `ApplicationStageChanged` синхронно, а архив/разархив по нему теперь делает подписчик pipeline
    (`core/domains/pipeline/events.py::on_application_stage_changed`), одним местом для всех
    источников смены стадии, а не только для этого роутера. `skip_job` — отдельный флаг
    (`skipped_vacancies`, не стадия), события не публикует, поэтому здесь остаётся прямой вызов.
    """
    try:
        from core.domains.pipeline.hr_threads import archive_threads_for_vacancy

        await archive_threads_for_vacancy(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — воронка важнее, архив треда best-effort
        logger.warning("Архив тредов после решения по воронке (%s): %s", vacancy_id, exc)


async def unskip_job(job_id: int, *, account_id: int) -> Job:
    """Снять пропуск с доски. Статус воронки не трогаем — его выставит смена стадии."""
    job = await _require_job(job_id, account_id=account_id)
    if not job.vacancy_id:
        return job
    try:
        await delete_skipped(job.vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Kanban unskip: снятие пропуска в Postgres не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    return job


async def update_job_card(
    job_id: int,
    *,
    note: str | None = None,
    applied_at=None,
    letter_required: bool | None = None,
    cover_letter_text: str | None = None,
    work_format: str | None = None,
    account_id: int,
) -> Job:
    """Поля карточки вакансии в вебе: заметка, дата отклика, флаг письма, сопроводительное, формат.

    `None` = не менять (COALESCE в `update_apply_fields`). Возвращает свежую строку.
    """
    job = await _require_job(job_id, account_id=account_id)
    try:
        await update_apply_fields(
            job.id or 0,
            note=note,
            applied_at=applied_at,
            letter_required=letter_required,
            cover_letter_text=cover_letter_text,
            work_format=work_format,
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Карточка вакансии: запись в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    return await get_job(job.id or 0, account_id=account_id) or job


async def set_job_track(job_id: int, track: str, *, account_id: int) -> Job:
    """Ручная поправка трека: побеждает вывод, рескор не перетирает. Затем детерминированный
    пересчёт рубрики без LLM — оси/гейты должны соответствовать выбранному треку."""
    if track not in ("primary", "second_job"):
        raise InvalidInput(f"неизвестный трек: {track}")
    job = await _require_job(job_id, account_id=account_id)
    try:
        updated = await update_job_track(job.id or 0, track, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Трек вакансии: запись в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    if updated is None or not updated.vacancy_id:
        return updated or job
    from core.domains.opportunities.rescore import recompute_job_weights

    recomputed = await recompute_job_weights(updated.vacancy_id, account_id=account_id)
    return recomputed or updated


async def delete_job_card(job_id: int, *, account_id: int) -> Job:
    """Удалить вакансию целиком с доски (JS-1.2: кривая/мусорная карточка — например, дубль или
    сломанный парсинг). Нет вакансии → 404 (`_require_job`); Postgres недоступен → 503. Возвращает
    удалённую строку (роутер берёт из неё vacancy_id для ответа).
    """
    job = await _require_job(job_id, account_id=account_id)
    try:
        await delete_job(job.id or 0, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Удаление вакансии: запись в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    return job


def _valid_statuses() -> frozenset[str]:
    return frozenset(all_funnel_status_values())


async def _require_job(job_id: int, *, account_id: int) -> Job:
    """Строка вакансии для мутаций доски: нет PG → 503, нет вакансии → 404."""
    try:
        job = await get_job(job_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без PG доска не работает (источник истины)
        logger.error("Доска: чтение вакансии из Postgres не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    if job is None or job.id is None:
        raise NotFound(f"вакансия не найдена: {job_id}")
    return job


__all__ = [
    "DiscoveredVacancy",
    "ScoreOutcome",
    "ScoredJob",
    "assess_remote_feasibility",
    "assess_remote_feasibility_safe",
    "delete_job_card",
    "hh_discovery",
    "persist_scored",
    "rescore_from_hr_facts",
    "rescore_from_hr_facts_safe",
    "run_batch_discovery_stream",
    "score_and_persist",
    "score_and_store",
    "score_vacancy",
    "set_funnel_status",
    "set_job_stage",
    "set_job_track",
    "skip_job",
    "unskip_job",
    "update_job_card",
]
