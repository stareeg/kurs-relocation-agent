"""Пересчёт скоринга вакансии по подтверждённым рекрутером фактам (полный авто).

Триггер (новое входящее HR-сообщение / новый исход этапа) зовёт `rescore_from_hr_facts(vacancy_id)`.
Собираем весь HR-контекст по вакансии (переписки + исходы этапов + заметка) → LLM извлекает факты →
если фактов нет или они не изменились (дедуп по хешу) → выходим, LLM на скоринг не тратим. Иначе:
фиксируем baseline (исходный JD-скор отдельной ревизией, один раз) → пересчитываем `score_vacancy`
с фактами как авторитетным override → перезаписываем `jobs.overall_score` (полный авто) + пишем
ревизию hr_confirmed с дельтой и обоснованием. **Воронку и skip НЕ трогаем** — это оценка системы,
не funnel-решение владельца.
"""

from __future__ import annotations

import logging

from core.domains.opportunities.jobs import get_job_by_vacancy_id, update_job_score
from core.domains.opportunities.models import ScoreResult
from core.domains.opportunities.score_revision import (
    ScoreRevisionRecord,
    count_revisions,
    latest_hr_fingerprint,
    save_score_revision,
    update_latest_hr_fingerprint,
)
from core.domains.opportunities.scorer import score_vacancy
from core.domains.pipeline.hr_facts import HRFacts, extract_hr_facts
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)


async def _gather_hr_context(
    vacancy_id: str, *, job_note: str | None, account_id: int, db: Executor
) -> str:
    """Собрать весь HR-контекст по вакансии: переписки (in/out) + исходы этапов + заметку."""
    parts: list[str] = []

    from core.domains.pipeline.hr_threads import list_messages, list_threads_by_vacancy

    for thread in await list_threads_by_vacancy(vacancy_id, account_id=account_id, db=db):
        if thread.id is None:
            continue
        for msg in await list_messages(thread.id, account_id=account_id, db=db):
            # Только реальная переписка с HR; уточняющую болтовню с ассистентом (llm_*) в факты не
            # кормим — это не слова рекрутера.
            if msg.kind not in ("hr_in", "hr_out"):
                continue
            body = (msg.body or "").strip()
            if body:
                who = "HR" if msg.kind == "hr_in" else "Кандидат"
                parts.append(f"[{who}] {body}")

    from core.domains.pipeline.stage_outcome import load_stage_outcome_history

    for outcome in await load_stage_outcome_history(vacancy_id, account_id=account_id, db=db):
        bits: list[str] = []
        if outcome.recruiter_feedback.strip():
            bits.append(outcome.recruiter_feedback.strip())
        if outcome.next_stage_notes.strip():
            bits.append(f"следующий этап: {outcome.next_stage_notes.strip()}")
        if bits:
            parts.append(f"[Исход этапа {outcome.stage}/{outcome.outcome}] " + "; ".join(bits))

    from core.domains.preparation.debrief import load_debrief_history

    for record in await load_debrief_history(vacancy_id, limit=5, account_id=account_id, db=db):
        # Только HR-скрининг: слова HR на звонке — тот же авторитетный источник, что переписка.
        # Техничка/финал сюда не идут — там речь про код/архитектуру, не про условия вакансии.
        if record.stage != "screening":
            continue
        transcript = (record.transcript or "").strip()
        if transcript:
            parts.append(f"[Расшифровка HR-скрининга] {transcript[:4000]}")
        elif (record.summary or "").strip():
            parts.append(f"[Итог HR-скрининга] {record.summary.strip()}")

    note = (job_note or "").strip()
    if note:
        parts.append(f"[Заметка по вакансии] {note}")

    return "\n".join(parts)


def _rationale(facts: HRFacts, prev: int, new: int) -> str:
    bits: list[str] = []
    if facts.salary.strip():
        bits.append(f"зарплата - {facts.salary.strip()}")
    if facts.work_format.strip():
        bits.append(f"формат - {facts.work_format.strip()}")
    if facts.grade.strip():
        bits.append(f"грейд - {facts.grade.strip()}")
    if facts.team.strip():
        bits.append(f"команда - {facts.team.strip()}")
    # delta==0 — факты рекрутера подтвердили тот же скор, а не «пересчитали ничего во что-то же»
    # (запись «X → X» читалась как баг, а не как факт: ничего не изменилось).
    head = (
        f"Пересчёт по фактам рекрутера ({prev} → {new})."
        if new != prev
        else f"Факты рекрутера не изменили скор ({new})."
    )
    return head + (" Учтено: " + "; ".join(bits) if bits else "")


