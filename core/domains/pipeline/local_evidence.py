"""Локальные факты активного процесса (запланированный этап / живая переписка с HR).

Вынесено из `negotiations.py::_has_active_local_evidence` (фикс инцидента «ТехВилл»,
2026-08-12, commit `9675db7`) в общее место, раз тот же провал контекста нашёлся ещё в
`archive_disposition.py` (план `local_context_blind_spots_2026_08_12.md` §2): LLM-классификатор
судит по куцему контексту (бейдж hh.ru / переписка без учёта `interview_stages`), а факт
запланированной встречи или живой переписки уже лежит в Postgres и должен блокировать сам
вызов LLM, а не подсказывать ему правильный ответ."""

from __future__ import annotations

from core.platform.db.pool import Executor


async def has_scheduled_interview_stage(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Есть ли по вакансии ещё не прошедший/не отменённый (`status='scheduled'`) этап собеса."""
    if not vacancy_id:
        return False

    from core.domains.preparation.interview_stages import load_stages

    stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    return any(s.status == "scheduled" for s in stages)


async def has_hr_thread_activity(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Есть ли реальная переписка (`hr_in`/`hr_out`) в основном треде вакансии — LLM-чат
    (`llm_user`/`llm_assistant`) сам по себе не считается доказательством живого процесса с HR."""
    if not vacancy_id:
        return False

    from core.domains.pipeline.hr_threads import get_primary_thread, list_messages

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None:
        return False
    messages = await list_messages(thread.id, account_id=account_id, db=db)
    return any(m.kind in ("hr_in", "hr_out") for m in messages)


async def has_active_local_evidence(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Запланированный этап ИЛИ живая переписка — оба факта LLM-классификаторы в этом домене
    (hh.ru-синк override, ручная классификация архива) видят не полностью и потому должны
    вообще не спрашиваться, если хотя бы один из них уже есть в базе."""
    if await has_scheduled_interview_stage(vacancy_id, account_id=account_id, db=db):
        return True
    return await has_hr_thread_activity(vacancy_id, account_id=account_id, db=db)


__all__ = [
    "has_active_local_evidence",
    "has_hr_thread_activity",
    "has_scheduled_interview_stage",
]
