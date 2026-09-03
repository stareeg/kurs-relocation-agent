"""Вопросы под вакансию (план 2026-07-23, шаг 7 + доп. усиление надёжности после живой проверки
шага 16): часть A - вероятные вопросы HR→кандидату с черновиками ответов, часть B - вопросы
кандидат→HR по группам, которые модель придумывает под конкретную вакансию (без зашитого списка
рубрик). Строится от разбора вакансии (`core/screening/brief.py`, шаг 4), а не от сырого текста JD.

Части A и B генерируются ДВУМЯ параллельными вызовами (а не одним JSON на обе), по той же причине,
по которой шаг 6 отделил рассказ от вопросов: разные схемы проще держать в узде по отдельности, и
поломка одной части (например, живая проверка нашла случай, когда модель роняла обязательное поле
`question` во всех группах части B из-за перегруженной комбинированной схемы) не должна топить
другую. Части A - `prompts/preparation/screening/hr_questions.md`, часть B - `prompts/preparation/screening/questions.md`.
Тир обеих - агент `screening_questions` (LlmFeature → reasoning).

Часть A особая: `draft_answer` читают вслух рекрутёру, поэтому после генерации прогоняется через
`core.domains.preparation.screening.style.lint_spoken_text` (тот же словарь правил устного стиля, что у легенды) и,
при нарушениях, чинится ровно одним ремонтным вызовом - см. `_generate_hr_questions`. Часть B
(`probe`/`expect`/`hook`) - аналитические заметки для чтения кандидатом про себя, а не текст на
звонок, поэтому не линтуются.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.opportunities.prompt import (
    CANDIDATE_IDENTITY_TOKEN,
    load_candidate_identity,
    load_resume,
)
from core.domains.preparation.llm import (
    SCREENING_HR_QUESTIONS,
    SCREENING_ORAL_STYLE,
    SCREENING_QUESTIONS,
)
from core.domains.preparation.screening.brief import JdBrief
from core.domains.preparation.screening.parse import strip_fence
from core.domains.preparation.screening.style import StyleViolation, lint_spoken_text
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

_HR_QUESTIONS_PROMPT = Path(SCREENING_HR_QUESTIONS)
_GROUPS_PROMPT = Path(SCREENING_QUESTIONS)
_RESUME_TOKEN = "{{RESUME}}"
_ORAL_STYLE_TOKEN = "{{ORAL_STYLE}}"
_ORAL_STYLE_PATH = Path(SCREENING_ORAL_STYLE)


class HrQuestion(BaseModel):
    """Вероятный вопрос HR к кандидату: конкретное требование вакансии, за которым он стоит,
    что этим проверяют + черновик ответа. `requirement` заменяет отдельный список «мосты к
    вакансии» — требование видно прямо при своём вопросе, не отдельным блоком."""

    question: str = Field(min_length=1, max_length=1000)
    requirement: str = Field(default="", max_length=300)
    intent: str = ""
    draft_answer: str = Field(min_length=1, max_length=2000)


class ScreeningQuestion(BaseModel):
    """Один вопрос, который кандидат задаёт HR: что хотим понять + что вероятно услышим."""

    question: str
    probe: str = Field(default="", description="Что хотим понять этим вопросом")
    expect: str = Field(default="", description="Что вероятно услышим и как это трактовать")


class QuestionGroup(BaseModel):
    """Группа вопросов кандидат→HR, придуманная под эту вакансию (без зашитых рубрик)."""

    title: str
    hook: str = Field(
        default="", description="Фраза вакансии (или дыра в ней), из-за которой группа появилась"
    )
    questions: list[ScreeningQuestion] = Field(default_factory=list)


class ScreeningQuestions(BaseModel):
    """Обе части вопросов под вакансию: HR→кандидат (с черновиками) и кандидат→HR (по группам)."""

    hr_questions: list[HrQuestion] = Field(default_factory=list)
    groups: list[QuestionGroup] = Field(default_factory=list)


async def _load_hr_questions_prompt(*, account_id: int | None) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    raw = _HR_QUESTIONS_PROMPT.read_text(encoding="utf-8")
    return (
        raw.replace(CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data))
        .replace(_RESUME_TOKEN, load_resume(data=resume_data))
        .replace(_ORAL_STYLE_TOKEN, _ORAL_STYLE_PATH.read_text(encoding="utf-8"))
    )


async def _load_groups_prompt(*, account_id: int | None) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    raw = _GROUPS_PROMPT.read_text(encoding="utf-8")
    return raw.replace(CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data))


def _format_brief(brief: JdBrief) -> str:
    lines = ["## Разбор вакансии"]
    if brief.role_reality:
        lines.append(f"\nЧем реально заниматься: {brief.role_reality}")
    if brief.product_context:
        lines.append(f"Продукт: {brief.product_context}")
    if brief.requirements:
        lines.append("\nТребования (важность - формулировка - цитата из вакансии):")
        for req in brief.requirements:
            quote = f' - "{req.quote}"' if req.quote else ""
            lines.append(f"- [{req.weight}] {req.text}{quote}")
    if brief.hooks:
        lines.append("\nЗацепки из текста вакансии:")
        lines.extend(f"- {hook}" for hook in brief.hooks)
    if brief.unknowns:
        lines.append("\nЧего не сказано в вакансии:")
        lines.extend(f"- {unknown}" for unknown in brief.unknowns)
    if brief.jargon:
        lines.append(f"\nТермины этой вакансии: {', '.join(brief.jargon)}")
    return "\n".join(lines)


def _build_user_prompt(
    brief: JdBrief, title: str, company: str, score_summary: str, *, task: str
) -> str:
    head = "## Вакансия\n"
    if title:
        head += f"\nДолжность: {title}"
    if company:
        head += f"\nКомпания: {company}"
    head += f"\n\n{_format_brief(brief)}"
    if score_summary:
        head += f"\n\n## Наша оценка вакансии\n\n{score_summary}"
    return f"""{head}

