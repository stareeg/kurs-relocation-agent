"""Извлечение следующего этапа собеседования из расшифровки HR-скрининга.

Отдельная узкая LLM-фича (по образцу `core.domains.pipeline.hr_facts`) — общий парсер HR-сообщений
(`hr_message_parser.py`) заточен под формат «сообщение от HR», для транскрипта звонка не подходит
без переписывания промпта целиком. Хвост разбора (`core.app.scenarios.debrief._tails`), не
самостоятельный сценарий: вызывается best-effort после того, как разбор уже сохранён.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.preparation.interview.timing import stage_status_from_datetime
from core.domains.preparation.interview_stages import InterviewStage, save_stage
from core.domains.preparation.models import InterviewStageType
from core.kernel import ports

_MSK = timezone(timedelta(hours=3))


class NextStageHint(BaseModel):
    """Упоминание следующего этапа со слов HR на звонке. mentioned=False — явно не упомянуто."""

    mentioned: bool = Field(default=False, description="HR явно назвал следующий этап")
    stage_type: InterviewStageType = "hr_screening"
    scheduled_at: datetime | None = Field(
        default=None, description="ISO 8601 с таймзоной, null если дата не названа"
    )
    format: Literal["online", "offline", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=300)


_SYSTEM_TEMPLATE = """Ты — извлекатель фактов из расшифровки HR-скрининга (звонок с рекрутёром).

Сегодня: {today} (Москва, UTC+3) — используй эту дату для относительных упоминаний
(«на следующей неделе», «во вторник»).

Определи, назвал ли HR СЛЕДУЮЩИЙ этап собеседования после этого скрининга — конкретно, не общими
словами вида «будем на связи»/«вернёмся с обратной связью».

Верни ТОЛЬКО JSON:
{{
  "mentioned": true|false,
  "stage_type": "hr_screening|live_coding|system_design|theory|soft_skills|manager|business_case|final",
  "scheduled_at": "ISO 8601 +03:00 или null, если дата не названа",
  "format": "online|offline|unknown",
  "notes": "коротко, что именно сказал HR про этот этап (до 300 символов)"
}}

Правила:
- "mentioned"=false, если HR не назвал конкретный следующий этап — НЕ выдумывай ради заполнения
  схемы, пустой/неоднозначный результат — это валидный и частый ответ.
- "stage_type": «техничка»/«техническое собеседование» без уточнений → live_coding; явный
  system design → system_design; «финал»/«встреча с руководителем»/«с CTO» → final; если тип
  неясен, но этап точно назван — hr_screening как безопасный дефолт.
- "scheduled_at" — только если названа явная дата/день недели; относительные формулировки
  переведи в дату от «сегодня» выше. Расплывчатое «на неделе» без дня — null.
- Решение только по словам HR из расшифровки, не по своим предположениям."""


async def extract_next_stage(transcript: str) -> NextStageHint:
    """Извлечь упоминание следующего этапа (дешёвый тир). Короткий/пустой вход → mentioned=False."""
    text = (transcript or "").strip()
    if len(text) < 20:
        return NextStageHint()

    today = datetime.now(tz=_MSK).strftime("%Y-%m-%d (%A)")
    system = _SYSTEM_TEMPLATE.format(today=today)
    user = f"Расшифровка HR-скрининга:\n\n{text[:6000]}"
    result = await ports.llm().structured(
        "next_stage_hint",
        schema=NextStageHint,
        system=system,
        user=user,
        temperature=0.1,
        max_retries=1,
    )
    if not isinstance(result, NextStageHint):  # pragma: no cover — структурный контракт
        return NextStageHint()
    return result


async def apply_next_stage_safe(vacancy_id: str, transcript: str, *, account_id: int) -> None:
    """Извлечь + записать в цепочку этапов. Ничего не упомянуто/распознать не вышло → no-op."""
    hint = await extract_next_stage(transcript)
    if not hint.mentioned:
        return
    await save_stage(
        InterviewStage(
            vacancy_id=vacancy_id,
            stage_type=hint.stage_type,
            scheduled_at=hint.scheduled_at,
            format=hint.format,
            status=stage_status_from_datetime(hint.scheduled_at, "scheduled"),
            notes=hint.notes,
        ),
        account_id=account_id,
    )


__all__ = ["NextStageHint", "apply_next_stage_safe", "extract_next_stage"]