async def rescore_from_hr_facts(
    vacancy_id: str, *, trigger: str = "hr_facts", account_id: int, db: Executor | None = None
) -> ScoreRevisionRecord | None:
    """Пересчитать скор по HR-фактам. None — нечего пересчитывать (нет вакансии/фактов/изменений)."""
    if not vacancy_id:
        return None
    db = db or get_pool()

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    if job is None or not (job.vacancy_text or "").strip():
        return None

    context = await _gather_hr_context(vacancy_id, job_note=job.note, account_id=account_id, db=db)
    if len(context.strip()) < 20:
        return None

    facts = await extract_hr_facts(context, account_id=account_id)
    if not facts.is_meaningful():
        return None

    fingerprint = facts.fingerprint()
    if await latest_hr_fingerprint(vacancy_id, account_id=account_id, db=db) == fingerprint:
        logger.info(
            "HR-пересчёт vacancy_id=%s: факты не изменились (hash=%s) — пропуск",
            vacancy_id,
            fingerprint,
        )
        return None

    # Baseline: исходный JD-скор как ревизия (один раз, до первого hr_confirmed) — чтобы дельта
    # 10 → 62 была видна и ничего не терялось молча.
    if await count_revisions(vacancy_id, account_id=account_id, db=db) == 0:
        await save_score_revision(
            ScoreRevisionRecord(
                vacancy_id=vacancy_id,
                basis="jd_only",
                trigger="baseline",
                overall_score=job.overall_score or 0,
                recommendation=job.recommendation or "",
                rationale="Исходная оценка по тексту вакансии (до HR-фактов).",
            ),
            account_id=account_id,
            db=db,
        )

    prev = job.overall_score or 0
    previous_salary = None
    if isinstance(job.score, dict) and job.score.get("salary"):
        try:
            previous_salary = ScoreResult.model_validate(job.score).salary
        except Exception:  # noqa: BLE001 — битый jsonb → без lock
            previous_salary = None

    new_score = await score_vacancy(
        job.vacancy_text,
        account_id=account_id,
        is_archived=job.is_archived,
        hr_facts=facts,
        vacancy_id=vacancy_id,
        company=job.company,
        salary_text=job.salary_text,
        previous_salary=previous_salary,
    )

    await update_job_score(
        vacancy_id,
        overall_score=new_score.overall_score,
        recommendation=new_score.recommendation,
        score_json=new_score.model_dump(mode="json"),
        salary_json=new_score.salary.model_dump(mode="json"),
        work_city=new_score.work_city or None,
        weights_version=new_score.weights_version or None,
        basis="hr_confirmed",
        account_id=account_id,
        db=db,
    )

    # JS-8.2: названная HR вилка — наблюдение рынка → в корпус калибровки (source='funnel', дедуп
    # по content_hash). Так подтверждённые вилки становятся приорами для будущих оценок сегмента.
    if facts.salary.strip():
        from core.domains.opportunities.salary_corpus import feed_hr_salary_sample_safe

        await feed_hr_salary_sample_safe(
            vacancy_id,
            facts.salary,
            new_score.company_type,
            new_score.grade_match.level,
            account_id=account_id,
            db=db,
        )

    delta = new_score.overall_score - prev
    # Скор не сдвинулся — job уже обновлён, ленту не засоряем; fingerprint всё равно
    # двигаем, иначе следующий триггер снова погонит LLM на тот же скор.
    if delta == 0:
        touched = await update_latest_hr_fingerprint(
            vacancy_id, fingerprint, account_id=account_id, db=db
        )
        if not touched:
            # Первое подтверждение HR при нулевой дельте — одна строка нужна для дедупа.
            return await save_score_revision(
                ScoreRevisionRecord(
                    vacancy_id=vacancy_id,
                    basis="hr_confirmed",
                    trigger=trigger,
                    facts=facts.model_dump(mode="json"),
                    facts_hash=fingerprint,
                    overall_score=new_score.overall_score,
                    recommendation=new_score.recommendation,
                    delta=0,
                    rationale=_rationale(facts, prev, new_score.overall_score),
                ),
                account_id=account_id,
                db=db,
            )
        logger.info(
            "ЗАДАЧА HR-пересчёт vacancy_id=%s: скор без изменений (%d), ревизию не пишем (триггер=%s)",
            vacancy_id,
            prev,
            trigger,
        )
        return None

    revision = await save_score_revision(
        ScoreRevisionRecord(
            vacancy_id=vacancy_id,
            basis="hr_confirmed",
            trigger=trigger,
            facts=facts.model_dump(mode="json"),
            facts_hash=fingerprint,
            overall_score=new_score.overall_score,
            recommendation=new_score.recommendation,
            delta=delta,
            rationale=_rationale(facts, prev, new_score.overall_score),
        ),
        account_id=account_id,
        db=db,
    )
    logger.info(
        "ЗАДАЧА HR-пересчёт vacancy_id=%s: %d → %d (триггер=%s)",
        vacancy_id,
        prev,
        new_score.overall_score,
        trigger,
    )
    return revision


async def rescore_from_hr_facts_safe(
    vacancy_id: str, *, trigger: str = "hr_facts", account_id: int, db: Executor | None = None
) -> None:
    """Best-effort обёртка для фоновых триггеров: глушит исключения (пересчёт не должен валить ввод)."""
    try:
        await rescore_from_hr_facts(vacancy_id, trigger=trigger, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort, не роняем запрос ввода
        logger.warning("HR-пересчёт vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


__all__ = ["rescore_from_hr_facts", "rescore_from_hr_facts_safe"]
