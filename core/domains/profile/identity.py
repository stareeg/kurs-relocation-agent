"""Единый источник строки-идентичности кандидата для system-промптов.

Раньше "Lead LLM Engineer, ex-Сбер" было продублировано вручную в ~15 промптах и модулях
(`prompts/assistant/system.md`, `core/interview/*`, `core/scoring/*` — см. FR-6). Эта функция
собирает эквивалент из резюме, чтобы для другой специальности текст не оставался враньём.
"""

from __future__ import annotations

from core.domains.profile.model import ResumeData

_FALLBACK = "кандидат ищет работу"
_FALLBACK_SPECIALIZATION = "вашей специализации"


def candidate_identity_line(resume: ResumeData) -> str:
    """«{должность} ({место работы})» — короткая строка для system-промптов.

    Должность: `resume.position.title`, иначе последняя запись опыта, иначе целевой грейд.
    Место работы: последняя запись опыта (с "ex-", если это не текущее место). Пустое резюме
    не должно ронять промпты — возвращает нейтральную заглушку.
    """
    last_job = resume.experience[0] if resume.experience else None

    title = resume.position.title.strip()
    if not title and last_job is not None:
        title = last_job.position.strip()
    if not title and resume.position.grade:
        title = ", ".join(resume.position.grade)
    if not title:
        return _FALLBACK

    if last_job is None:
        return title
    company = last_job.company.strip()
    if not company:
        return title
    if last_job.current:
        return f"{title} ({company})"
    return f"{title} (ex-{company})"


def candidate_specialization_line(resume: ResumeData) -> str:
    """Ниша/специализация кандидата — для плейсхолдера `{{SPECIALIZATION}}` в
    профилях компаний (`core.domains.preparation.interview.company_profiles`); раньше там
    был зашит текст "ML/LLM".

    Источник: `search_criteria.niches` (явный приоритет из «Критериев поиска»), иначе
    `position.categories` (закрытый список специальностей формы). Пустое резюме —
    нейтральная заглушка.
    """
    niches = [n.strip() for n in resume.search_criteria.niches if n.strip()]
    if niches:
        return ", ".join(niches[:3])
    categories = [c.strip() for c in resume.position.categories if c.strip()]
    if categories:
        return ", ".join(categories)
    return _FALLBACK_SPECIALIZATION
