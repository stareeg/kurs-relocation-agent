"""Оркестрация действий по результату анализа HR-сообщения (порт `bot.services.hr_actions`, S11).

Backend-free: воронка/enrichment/этапы/офферы пишутся в Postgres через `core.repo.*` (единственный
источник истины — зеркало воронки удалено, Google Calendar снесён в DR-2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.domains.opportunities.enrichment import merge_enrichment
from core.domains.opportunities.jobs import SOURCE_HR_THREAD_STUB
from core.domains.pipeline.hr_context import enrich_analysis_from_text
from core.domains.pipeline.hr_vacancy_resolve import (
    ensure_engaged_funnel_status,
    resolve_hr_vacancy,
)
from core.domains.pipeline.models import HrMessageAnalysis
from core.domains.pipeline.vacancy_links import listing_url_for_vacancy_id
from core.domains.preparation.interview_stages import InterviewStage, save_stage, stages_from_parser
from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    funnel_status: str = ""
    pg_updated: int = 0
    enrichment_saved: bool = False
    stages_saved: int = 0
    notes: list[str] = field(default_factory=list)
    # vacancy_id, который НЕ применён из-за низкого confidence — для кнопки подтверждения.
    pending_resolve_vacancy_id: str = ""
    # Этапы для prep-напоминаний — планирует канал (bot) через prep_reminders + chat_id.
    prep_reminder_stages: list = field(default_factory=list)


async def _sync_funnel(analysis: HrMessageAnalysis, status: str, *, account_id: int) -> bool:
    """Сменить статус воронки в Postgres (единственный источник истины, повторяет `POST /funnel`)."""
    if not analysis.vacancy_id:
        return False
    from core.domains.opportunities.jobs import Job, add_stage, get_job_by_vacancy_id, save_job

    try:
        job = await get_job_by_vacancy_id(analysis.vacancy_id, account_id=account_id)
        if job is None:
            job = await save_job(
                Job(
                    vacancy_id=analysis.vacancy_id,
                    vacancy_text="",
                    url=analysis.vacancy_url or listing_url_for_vacancy_id(analysis.vacancy_id),
                    status=status,
                    source=SOURCE_HR_THREAD_STUB,
                ),
                account_id=account_id,
            )
        assert job.id is not None
        await add_stage(job.id, status, source="hr_actions", account_id=account_id)
        if status == FunnelStatus.REJECTED.value and job.vacancy_id:
            await _archive_threads_best_effort(job.vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без PG воронка не пишется, но действие не валим
        logger.error("HR funnel: запись в Postgres не удалась: %s", exc)
        return False

    return True


async def _archive_threads_best_effort(vacancy_id: str, *, account_id: int) -> None:
    """Отказ по HR-сообщению → диалог в архив Чатов (иначе бейдж «Чаты» врёт, см. negotiations.py)."""
    try:
        from core.domains.pipeline.hr_threads import archive_threads_for_vacancy

        await archive_threads_for_vacancy(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — воронка важнее, архив треда best-effort
        logger.warning("Архив тредов после HR-отказа (%s): %s", vacancy_id, exc)


async def _save_enrichment(analysis: HrMessageAnalysis, *, account_id: int) -> bool:
    if not analysis.vacancy_id:
        return False
    try:
        await merge_enrichment(
            analysis.vacancy_id,
            salary_hr_range=analysis.salary_hr_range or analysis.salary_text,
            salary_match=analysis.salary_match,
            format_clarified=analysis.format_clarified,
            team_size=analysis.team_size,
            hr_contact_summary=analysis.summary,
            interview_debrief=analysis.debrief_summary,
            hr_link=analysis.hr_link,
            contact_at=analysis.parsed_at,
            account_id=account_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — enrichment best-effort
        logger.error("Enrichment merge error: %s", exc)
        return False


async def _persist_stages(
    analysis: HrMessageAnalysis,
    result: ActionResult,
    *,
    account_id: int,
) -> list[InterviewStage]:
    if not analysis.vacancy_id:
        return []

    stages = stages_from_parser(
        analysis.vacancy_id,
        analysis.interview_stages,
        fallback_dt=analysis.interview_dt,
        fallback_type=analysis.stage_type or "hr_screening",
        fallback_format=analysis.format,
    )
    if not stages:
        return []

    saved: list[InterviewStage] = []
    for stage in stages:
        try:
            saved_stage = await save_stage(stage, account_id=account_id)
            saved.append(saved_stage)
            result.stages_saved += 1
        except Exception as exc:  # noqa: BLE001 — одна стадия не валит остальные
            logger.error("Save stage error: %s", exc)

    return saved


async def _handle_offer_intent(
    analysis: HrMessageAnalysis, result: ActionResult, *, account_id: int
) -> None:
    """intent='offer' → core offer-parser + сохранение в core.repo.offers (merge)."""
    if not analysis.vacancy_id:
        result.notes.append("Оффер: vacancy_id не определён — пропускаю авто-парс")
        return
    try:
        from core.domains.offers.offer_parser import parse_offer_text
        from core.domains.offers.store import Offer, load_offer, upsert_offer

        existing = await load_offer(analysis.vacancy_id, account_id=account_id)
        parsed = await parse_offer_text(
            analysis.raw_text,
            vacancy_id=analysis.vacancy_id,
            fallback_company=analysis.company or "",
            fallback_position=analysis.position or "",
        )
        merged = await upsert_offer(
            Offer.model_validate(parsed.model_dump()), account_id=account_id, merge=True
        )
        if existing is None:
            result.notes.append(f"Оффер: распарсил новый ({merged.company or '?'})")
        else:
            result.notes.append("Оффер: обновлены поля из новой переписки")
        if merged.deadline:
            # Дедлайн-напоминания (24ч/2ч) — в S12 вместе с offers-хендлером и шедулером.
            result.notes.append("Оффер: дедлайн зафиксирован (напоминания подключатся в S12)")
    except Exception as exc:  # noqa: BLE001 — парсинг оффера best-effort
        logger.error("HR offer parse failed: %s", exc)
        result.notes.append(f"Оффер: ошибка парсинга ({exc})")


async def apply_hr_actions(
    analysis: HrMessageAnalysis, telegram_msg_id: int, *, account_id: int
) -> ActionResult:
    """Выполняет воронку/enrichment/этапы/Calendar/оффер в зависимости от intent (Postgres)."""
    result = ActionResult()
    analysis = enrich_analysis_from_text(analysis)
    analysis = await resolve_hr_vacancy(analysis, account_id=account_id)

    canonical_status = resolve_funnel_status(analysis.funnel_status, analysis.intent)
    if canonical_status:
        analysis = analysis.model_copy(update={"funnel_status": canonical_status})
    analysis = ensure_engaged_funnel_status(analysis)

    is_rejection = analysis.intent == "rejection" or analysis.funnel_status == FunnelStatus.REJECTED

    # Слабая привязка (эвристика по компании) — не трогаем воронку по vacancy_id, просим
    # подтверждения кнопкой. Enrichment по vacancy_id безвреден, но и его отвяжем для чистоты.
    low_confidence = (
        bool(analysis.vacancy_id)
        and analysis.resolve_confidence < 0.7
        and analysis.resolve_via == "company_search"
    )
    if low_confidence:
        result.notes.append(
            f"⚠ Привязка к вакансии {analysis.vacancy_id} не подтверждена "
            f"(эвристика по компании). Подтвердите кнопкой ниже или укажите id явно."
        )
        confirmation_vid = analysis.vacancy_id
        analysis = analysis.model_copy(update={"vacancy_id": "", "vacancy_url": ""})
        result.pending_resolve_vacancy_id = confirmation_vid

    if analysis.vacancy_id:
        result.enrichment_saved = await _save_enrichment(analysis, account_id=account_id)
        if result.enrichment_saved:
            parts = []
            if analysis.salary_hr_range or analysis.salary_text:
                parts.append("ЗП от HR")
            if analysis.format_clarified:
                parts.append("формат")
            if analysis.team_size:
                parts.append("команда")
            if analysis.debrief_summary:
                parts.append("дебриф")
            label = ", ".join(parts) if parts else "контакт HR"
            result.notes.append(f"Enrichment: сохранено ({label})")

    if analysis.should_update_funnel or is_rejection:
        status = FunnelStatus.REJECTED if is_rejection else analysis.funnel_status
        result.funnel_status = status
        if analysis.vacancy_id:
            if await _sync_funnel(analysis, status, account_id=account_id):
                result.pg_updated = 1
                result.notes.append(f"Воронка: «{status}» (id {analysis.vacancy_id})")
        else:
            # Лид без vacancy_id (HR написал по вакансии вне воронки) — привязать некуда, статус
            # не проставляем, только просим уточнить компанию/ссылку.
            if not is_rejection and analysis.company in ("", "Неизвестная компания"):
                result.notes.append("Воронка: укажите компанию или ссылку hh для привязки")
            else:
                result.notes.append("Воронка: HR-лид без vacancy_id — привязка не найдена")

    saved_stages = await _persist_stages(analysis, result, account_id=account_id)
    if analysis.is_interview_event and saved_stages:
        result.prep_reminder_stages = list(saved_stages)

    if analysis.intent == "offer":
        await _handle_offer_intent(analysis, result, account_id=account_id)

    return result
