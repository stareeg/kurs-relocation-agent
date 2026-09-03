"""LLM-резолв статуса воронки при неясном HH/Telegram контексте (порт из backend, S8).

Транспорт — порт `kernel.ports.llm().complete`; таксономия — `core.kernel.schemas.funnel`. Без БД. При сбое
LLM — fallback на текущий статус или «Отклик».
"""

from __future__ import annotations

import json
import logging
import re

from core.config import get_settings
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.schemas.funnel import FunnelStatus, all_funnel_status_values, resolve_funnel_status
from core.platform.observability import event

logger = logging.getLogger(__name__)

_SYSTEM = (
    """Ты помощник Job Hunter — определяешь статус воронки поиска работы.
Верни ТОЛЬКО JSON: {"funnel_status": "<одно из допустимых>", "reasoning": "кратко на русском"}

Допустимые статусы (точно как строки):
"""
    + ", ".join(all_funnel_status_values())
    + """

Правила:
- Страница hh.ru «Мои отклики» — это уже отправленные отклики, минимум «Отклик».
- HH «Собеседование» без конкретной даты/времени → «HR-звонок» или «В переписке с HR», НЕ «Собеседование».
- HH «Отказ» при активной переписке HR в Telegram → «В переписке с HR» или выше, не «Отказ».
- «Отказ» на HH не отменяет уже идущий процесс (HR-звонок, техинтервью), если контекст говорит о продолжении.
- Если в контексте явно упомянут финальный раунд/финальное собеседование (обычно после уже пройденных технических этапов) — статус «Финал», не «Техничка».
- Если неясно — «Отклик» или «В переписке с HR», не оставляй пустым.
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


async def resolve_funnel_status_llm(
    *,
    hh_status_raw: str = "",
    company: str = "",
    title: str = "",
    last_message: str | None = None,
    current_status: str | None = None,
    extra_context: str = "",
    vacancy_id: str = "",
) -> tuple[str, str]:
    """
    Вернуть (канонический funnel_status, reasoning).
    При ошибке LLM — fallback на current или «Отклик».

    `vacancy_id` — только для лога (§15 плана `local_context_blind_spots_2026_08_12.md`):
    reasoning классификатора раньше жил только в памяти функции и `llm_result_cache`, до
    бандла поддержки (`GET /api/logs/bundle`) не долетал вовсе.
    """
    if not get_settings().openrouter_api_key:
        fallback = resolve_funnel_status(current_status) or FunnelStatus.APPLIED
        return fallback, "LLM недоступен (нет API key)"

    user_parts = [
        f"Компания: {company or '—'}",
        f"Должность: {title or '—'}",
        f"Статус HH (сырой): {hh_status_raw or '—'}",
        f"Текущий статус Job Hunter: {current_status or 'не задан'}",
    ]
    if last_message:
        user_parts.append(f"Последнее сообщение на HH: {last_message[:500]}")
    if extra_context:
        user_parts.append(f"Контекст: {extra_context[:800]}")

    content = ""
    try:
        content = await ports.llm().complete(
            "funnel",
            system=_SYSTEM,
            user="\n".join(user_parts),
            temperature=0.1,
        )
        data = _extract_json(content)
        raw_status = str(data.get("funnel_status", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()
        resolved = resolve_funnel_status(raw_status)
        event(
            logger,
            "LLM",
            "funnel_status: raw=%s → %s (vacancy_id=%s) — %s",
            raw_status or "—",
            resolved or "не распознан",
            vacancy_id or "—",
            reasoning or "—",
            vacancy_id=vacancy_id,
            raw_status=raw_status,
            funnel_status=resolved,
            reasoning=reasoning,
            fallback=not resolved,
        )
        if resolved:
            return resolved, reasoning
        logger.warning("LLM funnel_status не распознан: %s", raw_status)
    except (LlmError, json.JSONDecodeError, KeyError) as exc:
        snippet = (content[:200] + "…") if content else "(пусто)"
        logger.warning(
            "LLM resolve funnel_status failed: %s — ответ: %s",
            exc,
            snippet,
        )
        event(
            logger,
            "LLM",
            "funnel_status: сбой (vacancy_id=%s) — %s",
            vacancy_id or "—",
            exc,
            level=logging.WARNING,
            vacancy_id=vacancy_id,
            fallback=True,
            reasoning=str(exc),
        )

    fallback = resolve_funnel_status(current_status) or FunnelStatus.APPLIED
    return fallback, "fallback без LLM"
