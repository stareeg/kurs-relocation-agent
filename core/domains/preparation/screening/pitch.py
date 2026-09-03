"""Устный рассказ под вакансию (план 2026-07-23, шаг 6): рассказ строится от разбора вакансии
(`core/screening/brief.py`, шаг 4) к фактам резюме, а не наоборот. Хранится блоками
(`core/screening/style.py:PitchBlock`) - сам формат выполняет правило «одна фраза - одна строка»
и даёт линтеру (`lint_pitch`, шаг 5) единицу проверки.

Промпт - `prompts/preparation/screening/pitch.md`. Тир - агент `screening_pitch` (LlmFeature →
reasoning_pro: задача письма прозой под стиль, не рассуждения). Битый JSON на первом вызове -
ровно один повтор с подсказкой про синтаксис (иначе пакет уходит без легенды). При нарушениях
устного стиля - ровно один ремонтный вызов тем же агентом; второй ремонт не делаем (дорого и
обычно не помогает, см. план часть 2) - число нарушений до/после только логируется, чтобы видеть,
работает ли линтер. Если сам ремонтный вызов упал (битый JSON/сеть) - отдаём черновик до ремонта,
а не роняем весь рассказ: непричёсанный по стилю текст лучше отсутствующего.
"""

from __future__ import annotations

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
from core.domains.preparation.llm import SCREENING_ORAL_STYLE, SCREENING_PITCH
from core.domains.preparation.screening.brief import JdBrief
from core.domains.preparation.screening.parse import strip_fence
from core.domains.preparation.screening.style import (
    PitchBlock,
    StyleViolation,
    lint_pitch,
    violations_to_prompt,
)
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

_PITCH_PROMPT = Path(SCREENING_PITCH)
_RESUME_TOKEN = "{{RESUME}}"
_ORAL_STYLE_TOKEN = "{{ORAL_STYLE}}"
_ORAL_STYLE_PATH = Path(SCREENING_ORAL_STYLE)

PITCH_LABELS = ("Кто я", "Что делал", "Мост к вакансии", "Почему сюда", "Что ищу", "Финал")
_LABEL_ORDER = {label: i for i, label in enumerate(PITCH_LABELS)}


class ScreeningPitch(BaseModel):
    """Устный рассказ блоками + «почему сюда». Требования вакансии в рассказ уже вплетены
    (блок «Мост к вакансии») — отдельного списка «требование → факт» здесь больше нет, он
    дублировал и рассказ, и HR-вопросы (те теперь сами носят своё `requirement`,
    `core.domains.preparation.screening.questions.HrQuestion`)."""

    blocks: list[PitchBlock] = Field(default_factory=list)
    why_company: str = ""


def pitch_to_plain_text(blocks: list[PitchBlock]) -> str:
    """Блоки → плоский текст (строки блока через перевод строки, блоки через пустую строку) -
    для копирования и для чата/HR-черновика, которые уже читают плоский `oral_pitch`."""
    parts = ["\n".join(line for line in block.lines if line.strip()) for block in blocks]
    return "\n\n".join(part for part in parts if part)


async def _load_system_prompt(*, account_id: int) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    raw = _PITCH_PROMPT.read_text(encoding="utf-8")
    return (
        raw.replace(CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data))
        .replace(_RESUME_TOKEN, load_resume(data=resume_data))
        .replace(_ORAL_STYLE_TOKEN, _ORAL_STYLE_PATH.read_text(encoding="utf-8"))
    )


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


def _build_user_prompt(brief: JdBrief, title: str, company: str, score_summary: str) -> str:
    head = "## Вакансия\n"
    if title:
        head += f"\nДолжность: {title}"
    if company:
        head += f"\nКомпания: {company}"
    head += f"\n\n{_format_brief(brief)}"
    if score_summary:
        head += f"\n\n## Наша оценка вакансии\n\n{score_summary}"
    return f"""{head}

Напиши устный рассказ под эту вакансию по инструкции. Верни ТОЛЬКО JSON."""


def _parse_blocks(items: object) -> list[PitchBlock]:
    if not isinstance(items, list):
        return []
    blocks: list[PitchBlock] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label not in _LABEL_ORDER:
            continue
        lines_raw = item.get("lines")
        lines = (
            [str(line).strip() for line in lines_raw if str(line).strip()]
            if isinstance(lines_raw, list)
            else []
        )
        if not lines:
            continue
        blocks.append(PitchBlock(label=label, lines=lines))
    blocks.sort(key=lambda b: _LABEL_ORDER[b.label])
    return blocks


