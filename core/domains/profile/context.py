"""Сборщик контекста аналитики для усиления резюме (JS-resume-strengthen-v2).

Стало: strengthen/audit получают не только исходный текст блока, но и срез рынка:
- top missing концепты из gap-отчёта (востребованы, но не упомянуты)
- weak bullets (без цифр и без глагола действия)
- срез воронки поиска (есть ли отклики/скрининги — сигнал, работает ли резюме)
- top-N релевантных вакансий из jobs (по overall_score) — под них точечно точим блок

Каждый блок best-effort: нет PG → кусок пропускается, пайплайн не падает (как gap.py).
Возвращает единый текстовый «Context» блок, который инжектируется в user-промпт.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config import get_settings
from core.domains.profile.gap import ResumeGapReport, WeakBullet, build_gap_report
from core.domains.profile.model import ResumeData, _salary_range_md

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StrengthenContext:
    """Готовый к инъекции в промпт контекст аналитики."""

    text: str
    # Карта исходных объектов на случай, если вызывающему нужно знать, было ли что-то.
    has_gap: bool
    has_funnel: bool
    has_top_vacancies: bool
    # Био-материал резюме (для rewrite-режима): должность, навыки, опыт коротко.
    # Пустая строка = структурированного резюме нет (тогда rewrite-режим не запустим).
    bio_material: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.has_gap or self.has_funnel or self.has_top_vacancies or self.bio_material)


def _format_missing(report: ResumeGapReport, limit: int = 15) -> str:
    """Top missing концептов с demand_pct — подсветка, где рынок требует, а резюме не упоминает."""
    if not report.available:
        return ""
    missing = report.missing[:limit]
    if not missing:
        return "Все востребованные концепты покрыты — gap по спросу не найден.\n"
    lines = [f"- {m.name} — {m.demand_pct:g}% вакансий требуют" for m in missing]
    return (
        "Востребовано рынком, но НЕ упомянуто в текущем резюме "
        f"(топ-{len(missing)} по спросу, корпус {report.corpus_size} вакансий):\n"
        + "\n".join(lines)
        + "\n"
    )


def _format_weak_bullets(weak: list[WeakBullet], limit: int = 12) -> str:
    if not weak:
        return "Слабых буллетов (без цифры и без глагола действия) автоматика не нашла.\n"
    rows = weak[:limit]
    lines = [f"- [{w.ref}] «{w.text}»" for w in rows]
    return (
        f"Слабые буллеты (без цифры/метрики и без глагола действия, топ-{len(rows)}):\n"
        + "\n".join(lines)
        + "\n"
    )


def _format_funnel(metrics: object | None) -> str:
    """Срез воронки поиска — сигнал, работает ли резюме на рынке."""
    if metrics is None:
        return ""
    try:
        available = bool(getattr(metrics, "available", False))
    except Exception:  # noqa: BLE001
        return ""
    if not available:
        return ""
    total = int(getattr(metrics, "total_jobs", 0) or 0)
    funnel = getattr(metrics, "funnel", None)
    applied = int(getattr(funnel, "applied", 0) or 0) if funnel is not None else 0
    responded = int(getattr(funnel, "responded", 0) or 0) if funnel is not None else 0
    interviewing = int(getattr(funnel, "interviewing", 0) or 0) if funnel is not None else 0
    skipped = int(getattr(metrics, "skipped_total", 0) or 0)
    return (
        "Срез воронки поиска (по jobs в PG):\n"
        f"- Всего вакансий в базе: {total}\n"
        f"- Откликов: {applied}, ответов HR: {responded}, на интервью: {interviewing}\n"
        f"- Пропущено (skip): {skipped}\n"
    )


def _format_top_vacancies(jobs: list, limit: int) -> str:
    """Top-N релевантных вакансий — под них точечно точим блок."""
    if not jobs:
        return ""
    rows = jobs[:limit]
    lines: list[str] = []
    for j in rows:
        title = (getattr(j, "title", None) or "").strip() or "?"
        company = (getattr(j, "company", None) or "").strip() or "?"
        score = getattr(j, "overall_score", None)
        score_str = f" (скор {int(score)})" if isinstance(score, (int, float)) else ""
        text = (getattr(j, "vacancy_text", None) or "").strip()
        snippet = ""
        if text:
            # 600 символов достаточно, чтобы вытащить ключевые требования; не тащим весь текст.
            snippet = text[:600].replace("\n", " ")
            if len(text) > 600:
                snippet += "…"
        lines.append(f"- {title} · {company}{score_str}: {snippet}")
    return (
        f"Топ-{len(rows)} релевантных вакансий из базы (под них точим блок):\n"
        + "\n".join(lines)
        + "\n"
    )


async def _gather_top_vacancies(limit: int, *, account_id: int) -> list:
    if limit <= 0:
        return []
    try:
        from core.domains.opportunities.jobs import list_jobs

        # Без пропущенных: калибруем под вакансии, которые ещё рассматриваем.
        return await list_jobs(limit=limit, exclude_skipped=True, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без вакансий, не падаем
        logger.debug("strengthen context: top-vacancies недоступны: %s", exc)
        return []


async def _gather_search_metrics(*, account_id: int) -> object | None:
    try:
        from core.domains.market.search_metrics import get_search_metrics

        return await get_search_metrics(account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без воронки, не падаем
        logger.debug("strengthen context: search-metrics недоступны: %s", exc)
        return None


def gather_bio_material(data: ResumeData) -> str:
    """Био-материал резюме аккаунта запроса для rewrite-режима (с нуля, без исходного текста
    блока).

    Фактический источник правды для LLM: должность + категории + зарплатная вилка,
    ключевые навыки (ATS-якоря) и краткая выжимка опыта (компания/должность/период/описание).
    Якоря биографии для rewrite/ats-fit; доработки под рынок — в промптах усиления.
    """
    parts: list[str] = []

    pos = data.position
    if pos.title:
        parts.append(f"Желаемая должность: {pos.title}")
    if pos.categories:
        parts.append(f"Категории: {', '.join(pos.categories)}")
    salary_range = _salary_range_md(pos)
    if salary_range:
        parts.append(f"Зарплатная вилка (как указано в резюме): {salary_range}")
    if pos.schedule:
        parts.append(f"График: {', '.join(pos.schedule)}")

    skills = [s for s in (data.key_skills or []) if s.strip()]
    if skills:
        parts.append("Ключевые навыки (ATS-якоря, до 30): " + ", ".join(skills))

    exps = data.experience or []
    if exps:
        parts.append("Опыт работы (компания · должность · период · описание):")
        for e in exps:
            period = ""
            if e.start or e.end or e.current:
                end = "по н.в." if e.current else (e.end or "")
                period = f" · {e.start or '?'}-{end}" if (e.start or end) else ""
            head = f"- {e.company or '?'} · {e.position or '?'}{period}"
            desc = (e.description or "").strip()
            if desc:
                # Ограничиваем 400 символами на место — длинные описания раздуют промпт,
                # для «Обо мне» важны ключевые тезисы, не полные буллеты.
                snippet = desc[:400].replace("\n", " ")
                if len(desc) > 400:
                    snippet += "…"
                head += f": {snippet}"
            parts.append(head)

    return "\n".join(parts).strip()


async def build_strengthen_context(
    *,
    account_id: int,
    report: ResumeGapReport | None = None,
    data: ResumeData | None = None,
    db: object | None = None,
) -> StrengthenContext:
    """Собрать единый контекстный блок для user-промпта усиления/аудита аккаунта запроса.

    `report` — готовый gap-отчёт (если уже посчитан, не дублируем). Иначе считаем здесь
    (best-effort PG). Каждый кусок независимо деградирует при отсутствии PG/данных.
    """
    settings = get_settings()
    if report is None:
        try:
            report = await build_gap_report(account_id=account_id, db=db)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.debug("strengthen context: gap-отчёт недоступен: %s", exc)
            report = None

    if data is None:
        from core.domains.profile.structured_store import read_resume_data_for_account

        data = await read_resume_data_for_account(account_id, db=db)  # type: ignore[arg-type]

    has_gap = report is not None and report.available
    weak: list[WeakBullet] = report.score.weak_bullets if (report and report.score) else []

    top_n = int(getattr(settings, "resume_strengthen_top_vacancies", 5) or 0)
    top_jobs = await _gather_top_vacancies(top_n, account_id=account_id) if top_n > 0 else []
    metrics = await _gather_search_metrics(account_id=account_id)

    from core.domains.profile.strengthen_quality import format_enhancement_directive

    parts: list[str] = [format_enhancement_directive(data) + "\n"]
    if report is not None:
        parts.append(_format_missing(report))
        parts.append(_format_weak_bullets(weak))
    funnel_text = _format_funnel(metrics)
    if funnel_text:
        parts.append(funnel_text)
    vac_text = _format_top_vacancies(top_jobs, top_n)
    if vac_text:
        parts.append(vac_text)

    text = "\n".join(p for p in parts if p).strip()
    bio = gather_bio_material(data)
    return StrengthenContext(
        text=text,
        has_gap=has_gap,
        has_funnel=bool(funnel_text),
        has_top_vacancies=bool(top_jobs),
        bio_material=bio,
    )


__all__ = ["StrengthenContext", "build_strengthen_context", "gather_bio_material"]