{task} Верни ТОЛЬКО JSON."""


def _parse_hr_questions(items: object) -> list[HrQuestion]:
    if not isinstance(items, list):
        return []
    out: list[HrQuestion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            q = HrQuestion(
                question=str(item.get("question") or "").strip(),
                requirement=str(item.get("requirement") or "").strip(),
                intent=str(item.get("intent") or "").strip(),
                draft_answer=str(item.get("draft_answer") or "").strip(),
            )
        except Exception as exc:  # noqa: BLE001 - битой hr_question пропускаем
            logger.warning("Битый hr_question пропущен: %s (%s)", item, exc)
            continue
        if q.question and q.draft_answer:
            out.append(q)
    return out


def _parse_screening_question(item: object) -> ScreeningQuestion | None:
    """Один вопрос части B. LLM часто забывает `question` и кладёт формулировку в `probe`."""
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or "").strip()
    probe = str(item.get("probe") or "").strip()
    expect = str(item.get("expect") or "").strip()
    if not question and probe:
        question, probe = probe, ""
    if not question:
        return None
    return ScreeningQuestion(question=question, probe=probe, expect=expect)


def _parse_groups(items: object) -> list[QuestionGroup]:
    if not isinstance(items, list):
        return []
    groups: list[QuestionGroup] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_qs = item.get("questions")
        questions = [
            q
            for raw in (raw_qs if isinstance(raw_qs, list) else [])
            if (q := _parse_screening_question(raw)) is not None
        ]
        title = str(item.get("title") or "").strip()
        hook = str(item.get("hook") or "").strip()
        if not title or not questions:
            if title or raw_qs:
                logger.warning(
                    "Битая группа вопросов пропущена: title=%r questions=%r",
                    title,
                    raw_qs,
                )
            continue
        groups.append(QuestionGroup(title=title, hook=hook, questions=questions))
    return groups


def parse_hr_questions_response(raw: str) -> list[HrQuestion]:
    """Разобрать JSON части A. Совместимость со старым ключом `questions` вместо `hr_questions` -
    так называлось поле в промпте до разделения на части A/B."""
    data = json.loads(strip_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не JSON-объект")
    hr_raw = data.get("hr_questions")
    if hr_raw is None:
        hr_raw = data.get("questions")
    result = _parse_hr_questions(hr_raw)
    if not result:
        raise ValueError("LLM вернул пустой список вопросов HR")
    return result


def parse_groups_response(raw: str) -> list[QuestionGroup]:
    """Разобрать JSON части B."""
    data = json.loads(strip_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не JSON-объект")
    result = _parse_groups(data.get("groups"))
    if not result:
        raise ValueError("LLM вернул пустой список групп вопросов")
    return result


async def _call_hr_questions(system_prompt: str, user: str) -> list[HrQuestion]:
    raw = await ports.llm().complete(
        "screening_questions",
        system=system_prompt,
        user=user,
        temperature=0.4,
    )
    try:
        return parse_hr_questions_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("screening hr_questions: LLM вернул не разобранный JSON: %s", exc)
        raise LlmError("LLM вернул некорректный формат вопросов HR") from exc


def _flag_hr_answer_violations(
    hr_questions: list[HrQuestion],
) -> list[tuple[HrQuestion, list[StyleViolation]]]:
    flagged: list[tuple[HrQuestion, list[StyleViolation]]] = []
    for q in hr_questions:
        violations = lint_spoken_text(q.draft_answer)
        if violations:
            flagged.append((q, violations))
    return flagged


def _hr_violations_prompt(flagged: list[tuple[HrQuestion, list[StyleViolation]]]) -> str:
    lines = [f'Вопрос "{q.question}" - {v.detail}' for q, violations in flagged for v in violations]
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))


def _build_hr_repair_prompt(
    hr_questions: list[HrQuestion], flagged: list[tuple[HrQuestion, list[StyleViolation]]]
) -> str:
    current = json.dumps(
        {"hr_questions": [q.model_dump() for q in hr_questions]}, ensure_ascii=False
    )
    return f"""## Текущий черновик вопросов HR (JSON)

