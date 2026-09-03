"""Синхронизация откликов hh.ru → стадии воронки на Postgres.

без SQLite/funnel_cache/sheets_batch: текущий статус
читается из Postgres (`jobs.status`), запись стадии — через `add_stage` (мастер истории —
`application_stages`). Таксономия HH→воронка — из `core.domains.offers.hh_negotiations`
(порт в core, S8); LLM-резолв неоднозначных статусов — `core.domains.pipeline.funnel_status_llm`
(только OpenRouter, без БД).

Источник истины — Postgres (единственный, зеркало воронки удалено).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from core.config import CoreSettings, get_settings
from core.domains.offers.hh_negotiations import (
    HhNegotiationStatus,
    NegotiationMapResult,
    NegotiationPreviewItem,
    NegotiationsPreviewResponse,
    NegotiationSyncItem,
    NegotiationSyncResultItem,
    SyncNegotiationsProgressEvent,
    SyncNegotiationsResponse,
    is_negotiation_discrepancy,
    is_stale_interaction,
    map_hh_to_funnel,
    normalize_hh_status,
    should_apply_funnel_update,
)
from core.domains.opportunities.jobs import (
    SOURCE_GETMATCH,
    SOURCE_HABR,
    SOURCE_HH_NEGOTIATIONS,
    Job,
    add_stage,
    archive_stale_jobs,
    get_jobs_by_vacancy_ids,
    is_manual_rejection_source,
    job_record_needs_vacancy_text,
    latest_rejection_source,
    mark_resume_viewed,
    purge_empty_unscored_jobs,
    save_job,
)
from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status
from core.platform.db.pool import Executor
from core.platform.observability import event

logger = logging.getLogger(__name__)


def _negotiation_job_source(vacancy_id: str) -> str:
    """GM-5.1/S13: площадочные отклики пишем с source соответствующей площадки."""
    if str(vacancy_id).startswith("gm_"):
        return SOURCE_GETMATCH
    if str(vacancy_id).startswith("habr_"):
        return SOURCE_HABR
    return SOURCE_HH_NEGOTIATIONS


def _canon(status: str | None) -> str | None:
    """Канонический FunnelStatus или None для пустого."""
    if not status or not str(status).strip():
        return None
    return resolve_funnel_status(status) or str(status).strip()


async def _mark_viewed_if_needed(
    job: Job | None,
    item: NegotiationSyncItem,
    mapped: NegotiationMapResult,
    *,
    dry_run: bool,
    account_id: int,
) -> None:
    """Записать `hr_viewed_at`, если известно, что работодатель открыл резюме — независимо от того,
    двигается ли стадия воронки (просмотр резюме != скрининг).

    `mapped.employer_viewed` — вывод из `hh_status` (достоверен для hh: invitation/interview/viewed →
    True). Если он None (статус сам по себе не сообщает факт просмотра — `rejected`/`unknown`),
    берём `item.employer_viewed`, который клиент детектит напрямую из metaStatus площадки
    (getmatch/habr). Это чинит кейс «отказ на getmatch/habr не ставил `hr_viewed_at`»: `rejected`
    в `map_hh_to_funnel` затирал просмотр в None, хотя клиент явно сообщал его в payload.
    hh при этом не регрессирует: его `item.employer_viewed` — boolean только от `VIEWED_BY_EMPLOYER`,
    но для invitation/interview `mapped.employer_viewed` уже True, и None-фолбэк не срабатывает."""
    viewed = mapped.employer_viewed if mapped.employer_viewed is not None else item.employer_viewed
    if dry_run or not viewed or job is None or job.id is None:
        return
    await mark_resume_viewed(job.id, account_id=account_id)


async def _has_active_local_evidence(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Реальные локальные признаки идущего процесса: запланированный этап собеса или живая
    переписка с HR в «Чатах» (`hr_messages`).

    HH-синк видит только бейдж на странице «Мои отклики» — `item.last_message` заполняет
    расширение из того же бейджа, а не из наших сохранённых тредов. Из-за этого LLM-разбор
    расхождения (см. ниже) однажды заключил «нет активной переписки или этапов» и понизил
    вакансию с назначенным звонком (запись в interview_stages + импортированный дамп hr_messages)
    в «Отказ» — это же тянуло за собой авто-архив диалога в «Чатах» (`_archive_threads_best_effort`).
    Если у нас в системе уже есть встреча/переписка, устаревший HH-бейдж не может её отменить —
    override даже не спрашивается.

    Реализация вынесена в `local_evidence.py` — та же проверка нужна ещё в
    `archive_disposition.py` (план `local_context_blind_spots_2026_08_12.md` §2)."""
    from core.domains.pipeline.local_evidence import has_active_local_evidence

    return await has_active_local_evidence(vacancy_id, account_id=account_id, db=db)


