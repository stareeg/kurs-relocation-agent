"""Готовность левой панели критериев для балла резюме и ATS-подгонки.

Без заполненных осей поиска (роль, рынок, ниши, грейд/вилка, формат) балл резюме
даёт ложную картину — модель и эвристики не знают, под что оценивать релевантность.

`score_criteria_alignment` — детерминированная доля в `role_fit` (15%): совпадает ли текст
резюме с осями из левой панели.
"""

from __future__ import annotations

import re

from core.domains.profile.model import ResumeData, market_scope_label

# Стабильные ключи обязательных полей левой панели — зеркалятся на фронте.
# `market_segment` намеренно не входит: пустая строка = «Любые» (без фильтра по отрасли).
LEFT_PANEL_GAP_KEYS: tuple[str, ...] = (
    "role_kind",
    "niches",
    "grade_or_salary",
    "schedule",
)

LEFT_PANEL_HINTS: dict[str, str] = {
    "role_kind": "Укажите тип роли — «делаю руками» или «управляю людьми»",
    "niches": "Добавьте хотя бы одну нишу в приоритетах",
    "grade_or_salary": "Укажите целевой грейд или зарплатную вилку",
    "schedule": "Выберите формат работы — офис, гибрид или удалёнка",
}

# Доля LLM/эвристики и осей поиска в итоговом role_fit.
ROLE_FIT_PRIMARY_WEIGHT = 0.85
ROLE_FIT_CRITERIA_WEIGHT = 0.15

CRITERIA_ALIGNMENT_HINTS: dict[str, str] = {
    "title": "Желаемая должность слабо читается в тексте — добавьте формулировку в «Обо мне»",
    "niches": "Приоритеты поиска не видны в резюме — вплетите ниши в «Обо мне» и буллеты",
    "grade": "Целевой грейд не отражён в должностях или «Обо мне»",
    "role_kind": "Тип роли (руками/люди) не бьётся с описанием опыта",
    "market_segment": "Рынок/отрасль из критериев не прослеживается в тексте",
    "skills_depth": "Мало ключевых навыков под целевую роль — доберите до 5+",
}

_MGMT_MARKERS = (
    "руковод",
    "управл",
    "менедж",
    "lead",
    "head",
    "директор",
    "team lead",
    "people",
)
_IC_MARKERS = (
    "разработ",
    "инжен",
    "engineer",
    "architect",
    "аналит",
    "implement",
    "программ",
)


def left_panel_gaps(data: ResumeData) -> list[str]:
    """Ключи незаполненных полей левой панели (порядок стабилен для UI)."""
    gaps: list[str] = []
    sc = data.search_criteria
    pos = data.position
    if not (sc.role_kind or "").strip():
        gaps.append("role_kind")
    if not [n for n in (sc.niches or []) if n.strip()]:
        gaps.append("niches")
    if not pos.grade and not pos.salary_min and not pos.salary_comfortable:
        gaps.append("grade_or_salary")
    if not [s for s in (pos.schedule or []) if s.strip()]:
        gaps.append("schedule")
    return gaps


def left_panel_ready_for_score(data: ResumeData) -> bool:
    return not left_panel_gaps(data)


def left_panel_hints(data: ResumeData) -> list[str]:
    return [LEFT_PANEL_HINTS[k] for k in left_panel_gaps(data) if k in LEFT_PANEL_HINTS]


def _title_words(title: str) -> list[str]:
    return [w for w in re.findall(r"\w+", title, flags=re.UNICODE) if len(w) > 2]