{current}

## Нарушения устного стиля в draft_answer - исправить каждое

{_hr_violations_prompt(flagged)}

Перепиши весь список целиком. Меняй ТОЛЬКО draft_answer у вопросов из списка нарушений; question,
requirement, intent и все вопросы без нарушений оставь дословно как есть.
Верни ТОЛЬКО JSON той же формы: {{"hr_questions": [...]}}"""


async def _generate_hr_questions(
    *, brief: JdBrief, title: str, company: str, score_summary: str, account_id: int
) -> list[HrQuestion]:
    system_prompt = await _load_hr_questions_prompt(account_id=account_id)
    user = _build_user_prompt(
        brief,
        title,
        company,
        score_summary,
        task="Составь вопросы, которые вероятно задаст HR, с черновиками устных ответов "
        "по инструкции.",
    )
    hr_questions = await _call_hr_questions(system_prompt, user)

    flagged = _flag_hr_answer_violations(hr_questions)
    if not flagged:
        event(
            logger,
            "LLM",
            "screening hr_questions: 0 нарушений устного стиля в draft_answer, ремонт не нужен",
            repaired=False,
        )
        return hr_questions

    total_before = sum(len(v) for _, v in flagged)
    logger.info(
        "screening hr_questions: %d нарушений устного стиля в draft_answer (%d из %d вопросов), "
        "запускаю ремонт",
        total_before,
        len(flagged),
        len(hr_questions),
    )
    try:
        repaired = await _call_hr_questions(
            system_prompt, _build_hr_repair_prompt(hr_questions, flagged)
        )
    except LlmError as exc:
        event(
            logger,
            "LLM",
            "screening hr_questions: ремонт не удался, возвращаю черновик как есть: %s",
            exc,
            violations_before=total_before,
            repaired=False,
            level=logging.WARNING,
        )
        return hr_questions
    total_after = sum(len(v) for _, v in _flag_hr_answer_violations(repaired))
    event(
        logger,
        "LLM",
        "screening hr_questions: после ремонта нарушений %d (было %d)",
        total_after,
        total_before,
        violations_before=total_before,
        violations_after=total_after,
        repaired=True,
    )
    return repaired


async def _generate_groups(
    *, brief: JdBrief, title: str, company: str, score_summary: str, account_id: int
) -> list[QuestionGroup]:
    system_prompt = await _load_groups_prompt(account_id=account_id)
    user = _build_user_prompt(
        brief,
        title,
        company,
        score_summary,
        task="Составь группы вопросов к рекрутёру по инструкции.",
    )
    raw = await ports.llm().complete(
        "screening_questions",
        system=system_prompt,
        user=user,
        temperature=0.4,
    )
    try:
        return parse_groups_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("screening groups: LLM вернул не разобранный JSON: %s", exc)
        raise LlmError("LLM вернул некорректный формат групп вопросов") from exc


async def generate_screening_questions(
    *,
    account_id: int,
    brief: JdBrief,
    title: str = "",
    company: str = "",
    score_summary: str = "",
) -> ScreeningQuestions:
    """Разбор вакансии → вопросы HR→кандидату (часть A) + вопросы кандидат→HR по группам
    (часть B) - двумя параллельными вызовами (см. модуль-докстрину).

    Нет ключа OpenRouter → `LlmError`. Обе части упали → `LlmError` наверх; упала
    одна - деградируем на том, что собралось (warning в лог).
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    hr_result, groups_result = await asyncio.gather(
        _generate_hr_questions(
            brief=brief,
            title=title,
            company=company,
            score_summary=score_summary,
            account_id=account_id,
        ),
        _generate_groups(
            brief=brief,
            title=title,
            company=company,
            score_summary=score_summary,
            account_id=account_id,
        ),
        return_exceptions=True,
    )

    hr_questions: list[HrQuestion] = []
    if isinstance(hr_result, BaseException):
        logger.warning("screening questions: вопросы HR не собрались: %s", hr_result)
    else:
        hr_questions = hr_result

    groups: list[QuestionGroup] = []
    if isinstance(groups_result, BaseException):
        logger.warning("screening questions: группы вопросов не собрались: %s", groups_result)
    else:
        groups = groups_result

    if isinstance(hr_result, BaseException) and isinstance(groups_result, BaseException):
        raise LlmError("вопросы HR и группы вопросов не собрались") from hr_result

    return ScreeningQuestions(hr_questions=hr_questions, groups=groups)