def _resolve_rules(item: NegotiationSyncItem) -> tuple[HhNegotiationStatus, NegotiationMapResult]:
    hh = item.hh_status or normalize_hh_status(
        item.hh_status_raw, employer_state_id=item.employer_state_id
    )
    mapped = map_hh_to_funnel(hh, has_hr_message=bool((item.last_message or "").strip()))
    return hh, mapped


async def _resolve_item(
    item: NegotiationSyncItem,
    current: str | None,
    *,
    use_llm: bool,
    settings: CoreSettings,
) -> tuple[HhNegotiationStatus, NegotiationMapResult, bool]:
    """Правила + (опционально) LLM при неоднозначном HH-статусе."""
    hh, mapped = _resolve_rules(item)
    llm_used = False

    need_llm = use_llm and (hh == HhNegotiationStatus.UNKNOWN or not mapped.funnel_status)
    if need_llm and settings.openrouter_api_key:
        try:
            from core.domains.pipeline.funnel_status_llm import resolve_funnel_status_llm

            status, _reason = await resolve_funnel_status_llm(
                hh_status_raw=item.hh_status_raw,
                company=item.company,
                title=item.title,
                last_message=item.last_message,
                current_status=current,
                vacancy_id=item.vacancy_id,
            )
            mapped = NegotiationMapResult(
                funnel_status=status,
                needs_interview_tracking=mapped.needs_interview_tracking
                or status in (FunnelStatus.SCREENING, FunnelStatus.TECH, FunnelStatus.FINAL),
                employer_viewed=mapped.employer_viewed,
            )
            llm_used = True
        except Exception as exc:  # noqa: BLE001 — LLM best-effort, остаёмся на правилах
            logger.warning("LLM resolve funnel_status %s: %s", item.vacancy_id, exc)

    return hh, mapped, llm_used


def _pg_unavailable_result(item: NegotiationSyncItem, exc: Exception) -> NegotiationSyncResultItem:
    logger.error("negotiations: Postgres недоступен (%s): %s", item.vacancy_id, exc)
    hh, mapped = _resolve_rules(item)
    return NegotiationSyncResultItem(
        vacancy_id=item.vacancy_id,
        hh_status=hh.value,
        funnel_status=mapped.funnel_status,
        applied=False,
        skipped=True,
        reason=f"Postgres недоступен: {exc}",
    )


