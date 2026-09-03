"""Справочник специальностей резюме (закрытый список в UI «Профиль»).

Value = человекочитаемая подпись: так специальность уходит в markdown, identity-строку
и промпт парсера PDF без отдельного словаря. Старые getmatch-слаги мапятся на канон
при чтении `ResumeData`, чтобы сохранённые резюме не теряли выбор.
"""

from __future__ import annotations

RESUME_CATEGORIES: tuple[str, ...] = (
    "Backend",
    "Frontend",
    "Fullstack",
    "Mobile",
    "QA / тестирование",
    "Аналитика / Data",
    "ML / DS / AI",
    "DevOps / инфраструктура",
    "КиберБез",
    "Техподдержка",
    "Product Management",
    "Project Management",
    "Системный анализ",
    "Дизайн / UX",
    "Embedded / IoT",
    "Архитектура",
    "Маркетинг",
    "Руководство",
)

RESUME_CATEGORIES_MAX = 3

_CANONICAL = frozenset(RESUME_CATEGORIES)

# Старые английские/зонтичные значения формы → канон.
# Пустая строка = выкинуть (не IT: 1С, HR, продажи).
_LEGACY_CATEGORY_MAP: dict[str, str] = {
    "QA": "QA / тестирование",
    "Product/Project/Architecture": "Product Management",
    "Project Manager": "Project Management",
    "Design & UX": "Дизайн / UX",
    "Analytics": "Аналитика / Data",
    "Аналитика": "Аналитика / Data",
    "Information Security": "КиберБез",
    "Информационная безопасность": "КиберБез",
    "Infrastructure & DevOps": "DevOps / инфраструктура",
    "Support": "Техподдержка",
    "Data & ML": "ML / DS / AI",
    "Data / ML": "ML / DS / AI",
    "HR & Recruitment": "",
    "HR / рекрутинг": "",
    "Top Management": "Руководство",
    "1C": "",
    "1С": "",
    "Sales": "",
    "Продажи": "",
    "Marketing": "Маркетинг",
    "Technical Engineering": "Системный анализ",
    "UX & Tech Writers": "Дизайн / UX",
}


def normalize_categories(raw: object) -> list[str]:
    """Привести сохранённые специальности к актуальному списку. Мусор и дубли отбрасываем."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if not trimmed:
            continue
        mapped = _LEGACY_CATEGORY_MAP.get(trimmed, trimmed)
        if not mapped or mapped not in _CANONICAL or mapped in seen:
            continue
        seen.add(mapped)
        out.append(mapped)
        if len(out) >= RESUME_CATEGORIES_MAX:
            break
    return out


def resume_categories_prompt_list() -> str:
    """Список для Field description / промпта парсера PDF."""
    return ", ".join(RESUME_CATEGORIES)