def _norm_question(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _filter_new_hr(items: list[HrQuestion], existing_norm: set[str]) -> list[HrQuestion]:
    out: list[HrQuestion] = []
    seen = set(existing_norm)
    for q in items:
        key = _norm_question(q.question)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def _filter_new_groups(groups: list[QuestionGroup], existing_norm: set[str]) -> list[QuestionGroup]:
    """Оставить только новые вопросы; пустые группы отбросить."""
    seen = set(existing_norm)
    out: list[QuestionGroup] = []
    for group in groups:
        kept: list[ScreeningQuestion] = []
        for q in group.questions:
            key = _norm_question(q.question)
            if not key or key in seen:
                continue
            seen.add(key)
            kept.append(q)
        if kept:
            out.append(QuestionGroup(title=group.title, hook=group.hook, questions=kept))
    return out


def _existing_block(existing: list[str]) -> str:
    lines = [q.strip() for q in existing if q and q.strip()]
    if not lines:
        return ""
    return "\n\nУже есть такие вопросы - НЕ повторяй их и не перефразируй:\n" + "\n".join(
        f"- {q}" for q in lines
    )


async def generate_more_hr_questions(
    *,
    account_id: int,
    brief: JdBrief,
    title: str = "",
    company: str = "",
    score_summary: str = "",
    existing: list[str] | None = None,
    count: int = 6,
) -> list[HrQuestion]:
    """Ещё пачка вопросов HR→кандидат, без повторов формулировок из `existing`."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    n = max(1, min(int(count or 6), 12))
    existing_list = list(existing or [])
    existing_norm = {_norm_question(q) for q in existing_list}
    system_prompt = await _load_hr_questions_prompt(account_id=account_id)
    user = _build_user_prompt(
        brief,
        title,
        company,
        score_summary,
        task=(
            f"Составь ещё ровно {n} новых вопросов, которые вероятно задаст HR, "
            f"с черновиками устных ответов по инструкции."
            f"{_existing_block(existing_list)}"
        ),
    )
    hr_questions = await _call_hr_questions(system_prompt, user)
    flagged = _flag_hr_answer_violations(hr_questions)
    if flagged:
        try:
            hr_questions = await _call_hr_questions(
                system_prompt, _build_hr_repair_prompt(hr_questions, flagged)
            )
        except LlmError as exc:
            logger.warning("screening more hr_questions: ремонт не удался, беру черновик: %s", exc)
    return _filter_new_hr(hr_questions, existing_norm)[:n]


async def generate_more_ask_groups(
    *,
    account_id: int,
    brief: JdBrief,
    title: str = "",
    company: str = "",
    score_summary: str = "",
    existing: list[str] | None = None,
    count: int = 6,
) -> list[QuestionGroup]:
    """Ещё пачка вопросов кандидат→HR (~count штук в новых группах), без повторов."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    n = max(1, min(int(count or 6), 12))
    existing_list = list(existing or [])
    existing_norm = {_norm_question(q) for q in existing_list}
    system_prompt = await _load_groups_prompt(account_id=account_id)
    user = _build_user_prompt(
        brief,
        title,
        company,
        score_summary,
        task=(
            f"Составь ещё группы вопросов к рекрутёру суммарно примерно на {n} новых вопросов "
            f"(2-3 группы). Не повторяй уже имеющиеся."
            f"{_existing_block(existing_list)}"
        ),
    )
    raw = await ports.llm().complete(
        "screening_questions",
        system=system_prompt,
        user=user,
        temperature=0.5,
    )
    try:
        groups = parse_groups_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("screening more groups: LLM вернул не разобранный JSON: %s", exc)
        raise LlmError("LLM вернул некорректный формат групп вопросов") from exc
    filtered = _filter_new_groups(groups, existing_norm)
    # Обрезаем до ~n вопросов, сохраняя целые группы где можно.
    kept: list[QuestionGroup] = []
    total = 0
    for group in filtered:
        if total >= n:
            break
        room = n - total
        qs = group.questions[:room]
        if not qs:
            continue
        kept.append(QuestionGroup(title=group.title, hook=group.hook, questions=qs))
        total += len(qs)
    return kept


__all__ = [
    "HrQuestion",
    "QuestionGroup",
    "ScreeningQuestion",
    "ScreeningQuestions",
    "generate_more_ask_groups",
    "generate_more_hr_questions",
    "generate_screening_questions",
    "parse_groups_response",
    "parse_hr_questions_response",
]
