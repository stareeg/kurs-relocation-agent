"""Персистентность этапов собеседований per vacancy_id (Postgres, `interview_stages`).

Только хранение: LLM-разбор этапов живёт в `core.domains.pipeline`. Связку enrichment+stages
для Q&A даёт `load_bundle`. Digest «HR давно молчит» (`load_stale_hr_contacts`) — в
`core.domains.opportunities.enrichment`, рядом со своей таблицей.

Аккаунт-изоляция (миграция 0100_interview_stages_account_id.sql):
`account_id` — обязательный keyword-параметр каждой функции, явный `WHERE`/insert-колонка (тот
же приём, что `core.domains.opportunities.jobs` — не `account_scope()`-обёртка, т.к. вызывающая
сторона обычно уже держит `account_id` из `AccountContext`/бота, а не отдельное соединение).
Без него `vacancy_id` не был уникален даже в пределах одного аккаунта (несколько этапов на
вакансию) и тем более не гарантирует уникальности МЕЖДУ аккаунтами — два человека, трекающих одну
и ту же публичную hh-вакансию, до этой миграции писали бы в одни и те же строки.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.domains.opportunities.enrichment import VacancyEnrichment, load_enrichment
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLUMNS = (
    "id, vacancy_id, stage_type, scheduled_at, format, status, position, notes, "
    "source_message_id, created_at"
)


class InterviewStage(BaseModel):
    """Этап собеседования. Допустимые значения enum-полей валидирует CHECK в миграциях 0006/0044:

    stage_type: hr_screening | live_coding | system_design | theory | soft_skills | manager |
                business_case | final (два последних добавлены RD-19 под форматы Техничек)
    format:     online | offline | unknown
    status:     scheduled | completed | cancelled | rescheduled

    position — ручной порядок в цепочке этапов вакансии (степпер веба), независим от
    scheduled_at (этап без назначенной даты всё равно занимает место в цепочке).

    source_message_id — реплика hr_messages, из которой этап извлёк LLM; None — этап
    заведён руками. Только для проверяемости в UI, на матчинг/статусы не влияет.
    """

    id: int | None = None
    vacancy_id: str = ""
    stage_type: str = "hr_screening"
    scheduled_at: datetime | None = None
    format: str = "unknown"
    status: str = "scheduled"
    position: int = 0
    notes: str = ""
    source_message_id: int | None = None
    created_at: datetime | None = None


class EnrichmentBundle(BaseModel):
    """Enrichment от HR + этапы собеседований одной вакансии (порт VacancyEnrichmentBundle)."""

    enrichment: VacancyEnrichment | None = None
    stages: list[InterviewStage] = []


async def save_stage(
    stage: InterviewStage, *, account_id: int, db: Executor | None = None
) -> InterviewStage:
    """Upsert этапа: при заданном id — UPDATE, иначе INSERT. Возвращает строку с id/created_at.

    UPDATE не трогает vacancy_id/created_at (иммутабельны после создания). Новый
    этап без явной `position` (степпер веба) уезжает в конец цепочки вакансии.

    Инвариант: у вакансии не больше одного `hr_screening` — повторный INSERT сливается в
    существующую строку (HR-парсер / ensure / ручное «+» не плодят дубликаты в шапке дровера).
    """
    db = db or get_pool()
    if stage.id:
        row = await db.fetchrow(
            f"""
            update interview_stages set
                stage_type = $3, scheduled_at = $4, format = $5, status = $6,
                position = $7, notes = $8, source_message_id = $9
            where id = $1 and account_id = $2
            returning {_COLUMNS}
            """,
            stage.id,
            account_id,
            stage.stage_type,
            stage.scheduled_at,
            stage.format,
            stage.status,
            stage.position,
            stage.notes,
            stage.source_message_id,
        )
        if row is None:
            raise ValueError(f"interview_stage id={stage.id} не найден для обновления")
        return InterviewStage(**row_to_dict(row))

    if not stage.vacancy_id:
        raise ValueError("vacancy_id required для нового этапа")

    if stage.stage_type == "hr_screening":
        existing = await db.fetchrow(
            f"select {_COLUMNS} from interview_stages "
            f"where vacancy_id = $1 and account_id = $2 and stage_type = 'hr_screening' "
            f"order by position asc, id asc limit 1",
            stage.vacancy_id,
            account_id,
        )
        if existing is not None:
            cur = InterviewStage(**row_to_dict(existing))
            from core.domains.preparation.interview.timing import is_past_datetime

            # Мерджим только в ЕЩЁ ОТКРЫТЫЙ скрининг (переносится/уточняется дата ТОГО ЖЕ звонка).
            # Если существующий hr_screening уже пройден/резолвлен (completed/failed/cancelled,
            # либо его scheduled_at уже в прошлом), новый безымянный "hr_screening" — почти
            # наверняка НЕ тот же звонок, а следующий этап, для которого вызывающая сторона не
            # распознала формат (см. event_extract._upsert_stage: дефолт на неясности). Слияние
            # тогда затирало бы дату реального скрининга датой следующего этапа и вешало на него
            # бейдж «HR-скрининг» вместо честной отдельной строки (инцидент «МТС, Топ
            # менеджмент», 2026-08-12) — даём завестись отдельным этапом ниже.
            cur_still_open = cur.status in ("scheduled", "rescheduled") and (
                cur.scheduled_at is None or not is_past_datetime(cur.scheduled_at)
            )
            if cur_still_open:
                # Не откатываем уже пройденный скрининг в scheduled из повторного парса HR.
                merged_status = cur.status
                if cur.status in ("scheduled", "rescheduled") and stage.status:
                    merged_status = stage.status
                elif stage.status == "completed":
                    merged_status = "completed"
                return await save_stage(
                    cur.model_copy(
                        update={
                            "scheduled_at": stage.scheduled_at or cur.scheduled_at,
                            "format": stage.format if stage.format != "unknown" else cur.format,
                            "status": merged_status,
                            "notes": stage.notes or cur.notes,
                            "source_message_id": stage.source_message_id or cur.source_message_id,
                        }
                    ),
                    account_id=account_id,
                    db=db,
                )

    row = await db.fetchrow(
        f"""
        insert into interview_stages (
            account_id, vacancy_id, stage_type, scheduled_at, format, status, position, notes,
            source_message_id, created_at
        ) values (
            $1, $2, $3, $4, $5, $6,
            coalesce($7, (
                select coalesce(max(position) + 1, 0) from interview_stages
                where vacancy_id = $2 and account_id = $1
            )),
            $8, $9, coalesce($10, now())
        )
        returning {_COLUMNS}
        """,
        account_id,
        stage.vacancy_id,
        stage.stage_type,
        stage.scheduled_at,
        stage.format,
        stage.status,
        stage.position or None,
        stage.notes,
        stage.source_message_id,
        stage.created_at,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return InterviewStage(**row_to_dict(row))


async def load_stages(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> list[InterviewStage]:
    """Этапы вакансии по порядку цепочки (`position`, перетаскиваемый в UI).

    Побочный эффект: схлопывает лишние `hr_screening` (оставляет один) — чинит уже накопленные
    дубликаты в дровере без отдельной миграции.
    """
    if not vacancy_id:
        return []
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLUMNS} from interview_stages where vacancy_id = $1 and account_id = $2 "
        f"order by position asc, scheduled_at asc nulls last, id asc",
        vacancy_id,
        account_id,
    )
    stages = [InterviewStage(**row_to_dict(r)) for r in rows]
    return await _collapse_duplicate_hr_screenings(stages, account_id=account_id, db=db)


_HR_STATUS_RANK = {
    "completed": 0,
    "failed": 1,
    "scheduled": 2,
    "rescheduled": 2,
    "cancelled": 3,
}


def _prefer_hr_screening(hrs: list[InterviewStage]) -> InterviewStage:
    return min(
        hrs,
        key=lambda s: (
            _HR_STATUS_RANK.get(s.status, 9),
            s.position,
            s.id or 0,
        ),
    )


async def _collapse_duplicate_hr_screenings(
    stages: list[InterviewStage],
    *,
    account_id: int,
    db: Executor,
) -> list[InterviewStage]:
    hrs = [s for s in stages if s.stage_type == "hr_screening" and s.id is not None]
    if len(hrs) <= 1:
        return stages
    keep = _prefer_hr_screening(hrs)
    for s in hrs:
        if s.id is not None and s.id != keep.id:
            await delete_stage(s.id, account_id=account_id, db=db)
    return [s for s in stages if s.stage_type != "hr_screening" or s.id == keep.id]


async def delete_stage(stage_id: int, *, account_id: int, db: Executor | None = None) -> None:
    """Убрать этап из цепочки (этого формата у этой компании нет — не размазывать усилия)."""
    db = db or get_pool()
    await db.execute(
        "delete from interview_stages where id = $1 and account_id = $2", stage_id, account_id
    )


async def reorder_stages(
    vacancy_id: str, ordered_ids: list[int], *, account_id: int, db: Executor | None = None
) -> list[InterviewStage]:
    """Переставить порядок цепочки: `ordered_ids` — id этапов вакансии в новом порядке.

    Пишет `position` = индекс в списке. Этапы вне списка (гонка с параллельным добавлением) не
    трогает — их `position` просто уедет в хвост следующей загрузкой.
    """
    db = db or get_pool()
    for idx, stage_id in enumerate(ordered_ids):
        await db.execute(
            "update interview_stages set position = $2 "
            "where id = $1 and vacancy_id = $3 and account_id = $4",
            stage_id,
            idx,
            vacancy_id,
            account_id,
        )
    return await load_stages(vacancy_id, account_id=account_id, db=db)


async def complete_stage_by_id(
    stage_id: int, *, account_id: int, db: Executor | None = None
) -> InterviewStage | None:
    """Пометить конкретный этап цепочки пройденным (UX2-9: разбор явно привязан к этой строке
    цепочки — точнее, чем угадывание по типу/дате; DBR-1: единственный путь авто-прогресса)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from interview_stages where id = $1 and account_id = $2",
        stage_id,
        account_id,
    )
    if row is None:
        return None
    stage = InterviewStage(**row_to_dict(row))
    return await save_stage(
        stage.model_copy(update={"status": "completed"}), account_id=account_id, db=db
    )


