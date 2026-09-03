"""Сборка контекста вакансии для Q&A.

Bundle enrichment/этапов — модели домена поверх Postgres (источник истины).
"""

from __future__ import annotations

from core.domains.offers.models import OfferRecord
from core.domains.preparation.interview_stages import EnrichmentBundle
from core.domains.preparation.models import ScoreResult, VacancyRecord

# Подписи типов этапов собеседований ().
STAGE_TYPE_LABELS: dict[str, str] = {
    "hr_screening": "HR-скрининг",
    "live_coding": "Live coding",
    "system_design": "System design",
    "theory": "Теория",
    "soft_skills": "Soft skills",
    "manager": "Менеджер",
}

RECOMMENDATION_LABELS = {
    "strong_apply": "ПОДАТЬ ОБЯЗАТЕЛЬНО",
    "apply": "ПОДАТЬ",
    "maybe": "СОМНЕНИЕ",
    "skip": "ПРОПУСТИТЬ",
}

MAX_VACANCY_TEXT_CHARS = 14_000


def truncate_vacancy_text(text: str, limit: int = MAX_VACANCY_TEXT_CHARS) -> str:
    """Ужать текст вакансии через общий бюджет блоков, не локальным срезом."""
    from core.platform.llm.budget import InputBlock, fit_blocks

    return fit_blocks(
        [InputBlock(kind="vacancy", text=text, required=True)],
        max_chars=limit,
        ellipsis="\n\n[…текст обрезан]",
    ).text


def build_score_summary(score: ScoreResult | None) -> str:
    if score is None:
        return "Оценка LLM недоступна — опирайся на текст вакансии и резюме кандидата."

    s = score
    niches = (
        ", ".join(s.role_content_match.matched_niche) if s.role_content_match.matched_niche else "—"
    )
    pros = "; ".join(s.pros[:5])
    cons = "; ".join(s.cons[:5])
    flags = "; ".join(s.red_flags[:5]) if s.red_flags else "—"

    return f"""Итоговая оценка: {s.overall_score}/100 — {RECOMMENDATION_LABELS.get(s.recommendation, s.recommendation)}
Вердикт: {s.one_line_verdict}
Грейд: {s.grade_match.level} ({s.grade_match.reasoning})
Зарплата: {s.salary.value_or_range or "не указана"}; meets_min={s.salary.meets_min}; note: {s.salary.note}
Remote: {s.remote_abroad_compat.level} — {s.remote_abroad_compat.reasoning}
Ниша (score {s.role_content_match.score}): {niches}
Управление: {s.burnout_risk.level}
Тип компании: {s.company_type}
Плюсы: {pros}
Минусы: {cons}
Красные флаги: {flags}"""


def build_enrichment_block(bundle: EnrichmentBundle | None) -> str:
    if bundle is None or (bundle.enrichment is None and not bundle.stages):
        return ""

    lines = ["--- Данные от HR (enrichment) ---"]
    e = bundle.enrichment
    if e:
        if e.salary_hr_range:
            match = e.salary_match or "не оценено"
            lines.append(f"ЗП от HR: {e.salary_hr_range} (match: {match})")
        if e.format_clarified:
            lines.append(f"Формат работы (уточнено HR): {e.format_clarified}")
        if e.team_size:
            lines.append(f"Размер команды: {e.team_size}")
        if e.hr_contact_summary:
            lines.append(f"Последнее от HR: {e.hr_contact_summary}")
        if e.interview_debrief:
            lines.append(f"Дебриф после собеса:\n{e.interview_debrief[:4000]}")
        if e.last_hr_contact_at:
            lines.append(f"Контакт HR: {e.last_hr_contact_at.strftime('%d.%m.%Y %H:%M')}")

    if bundle.stages:
        lines.append("Этапы собеседований:")
        for stage in bundle.stages:
            label = STAGE_TYPE_LABELS.get(stage.stage_type, stage.stage_type)
            when = (
                stage.scheduled_at.strftime("%d.%m.%Y %H:%M")
                if stage.scheduled_at
                else "дата не назначена"
            )
            fmt = stage.format if stage.format != "unknown" else "—"
            lines.append(f"- {label}: {when}, формат {fmt}, статус {stage.status}")
            if stage.notes:
                lines.append(f"  заметки: {stage.notes}")

    return "\n".join(lines)


def _format_offer_line(offer: OfferRecord) -> str:
    period = "мес" if offer.base_salary_period == "month" else "год"
    amount = (
        f"{offer.base_salary:,}".replace(",", " ") + f" {offer.base_salary_currency}/{period}"
        if offer.base_salary
        else "сумма не указана"
    )
    office_note = ""
    if offer.work_format == "hybrid" and offer.office_days_per_week is not None:
        office_note = f", {offer.office_days_per_week} дн. в офисе"
    deadline_note = (
        f", ответить нужно до {offer.deadline.strftime('%d.%m.%Y')}" if offer.deadline else ""
    )
    return (
        f"{offer.company or 'компания не указана'} ({offer.position or 'должность не указана'}): "
        f"{amount}, формат {offer.work_format}{office_note}, статус {offer.status}{deadline_note}"
    )


def build_offer_block(offers: list[OfferRecord]) -> str:
    """Факт «у кандидата уже есть оффер(ы) в руках» — рычаг/контекст для чата и HR-черновиков по
    ЛЮБОЙ вакансии, включая ДРУГИЕ (OF-14, пример: оффер по одной вакансии как рычаг давления по
    срокам в переговорах по другой). Пусто, если активных офферов нет (draft/declined/expired —
    решённое прошлое, не рычаг).
    """
    active = [o for o in offers if o.status in ("thinking", "accepted")]
    if not active:
        return ""
    lines = [
        "У кандидата уже есть оффер(ы) в руках (факт/рычаг для контекста, не решение кандидата):"
    ]
    lines.extend(f"- {_format_offer_line(o)}" for o in active)
    return "\n".join(lines)


def build_vacancy_context_block(
    record: VacancyRecord,
    bundle: EnrichmentBundle | None = None,
    offers: list[OfferRecord] | None = None,
) -> str:
    lines = [
        f"Компания: {record.company or 'не указана'}",
        f"Должность: {record.title or 'не указана'}",
        f"Зарплата (HH): {record.salary_text or 'не указана'}",
    ]
    if record.status:
        lines.append(f"Статус воронки: {record.status}")
    if record.url:
        lines.append(f"URL: {record.url}")

    offer_block = build_offer_block(offers or [])
    if offer_block:
        lines.append("")
        lines.append(offer_block)

    lines.append("")
    lines.append("--- Оценка LLM ---")
    lines.append(build_score_summary(record.score))

    enrichment = build_enrichment_block(bundle)
    if enrichment:
        lines.append("")
        lines.append(enrichment)

    lines.append("")
    lines.append("--- Текст вакансии ---")
    lines.append(truncate_vacancy_text(record.vacancy_text))
    return "\n".join(lines)


def build_first_user_message(
    record: VacancyRecord,
    question: str,
    bundle: EnrichmentBundle | None = None,
) -> str:
    return (
        f"{build_vacancy_context_block(record, bundle)}\n\n"
        f"--- Вопрос кандидата ---\n"
        f"{question.strip()}"
    )