def criteria_alignment_checks(data: ResumeData, resume_text: str) -> list[tuple[str, bool]]:
    """Чек-лист согласованности текста резюме с осями левой панели."""
    text_cf = (resume_text or "").casefold()
    sc = data.search_criteria
    pos = data.position
    checks: list[tuple[str, bool]] = []

    title = (pos.title or "").strip()
    if title:
        words = _title_words(title)
        if words:
            hits = sum(1 for w in words if w.casefold() in text_cf)
            checks.append(("title", hits >= max(1, (len(words) + 1) // 2)))
        else:
            checks.append(("title", title.casefold() in text_cf))
    else:
        checks.append(("title", False))

    niches = [n.strip() for n in (sc.niches or []) if n.strip()]
    if niches:
        niche_hit = any(n.casefold() in text_cf for n in niches)
        if not niche_hit:
            niche_hit = any(
                part.strip().casefold() in text_cf
                for n in niches
                for part in re.split(r"[/,]", n)
                if len(part.strip()) > 2
            )
        checks.append(("niches", niche_hit))
    else:
        checks.append(("niches", False))

    grades = [g.strip() for g in (pos.grade or []) if g.strip()]
    if grades:
        checks.append(("grade", any(g.casefold() in text_cf for g in grades)))
    else:
        checks.append(("grade", bool(pos.salary_min or pos.salary_comfortable)))

    rk = (sc.role_kind or "").strip().casefold()
    if "управ" in rk or "management" in rk:
        checks.append(("role_kind", any(m in text_cf for m in _MGMT_MARKERS)))
    elif "руками" in rk or "hands" in rk:
        has_ic = any(m in text_cf for m in _IC_MARKERS)
        checks.append(("role_kind", has_ic or not any(m in text_cf for m in _MGMT_MARKERS)))
    elif rk:
        checks.append(("role_kind", True))
    else:
        checks.append(("role_kind", False))

    seg = (sc.market_segment or "").strip()
    if seg:
        parts = [p.strip() for p in seg.split(",") if p.strip()]
        checks.append(("market_segment", any(p.casefold() in text_cf for p in parts)))
    else:
        # «Любые» — фильтр по отрасли не задан, не штрафуем alignment.
        checks.append(("market_segment", True))

    skill_count = len([s for s in data.key_skills if s.strip()])
    checks.append(("skills_depth", skill_count >= 5))

    return checks


def score_criteria_alignment(data: ResumeData, resume_text: str) -> int:
    """0-100: насколько текст резюме согласован с критериями левой панели."""
    checks = criteria_alignment_checks(data, resume_text)
    if not checks:
        return 0
    return round(100 * sum(1 for _, ok in checks if ok) / len(checks))


def blend_role_fit(primary: int, criteria_alignment: int) -> int:
    """Смешать LLM/эвристику (85%) и оси поиска (15%)."""
    blended = ROLE_FIT_PRIMARY_WEIGHT * primary + ROLE_FIT_CRITERIA_WEIGHT * criteria_alignment
    return max(0, min(100, round(blended)))


def criteria_alignment_tips(data: ResumeData, resume_text: str) -> list[str]:
    """Подсказки по осям, которые не читаются в тексте резюме."""
    tips: list[str] = []
    for key, ok in criteria_alignment_checks(data, resume_text):
        if not ok and key in CRITERIA_ALIGNMENT_HINTS:
            tips.append(CRITERIA_ALIGNMENT_HINTS[key])
    return tips


def format_search_axes_block(data: ResumeData) -> str:
    """Текстовый блок осей поиска для промптов role_fit / контекста."""
    sc = data.search_criteria
    pos = data.position
    lines = [
        f"Тип роли: {sc.role_kind or '(не указан)'}",
        f"Рынок поиска: {market_scope_label(sc.market_scope)}",
        f"Рынок / отрасль: {sc.market_segment.strip() if sc.market_segment.strip() else 'Любые'}",
        f"Приоритеты: {', '.join(sc.niches) if sc.niches else '(не указаны)'}",
        f"Формат работы: {', '.join(pos.schedule) if pos.schedule else '(не указан)'}",
        f"Типы компаний: {', '.join(pos.company_types) if pos.company_types else '(не указаны)'}",
    ]
    if sc.dealbreakers:
        lines.append(f"Редфлаги: {', '.join(sc.dealbreakers)}")
    if sc.target_companies:
        lines.append(f"Целевые компании: {', '.join(sc.target_companies[:8])}")
    salary_parts: list[str] = []
    if pos.salary_min:
        salary_parts.append(f"от {pos.salary_min}")
    if pos.salary_comfortable:
        salary_parts.append(f"комфорт {pos.salary_comfortable}")
    if salary_parts:
        cur = pos.salary_currency or "RUB"
        lines.append(f"Зарплатная вилка ({cur}): {' / '.join(salary_parts)}")
    if pos.categories:
        lines.append(f"Специализации: {', '.join(pos.categories)}")
    return "\n".join(lines)


__all__ = [
    "CRITERIA_ALIGNMENT_HINTS",
    "LEFT_PANEL_GAP_KEYS",
    "LEFT_PANEL_HINTS",
    "ROLE_FIT_CRITERIA_WEIGHT",
    "ROLE_FIT_PRIMARY_WEIGHT",
    "blend_role_fit",
    "criteria_alignment_checks",
    "criteria_alignment_tips",
    "format_search_axes_block",
    "left_panel_gaps",
    "left_panel_hints",
    "left_panel_ready_for_score",
    "score_criteria_alignment",
]
