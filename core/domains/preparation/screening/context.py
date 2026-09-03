"""Форматирование кэша пакета скрининга для чата / HR-черновика / сопроводительного.

Только чтение уже сохранённого пакета - без LLM. Groups (нападение) сюда не входят: другой жанр
для письма и ответа рекрутёру. Нет записи / пустой срез защиты → пустая строка (вызывающий
делает фолбэк).

Отдельного блока «Мосты к вакансии» здесь больше нет - требование вакансии, на которое отвечает
вопрос, теперь идёт прямо с самим HR-вопросом (`HrQuestion.requirement`), а не дублирующим
списком рядом.
"""

from __future__ import annotations

from typing import Any

from core.domains.preparation.screening_questions import (
    SavedScreeningQuestions,
    get_screening_questions,
)

# В промпт hr_draft/письма хватает 2-3 вероятных Q&A - не раздуваем контекст.
_MAX_HR_QUESTIONS = 3


def _has_defense(saved: SavedScreeningQuestions) -> bool:
    return bool(
        (saved.oral_pitch or "").strip() or (saved.why_company or "").strip() or saved.hr_questions
    )


def format_self_pres_context(
    saved: SavedScreeningQuestions | None,
    *,
    include_hr_questions: bool = True,
    max_hr_questions: int = _MAX_HR_QUESTIONS,
    include_ask_questions: bool = False,
) -> str:
    """Короткий markdown-блок защиты из кэша. Пустой пакет / None → \"\".

    include_ask_questions — вопросы кандидата К HR (`saved.groups`), по умолчанию выключено
    (HR-черновик/сопроводительное их не используют, см. модуль). Единственный текущий потребитель
    с include_ask_questions=True — чат Скринингов (`core.app.scenarios.prep_chat._pack_content`):
    там это тот же экран, что и «Вопросы от HR», агенту нужны обе стороны диалога.
    """
    if saved is None or not _has_defense(saved):
        return ""

    parts: list[str] = []
    oral = (saved.oral_pitch or "").strip()
    if oral:
        parts.append("### Устный рассказ под вакансию\n\n" + oral)

    why = (saved.why_company or "").strip()
    if why:
        parts.append("### Почему компания\n\n" + why)

    if include_hr_questions:
        hr_blocks: list[str] = []
        for item in (saved.hr_questions or [])[: max(0, max_hr_questions)]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()
            requirement = str(item.get("requirement") or "").strip()
            intent = str(item.get("intent") or "").strip()
            a = str(item.get("draft_answer") or "").strip()
            if not q:
                continue
            block = f"**Q:** {q}"
            if requirement:
                block += f"\n**Требование:** {requirement}"
            if intent:
                block += f"\n**Проверяют:** {intent}"
            if a:
                block += f"\n**A:** {a}"
            hr_blocks.append(block)
        if hr_blocks:
            parts.append(
                "### Вероятные вопросы HR (черновики ответов)\n\n" + "\n\n".join(hr_blocks)
            )

    if include_ask_questions:
        ask_blocks: list[str] = []
        for g in saved.groups or []:
            if not isinstance(g, dict):
                continue
            title = str(g.get("title") or "").strip()
            questions = g.get("questions") or []
            if not isinstance(questions, list):
                continue
            for item in questions:
                if not isinstance(item, dict):
                    continue
                q = str(item.get("question") or "").strip()
                if not q:
                    continue
                block = f"**Вопрос:** {q}"
                probe = str(item.get("probe") or "").strip()
                if probe:
                    block += f"\n**Что хотим понять:** {probe}"
                if title:
                    block += f"\n**Группа:** {title}"
                ask_blocks.append(block)
        if ask_blocks:
            parts.append(
                "### Вопросы, которые кандидат собирается задать HR\n\n" + "\n\n".join(ask_blocks)
            )

    return "\n\n".join(parts).strip()


def format_self_pres_for_cover_letter(saved: SavedScreeningQuestions | None) -> str:
    """Срез для сопроводительного: oral + мосты + why, без hr_questions."""
    return format_self_pres_context(saved, include_hr_questions=False)


async def load_self_pres_context(
    vacancy_id: str,
    *,
    account_id: int,
    include_hr_questions: bool = True,
    max_hr_questions: int = _MAX_HR_QUESTIONS,
    include_ask_questions: bool = False,
) -> str:
    """Загрузить кэш по vacancy_id и отформатировать. Нет PG/записи → \"\"."""
    if not (vacancy_id or "").strip():
        return ""
    saved = await get_screening_questions(vacancy_id.strip(), account_id=account_id)
    return format_self_pres_context(
        saved,
        include_hr_questions=include_hr_questions,
        max_hr_questions=max_hr_questions,
        include_ask_questions=include_ask_questions,
    )


def saved_from_mapping(data: dict[str, Any], *, vacancy_id: str = "") -> SavedScreeningQuestions:
    """Сконструировать SavedScreeningQuestions из dict (тесты / без БД)."""
    hr_raw = data.get("hr_questions") or []
    hr_questions = hr_raw if isinstance(hr_raw, list) else []
    groups_raw = data.get("groups")
    groups = groups_raw if isinstance(groups_raw, list) else []
    return SavedScreeningQuestions(
        vacancy_id=vacancy_id or str(data.get("vacancy_id") or ""),
        groups=groups,
        hr_questions=hr_questions,
        why_company=str(data.get("why_company") or ""),
        oral_pitch=str(data.get("oral_pitch") or ""),
    )


__all__ = [
    "format_self_pres_context",
    "format_self_pres_for_cover_letter",
    "load_self_pres_context",
    "saved_from_mapping",
]