async def _sync_one(
    item: NegotiationSyncItem,
    *,
    dry_run: bool,
    use_llm: bool,
    force: bool,
    settings: CoreSettings,
    job: Job | None,
    account_id: int,
) -> NegotiationSyncResultItem:
    """Один отклик: HH-статус → стадия воронки (Postgres).

    `job` — уже найденная (или отсутствующая) вакансия: L-32 убрал `get_job_by_vacancy_id`
    в цикле — вызывающий батчит поиск разом через `get_jobs_by_vacancy_ids`.
    """
    current = job.status if job else None
    current_canon = _canon(current)
    # «Отказ», проставленный владельцем, — не тот «Отказ», который авто-синк площадки вправе
    # откатить: если владелец сам увёл вакансию в «Отказ», «Приглашение»/«Собеседование» на hh.ru
    # для неё — устаревший бейдж, а не факт возобновления (инцидент «Толк», vacancy 89).
    # Проверяем историю стадий точечно, только когда текущий статус действительно «Отказ»,
    # чтобы не платить лишним запросом на каждый отклик в цикле синка.
    current_is_manual_rejection = False
    if current_canon == FunnelStatus.REJECTED and job is not None and job.id is not None:
        try:
            reject_source = await latest_rejection_source(job.id, account_id=account_id, db=None)
            current_is_manual_rejection = is_manual_rejection_source(reject_source)
        except Exception as exc:  # noqa: BLE001 — история best-effort, guard не валим
            logger.warning(
                "negotiations: история «Отказ» недоступна (%s): %s", item.vacancy_id, exc
            )
    hh, mapped, llm_used = await _resolve_item(item, current, use_llm=use_llm, settings=settings)
    proposed = mapped.funnel_status
    if is_stale_interaction(item.applied_at or (job.applied_at if job else None)):
        proposed = FunnelStatus.REJECTED.value
        mapped = NegotiationMapResult(
            funnel_status=proposed, employer_viewed=mapped.employer_viewed
        )
        llm_used = False
    proposed_canon = _canon(proposed) or proposed
    discrepancy = is_negotiation_discrepancy(current, proposed)
    guard_ok = should_apply_funnel_update(
        current,
        proposed,
        hh_status=hh,
        force=force,
        current_is_manual_rejection=current_is_manual_rejection,
    )
    guard_note = ""
    if current_is_manual_rejection and current_canon == FunnelStatus.REJECTED:
        guard_note = " (владелец сам увёл вакансию в «Отказ» — авто-синк не воскрешает)"

    if (
        not guard_ok
        and discrepancy
        and not llm_used
        and use_llm
        and settings.openrouter_api_key
        and not current_is_manual_rejection
    ):
        # EX-8: раньше guard молча блокировал понижение и ждал ручного force-клика «Применить» —
        # копилось как «спорный случай» без разбора. Теперь для реального расхождения зовём LLM с
        # полным контекстом (сообщение HR + текущий статус) вместо бесконечного requires-a-click:
        # либо LLM подтверждает защиту (осознанное решение, не тупик), либо явно решает, что
        # понижение легитимно (HR правда откатил процесс, а не устаревший бейдж HH).
        #
        # Но если у нас САМИХ уже есть надёжный локальный факт активного процесса
        # (`_has_active_local_evidence`) — не спрашиваем LLM вовсе: он видит только куцый бейдж
        # HH (`item.last_message` — из того же бейджа расширения, не из полного треда), и один раз
        # уже сделал вывод «нет переписки/этапов» ровно тогда, когда назначенная встреча и импорт
        # переписки уже лежали в базе (job 317, «ТехВилл» 2026-08-11 — ложный «Отказ», следом
        # утянувший диалог в архив «Чатов» через `_archive_threads_best_effort`). Календарная
        # встреча и сохранённая переписка — не то, что стоит отдавать на усмотрение LLM с неполным
        # контекстом.
        if await _has_active_local_evidence(item.vacancy_id, account_id=account_id):
            guard_note = " (есть запланированный этап или переписка с HR — LLM не спрашивали)"
        else:
            try:
                from core.domains.pipeline.funnel_status_llm import resolve_funnel_status_llm

                llm_status, llm_reason = await resolve_funnel_status_llm(
                    hh_status_raw=item.hh_status_raw,
                    company=item.company,
                    title=item.title,
                    last_message=item.last_message,
                    current_status=current,
                    vacancy_id=item.vacancy_id,
                    extra_context=(
                        f"Правило синхронизации предлагает понизить статус с «{current}» на "
                        f"«{proposed}», но защита воронки блокирует автоматическое понижение. "
                        "Реши: это легитимный откат (HR действительно отказал/остановил процесс) "
                        "или устаревший статус HH, который не должен затирать более продвинутый "
                        "прогресс."
                    ),
                )
                llm_used = True
                llm_canon = _canon(llm_status) or llm_status
                if llm_canon != current_canon:
                    proposed = llm_status
                    proposed_canon = llm_canon
                    discrepancy = is_negotiation_discrepancy(current, proposed)
                    guard_ok = True
                    guard_note = f" (LLM: {llm_reason})" if llm_reason else " (LLM решил применить)"
                else:
                    guard_note = (
                        f" (LLM подтвердил: {llm_reason})"
                        if llm_reason
                        else " (LLM подтвердил защиту)"
                    )
            except Exception as exc:  # noqa: BLE001 — LLM best-effort, остаёмся на решении guard
                logger.warning("LLM guard-override %s: %s", item.vacancy_id, exc)

    common: dict[str, Any] = dict(
        vacancy_id=item.vacancy_id,
        hh_status=hh.value,
        funnel_status=proposed,
        needs_interview_tracking=mapped.needs_interview_tracking,
        llm_used=llm_used,
    )

    if not guard_ok:
        # §16 local_context_blind_spots_2026_08_12: раньше эта ветка не логировала вообще ничего —
        # причина блокировки уходила только в HTTP-ответ (разовый тост фронта, нигде не сохраняется).
        # Баг «ТехВилл» (job 317) нельзя было продиагностировать без прямого SSH+psql к проду именно
        # из-за этого — добавляем ту же строку, что уже есть для применённых изменений (add_stage
        # ниже публикует ApplicationStageChanged), но на симметричной ветке «не применено».
        event(
            logger,
            "ЗАДАЧА",
            "negotiations: заблокировано %s → %s%s",
            current or "—",
            proposed,
            guard_note,
            vacancy_id=item.vacancy_id,
            current=current,
            proposed=proposed,
            reason=guard_note,
        )
        await _mark_viewed_if_needed(job, item, mapped, dry_run=dry_run, account_id=account_id)
        return NegotiationSyncResultItem(
            **common,
            current_status=current,
            is_discrepancy=discrepancy,
            applied=False,
            skipped=True,
            reason=f"защита воронки: оставлен «{current or '—'}»{guard_note}",
        )

    if proposed_canon == current_canon and not force:
        await _mark_viewed_if_needed(job, item, mapped, dry_run=dry_run, account_id=account_id)
        return NegotiationSyncResultItem(
            **common,
            current_status=current,
            is_discrepancy=False,
            applied=False,
            skipped=True,
            reason=f"без изменений: уже «{current}»",
        )

    if dry_run:
        return NegotiationSyncResultItem(
            **common,
            current_status=current,
            is_discrepancy=discrepancy,
            applied=True,
            skipped=False,
            reason="dry_run",
        )

    # --- Postgres: источник истины ---
    url_key = (item.url or f"https://hh.ru/vacancy/{item.vacancy_id}").split("?")[0]
    try:
        if job is None or job.id is None:
            job = await save_job(
                Job(
                    vacancy_id=item.vacancy_id,
                    vacancy_text="",
                    url=url_key,
                    company=item.company or None,
                    title=item.title or None,
                    source=_negotiation_job_source(item.vacancy_id),
                ),
                account_id=account_id,
            )
        assert job.id is not None
        # Архив/разархив HR-треда по «Отказ»/возврату в активную стадию — подписчик pipeline на
        # ApplicationStageChanged (см. events.py::on_application_stage_changed), не здесь:
        # add_stage публикует событие синхронно (publish_and_wait), эффект уже применён.
        await add_stage(
            job.id,
            proposed_canon,
            source=_negotiation_job_source(item.vacancy_id),
            applied_at=item.applied_at,
            account_id=account_id,
        )
        await _mark_viewed_if_needed(job, item, mapped, dry_run=dry_run, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — запись стадии не удалась → пропускаем item
        logger.error("negotiations add_stage %s: %s", item.vacancy_id, exc)
        return NegotiationSyncResultItem(
            **common,
            current_status=current,
            is_discrepancy=discrepancy,
            applied=False,
            skipped=True,
            reason=f"Postgres: {exc}",
        )

    return NegotiationSyncResultItem(
        **common,
        current_status=proposed_canon,
        is_discrepancy=False,
        applied=True,
        skipped=False,
        db_updated=1,
    )


async def preview_negotiations(
    items: list[NegotiationSyncItem],
    *,
    account_id: int,
) -> NegotiationsPreviewResponse:
    """Текущий (Postgres) vs предлагаемый статус для списка откликов (без записи)."""
    settings = get_settings()
    vids = [item.vacancy_id for item in items if item.vacancy_id]
    try:
        jobs_by_vid = await get_jobs_by_vacancy_ids(vids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → текущий статус неизвестен, не 500
        logger.debug("negotiations preview: Postgres недоступен: %s", exc)
        jobs_by_vid = {}
    # Лёгкий фолбэк статусов, если батч jobs упал частично — не нужен: один запрос.

    previews: list[NegotiationPreviewItem] = []
    for item in items:
        job = jobs_by_vid.get(item.vacancy_id)
        current = job.status if job else None
        hh, mapped, _ = await _resolve_item(item, current, use_llm=False, settings=settings)
        proposed = mapped.funnel_status
        if is_stale_interaction(item.applied_at):
            proposed = FunnelStatus.REJECTED.value
        previews.append(
            NegotiationPreviewItem(
                vacancy_id=item.vacancy_id,
                funnel_status_proposed=proposed,
                current_status=current,
                is_discrepancy=is_negotiation_discrepancy(current, proposed),
                hh_status=hh.value,
                needs_vacancy_text=bool(job and job_record_needs_vacancy_text(job)),
            )
        )
    return NegotiationsPreviewResponse(items=previews)


async def _purge_empty_stubs_best_effort() -> None:
    try:
        purged_n = await purge_empty_unscored_jobs(db=None)
        if purged_n:
            logger.info("negotiations: удалены пустые stub'ы без скора: %d", purged_n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("negotiations: purge пустых stub'ов не выполнен: %s", exc)


def _summarize(results: list[NegotiationSyncResultItem]) -> tuple[int, int]:
    synced = sum(1 for r in results if r.applied and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    return synced, skipped


async def sync_negotiations_batch(
    items: list[NegotiationSyncItem],
    *,
    dry_run: bool = False,
    use_llm: bool = True,
    force: bool = False,
    account_id: int,
) -> SyncNegotiationsResponse:
    """Применить статусы из hh.ru/negotiations → Postgres."""
    if not items:
        return SyncNegotiationsResponse(results=[], synced_count=0, skipped_count=0)

    settings = get_settings()
    if not dry_run:
        try:
            archived_n = await archive_stale_jobs(db=None)
            if archived_n:
                logger.info("negotiations: авто-архив %d устаревших вакансий", archived_n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("negotiations: авто-архив не выполнен: %s", exc)
        await _purge_empty_stubs_best_effort()

    results: list[NegotiationSyncResultItem] = []
    try:
        jobs_by_vid = await get_jobs_by_vacancy_ids(
            [item.vacancy_id for item in items], account_id=account_id
        )
    except Exception as exc:  # noqa: BLE001 — без PG синхронизировать нечего (источник истины)
        results.extend(_pg_unavailable_result(item, exc) for item in items)
    else:
        for item in items:
            results.append(
                await _sync_one(
                    item,
                    dry_run=dry_run,
                    use_llm=use_llm,
                    force=force,
                    settings=settings,
                    job=jobs_by_vid.get(item.vacancy_id),
                    account_id=account_id,
                )
            )

    # S3: отметим свежесть getmatch-синка, если в пакете был хотя бы один применённый gm_*-айтем.
    # Лучше делать после успешной записи хотя бы одной стадии — меньше шума от пустых прогонов.
    if not dry_run and any(
        r.applied and not r.skipped and str(r.vacancy_id).startswith("gm_") for r in results
    ):
        try:
            from core.domains.opportunities.getmatch_sync import mark_getmatch_sync

            await mark_getmatch_sync()
        except Exception as exc:  # noqa: BLE001 — best-effort, синк уже отработал
            logger.debug("getmatch_sync_freshness: не отмечен: %s", exc)

    synced, skipped = _summarize(results)
    event(
        logger,
        "ЗАДАЧА",
        "negotiations: синхронизировано %d, пропущено %d из %d",
        synced,
        skipped,
        len(items),
        total=len(items),
        synced=synced,
        skipped=skipped,
    )
    return SyncNegotiationsResponse(
        results=results,
        synced_count=synced,
        skipped_count=skipped,
    )


def _progress_event(**kwargs: Any) -> dict[str, Any]:
    return SyncNegotiationsProgressEvent(**kwargs).model_dump(mode="json")


async def sync_negotiations_batch_stream(
    items: list[NegotiationSyncItem],
    *,
    dry_run: bool = False,
    use_llm: bool = True,
    force: bool = False,
    account_id: int,
) -> AsyncIterator[dict[str, Any]]:
    """Стрим прогресса синхронизации (payload'ы для SSE A-14; UI расширения слушает кадры)."""
    total = len(items)
    if not total:
        yield _progress_event(
            type="complete",
            total=0,
            done=0,
            message="Нет откликов для синхронизации",
            response=SyncNegotiationsResponse(results=[], synced_count=0, skipped_count=0),
        )
        return

    yield _progress_event(type="start", total=total, message="Синхронизация откликов…")

    settings = get_settings()
    if not dry_run:
        try:
            archived_n = await archive_stale_jobs(db=None)
            if archived_n:
                yield _progress_event(
                    type="progress",
                    done=0,
                    total=total,
                    message=f"Авто-архив: {archived_n} устаревших вакансий",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("negotiations stream: авто-архив не выполнен: %s", exc)
        await _purge_empty_stubs_best_effort()

    results: list[NegotiationSyncResultItem] = []
    synced_n = 0
    skipped_n = 0

    jobs_by_vid: dict[str, Job] | None
    stream_pg_exc: Exception | None
    try:
        jobs_by_vid = await get_jobs_by_vacancy_ids(
            [item.vacancy_id for item in items], account_id=account_id
        )
        stream_pg_exc = None
    except Exception as exc:  # noqa: BLE001 — без PG синхронизировать нечего (источник истины)
        jobs_by_vid = None
        stream_pg_exc = exc

    for idx, item in enumerate(items):
        if jobs_by_vid is None:
            # stream_pg_exc задан в except выше; assert сужает тип для pyright
            assert stream_pg_exc is not None
            result = _pg_unavailable_result(item, stream_pg_exc)
        else:
            result = await _sync_one(
                item,
                dry_run=dry_run,
                use_llm=use_llm,
                force=force,
                settings=settings,
                job=jobs_by_vid.get(item.vacancy_id),
                account_id=account_id,
            )
        results.append(result)
        if result.applied and not result.skipped:
            synced_n += 1
        else:
            skipped_n += 1

        label = item.company or item.vacancy_id
        yield _progress_event(
            type="progress",
            done=idx + 1,
            total=total,
            synced=synced_n,
            skipped=skipped_n,
            vacancy_id=item.vacancy_id,
            message=f"{label}: {result.funnel_status or result.reason or '—'}",
            result=result,
        )

    synced, skipped = _summarize(results)
    msg = f"Готово: обновлено {synced}, пропущено {skipped}"
    event(
        logger,
        "ЗАДАЧА",
        "negotiations stream: синхронизировано %d, пропущено %d из %d",
        synced,
        skipped,
        total,
        total=total,
        synced=synced,
        skipped=skipped,
    )

    # S3: отметим свежесть getmatch-синка, если в стриме был применённый gm_*-айтем.
    if not dry_run and any(
        r.applied and not r.skipped and str(r.vacancy_id).startswith("gm_") for r in results
    ):
        try:
            from core.domains.opportunities.getmatch_sync import mark_getmatch_sync

            await mark_getmatch_sync()
        except Exception as exc:  # noqa: BLE001 — best-effort, синк уже отработал
            logger.debug("getmatch_sync_freshness: не отмечен (stream): %s", exc)

    yield _progress_event(
        type="complete",
        done=total,
        total=total,
        synced=synced,
        skipped=skipped,
        message=msg,
        response=SyncNegotiationsResponse(
            results=results,
            synced_count=synced,
            skipped_count=skipped,
        ),
    )