async def ensure_hr_screening_completed(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> None:
    """Переход воронки в «Техничка» ⇒ скрининг уже позади.

    Открытые `hr_screening` → `completed`; если строки нет — создать пройденную в начале цепочки
    (чтобы в дровере сразу был зелёный кружок, без ручной отметки в Техничках).
    """
    if not vacancy_id:
        return
    db = db or get_pool()
    stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    screenings = [s for s in stages if s.stage_type == "hr_screening"]
    if screenings:
        for s in screenings:
            if s.id is not None and s.status in ("scheduled", "rescheduled"):
                await complete_stage_by_id(s.id, account_id=account_id, db=db)
        return

    await db.execute(
        "update interview_stages set position = position + 1 "
        "where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    await db.execute(
        "insert into interview_stages ("
        "  account_id, vacancy_id, stage_type, format, status, position, notes, created_at"
        ") values ($1, $2, 'hr_screening', 'unknown', 'completed', 0, '', now())",
        account_id,
        vacancy_id,
    )


async def ensure_hr_screening_stage_open(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> None:
    """Переход воронки в «Скрининг» ⇒ в цепочке должна появиться сама строка HR-скрининга —
    открытой, не пройденной. Раньше первая строка «HR-скрининг» заводилась только задним числом,
    когда вакансия уже проезжала МИМО скрининга (`ensure_hr_screening_completed`, переход в
    Техничку/Финал/Оффер) — дровер на самом «Скрининге» стоял с пустой цепочкой.

    Уже есть hr_screening (в любом статусе — открыт, пройден, отменён) → не трогаем: это уже
    чья-то реальная строка, а не место для второй с тем же типом.
    """
    if not vacancy_id:
        return
    db = db or get_pool()
    stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    if any(s.stage_type == "hr_screening" for s in stages):
        return

    await db.execute(
        "update interview_stages set position = position + 1 "
        "where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    await db.execute(
        "insert into interview_stages ("
        "  account_id, vacancy_id, stage_type, format, status, position, notes, created_at"
        ") values ($1, $2, 'hr_screening', 'unknown', 'scheduled', 0, '', now())",
        account_id,
        vacancy_id,
    )


async def complete_past_stages(*, db: Executor | None = None) -> int:
    """Довести просроченные `scheduled`-этапы до `completed` без ручного вмешательства.

    Ничего не решает LLM — дата уже прошла, гадать не нужно, чистый детерминированный UPDATE
    (plans/local_context_blind_spots_2026_08_12.md §8). Раньше это происходило только «на лету»
    при следующей записи этапа (`stage_status_from_datetime`); этап, который никто не трогал
    после даты, навсегда оставался `scheduled` и витрины вида `next_stage_at`
    (`hr_threads.py::_THREAD_SELECT`) показывали прошедшую встречу как предстоящую.

    Без `account_id` — системная фоновая чистка по всем аккаунтам сразу, тот же паттерн, что
    `jobs.py::archive_stale_jobs`.
    """
    db = db or get_pool()
    result = await db.execute(
        "update interview_stages set status = 'completed' "
        "where status = 'scheduled' and scheduled_at is not null and scheduled_at < now()"
    )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def fail_stage(
    stage_id: int, *, account_id: int, db: Executor | None = None
) -> InterviewStage | None:
    """Пометить этап явно не пройденным (подтверждённый перепиской отказ по этому этапу).

    Отдельный статус от `cancelled` (этап убрали из цепочки руками, к исходу собеса отношения не
    имеет) — `failed` виден в UI отдельным акцентом (core.interview.debrief_resolution).
    """
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from interview_stages where id = $1 and account_id = $2",
        stage_id,
        account_id,
    )
    if row is None:
        return None
    stage = InterviewStage(**row_to_dict(row))
    return await save_stage(
        stage.model_copy(update={"status": "failed"}), account_id=account_id, db=db
    )


async def load_upcoming_stages(
    days: int = 30, *, account_id: int, db: Executor | None = None
) -> list[InterviewStage]:
    """Назначенные собеседы в ближайшие N дней (digest «собеседы скоро»)."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLUMNS} from interview_stages "
        f"where account_id = $2 and scheduled_at is not null and status = 'scheduled' "
        f"and scheduled_at >= now() and scheduled_at <= now() + make_interval(days => $1) "
        f"order by scheduled_at asc",
        days,
        account_id,
    )
    return [InterviewStage(**row_to_dict(r)) for r in rows]


async def load_bundle(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> EnrichmentBundle:
    """Enrichment + этапы одной вакансии (контекст Q&A). PG — источник истины."""
    db = db or get_pool()
    enrichment = await load_enrichment(vacancy_id, account_id=account_id, db=db)
    return EnrichmentBundle(
        enrichment=enrichment,
        stages=await load_stages(vacancy_id, account_id=account_id, db=db),
    )


def stages_from_parser(
    vacancy_id: str,
    stages_in: list,
    *,
    fallback_dt: datetime | None,
    fallback_type: str,
    fallback_format: str,
) -> list[InterviewStage]:
    """LLM-этапы (`InterviewStageIn`) + fallback single stage → list[InterviewStage].

    Чистая логика без БД (): статус
    этапа считается по дате (`stage_status_from_datetime`). Результат пишет `save_stage`.
    """
    from core.domains.preparation.interview.timing import stage_status_from_datetime

    out: list[InterviewStage] = []
    for item in stages_in:
        out.append(
            InterviewStage(
                vacancy_id=vacancy_id,
                stage_type=item.stage_type,
                scheduled_at=item.scheduled_at,
                format=item.format,
                status=stage_status_from_datetime(item.scheduled_at, item.status),
                notes=item.notes,
            )
        )
    if not out and fallback_dt and vacancy_id:
        out.append(
            InterviewStage(
                vacancy_id=vacancy_id,
                stage_type=fallback_type,
                scheduled_at=fallback_dt,
                format=fallback_format,
                status=stage_status_from_datetime(fallback_dt, "scheduled"),
            )
        )
    return out
