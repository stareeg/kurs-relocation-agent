"""LLM-резолв типа этапа интервью, когда основной парсер HR-сообщения (`hr_message_parser.py`)
не вернул валидный `stage_type`. Раньше эту роль играл keyword-regex в
`bot_app/services/hr_enrichment.py::infer_stage_type` — он путает «техническое собеседование» с
`live_coding`, хотя это с равной вероятностью `system_design`/`theory`. Тот regex остаётся
fallback-ом на случай сбоя LLM (тот же принцип, что и в `funnel_status_llm.py`: LLM первым,
эвристика — страховка).
"""

from __future__ import annotations

import json
import logging
import re

from core.config import get_settings
from core.domains.preparation.models import InterviewStageType
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

_VALID_STAGE_TYPES: tuple[InterviewStageType, ...] = (
    "hr_screening",
    "live_coding",
    "system_design",
    "theory",
    "soft_skills",
    "manager",
    "business_case",
    "final",
)

_SYSTEM = (
    """Ты помощник Job Hunter — определяешь тип этапа интервью по тексту переписки/заметки.
Верни ТОЛЬКО JSON: {"stage_type": "<одно из допустимых>", "reasoning": "кратко на русском"}

Допустимые значения (точно как строки):
"""
    + ", ".join(_VALID_STAGE_TYPES)
    + """

Правила:
- «Техническое собеседование» само по себе НЕ значит live_coding — это с равной вероятностью
  system_design или theory. Смотри на контекст: обсуждение архитектуры/масштабирования →
  system_design; live-кодинг/leetcode/алгоритмы у доски → live_coding; вопросы по теории/базе
  без кода → theory.
- Кейс/бизнес-кейс (разбор гипотетической бизнес-задачи, не алгоритмы и не архитектура) →
  business_case.
- Финальный раунд/финальное собеседование (часто с руководителем/CEO, часто после уже пройденных
  технических этапов) → final. Отдельно узкий разговор именно с непосредственным руководителем
  без признаков финального раунда → manager. Узко культурный fit/soft skills без признаков
  финала → soft_skills. Все три сейчас двигают воронку в «Финал», но stage_type должен отражать
  РЕАЛЬНЫЙ формат, не просто близость к концу процесса.
- Разговор с руководителем/директором/head of (не финальный раунд) → manager.
- Софт-скиллы/культурное соответствие (не финальный раунд) → soft_skills.
- Первичный скрининг/знакомство с HR, без технической части → hr_screening.
- Если контекста недостаточно, чтобы уверенно выбрать технический подтип — hr_screening
  (самый безопасный дефолт, не льстит точности).
"""
)


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty LLM response", raw, 0)

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(raw[start : i + 1])

    raise json.JSONDecodeError("no JSON object in LLM response", raw, 0)


async def resolve_stage_type_llm(
    text: str, *, vacancy_id: str = ""
) -> tuple[InterviewStageType, str] | None:
    """Вернуть (stage_type, reasoning) или None при недоступности/сбое LLM.

    `None` — сигнал звонящему коду упасть на regex-fallback (`infer_stage_type`), не решение
    само по себе: здесь нет «безопасного дефолта», это сделает вызывающая сторона.

    `vacancy_id` — только для лога (§15 плана `local_context_blind_spots_2026_08_12.md`):
    без него reasoning классификатора нигде не попадал в `copilot_logs`/бандл поддержки.
    """
    if not get_settings().openrouter_api_key:
        return None

    content = ""
    try:
        content = await ports.llm().complete(
            "stage_type",
            system=_SYSTEM,
            user=text[:2000],
            temperature=0.1,
        )
        data = _extract_json(content)
        raw_stage = str(data.get("stage_type", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()
        event(
            logger,
            "LLM",
            "stage_type: raw=%s (vacancy_id=%s) — %s",
            raw_stage or "—",
            vacancy_id or "—",
            reasoning or "—",
            vacancy_id=vacancy_id,
            stage_type=raw_stage,
            reasoning=reasoning,
            fallback=raw_stage not in _VALID_STAGE_TYPES,
        )
        if raw_stage in _VALID_STAGE_TYPES:
            return raw_stage, reasoning  # type: ignore[return-value]
        logger.warning("LLM stage_type не распознан: %s", raw_stage)
    except (LlmError, json.JSONDecodeError, KeyError) as exc:
        snippet = (content[:200] + "…") if content else "(пусто)"
        logger.warning("LLM resolve stage_type failed: %s — ответ: %s", exc, snippet)
        event(
            logger,
            "LLM",
            "stage_type: сбой (vacancy_id=%s) — %s",
            vacancy_id or "—",
            exc,
            level=logging.WARNING,
            vacancy_id=vacancy_id,
            fallback=True,
            reasoning=str(exc),
        )

    return None