def parse_pitch(raw: str) -> ScreeningPitch:
    """Разобрать JSON рассказа. Блоки с чужим label отбрасываются, оставшиеся сортируются в
    каноническом порядке (`PITCH_LABELS`)."""
    data = json.loads(strip_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не JSON-объект")
    return ScreeningPitch(
        blocks=_parse_blocks(data.get("blocks")),
        why_company=str(data.get("why_company") or "").strip(),
    )


async def _call_pitch(system_prompt: str, user: str) -> ScreeningPitch:
    raw = await ports.llm().complete(
        "screening_pitch",
        system=system_prompt,
        user=user,
        temperature=0.6,
    )
    try:
        return parse_pitch(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("screening pitch: LLM вернул не разобранный JSON: %s", exc)
        raise LlmError("LLM вернул некорректный формат рассказа") from exc


_JSON_RETRY_HINT = (
    "Предыдущий ответ нельзя разобрать как JSON (синтаксис сломан). "
    "Верни ТОЛЬКО валидный JSON той же формы, без markdown и пояснений. "
    "В строках экранируй кавычки, без trailing comma."
)


def _build_repair_user_prompt(pitch: ScreeningPitch, violations: list[StyleViolation]) -> str:
    current = json.dumps(
        {
            "blocks": [b.model_dump() for b in pitch.blocks],
            "why_company": pitch.why_company,
        },
        ensure_ascii=False,
    )
    return f"""## Текущий черновик (JSON)

{current}

## Нарушения устного стиля - исправить каждое

{violations_to_prompt(violations)}

Перепиши целиком, устранив каждый пункт; факты и структуру (label) не менять.
Верни ТОЛЬКО JSON той же формы."""


async def generate_screening_pitch(
    *,
    account_id: int,
    brief: JdBrief,
    title: str = "",
    company: str = "",
    score_summary: str = "",
) -> ScreeningPitch:
    """Разбор вакансии → устный рассказ блоками + мосты.

    L-13: на сценарий — максимум один дополнительный LLM-вызов (итого ≤2): либо JSON-retry
    при битом первом ответе, либо style-repair. Оба подряд не запускаем — иначе пакет
    скрининга легко упирается в клиентский таймаут при уже успешной первой генерации.

    Нет ключа OpenRouter → `LlmError`.
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    system_prompt = await _load_system_prompt(account_id=account_id)
    user = _build_user_prompt(brief, title, company, score_summary)
    used_extra = False
    try:
        pitch = await _call_pitch(system_prompt, user)
    except LlmError as first_exc:
        # Claude часто ломает длинный JSON (кавычки) - один повтор дешевле пустой легенды.
        logger.warning(
            "screening pitch: первый ответ не разобран, повторяю один раз: %s", first_exc
        )
        retry_user = f"{user}\n\n{_JSON_RETRY_HINT}"
        pitch = await _call_pitch(system_prompt, retry_user)
        used_extra = True

    anchors = [req.text for req in brief.requirements] + brief.jargon
    violations = lint_pitch(pitch.blocks, anchors=anchors)
    if not violations:
        event(
            logger,
            "LLM",
            "screening pitch: 0 нарушений устного стиля, ремонт не нужен",
            repaired=False,
        )
        return pitch

    if used_extra:
        event(
            logger,
            "LLM",
            "screening pitch: %d нарушений устного стиля, extra-вызов уже был (JSON retry) - отдаём как есть",
            len(violations),
            violations_before=len(violations),
            repaired=False,
            level=logging.WARNING,
        )
        return pitch

    logger.info("screening pitch: %d нарушений устного стиля, запускаю ремонт", len(violations))
    try:
        repaired = await _call_pitch(system_prompt, _build_repair_user_prompt(pitch, violations))
    except LlmError as exc:
        event(
            logger,
            "LLM",
            "screening pitch: ремонт не удался, возвращаю черновик как есть: %s",
            exc,
            violations_before=len(violations),
            repaired=False,
            level=logging.WARNING,
        )
        return pitch
    repaired_violations = lint_pitch(repaired.blocks, anchors=anchors)
    event(
        logger,
        "LLM",
        "screening pitch: после ремонта нарушений %d (было %d)",
        len(repaired_violations),
        len(violations),
        violations_before=len(violations),
        violations_after=len(repaired_violations),
        repaired=True,
    )
    return repaired


__all__ = [
    "PITCH_LABELS",
    "ScreeningPitch",
    "generate_screening_pitch",
    "parse_pitch",
    "pitch_to_plain_text",
]
