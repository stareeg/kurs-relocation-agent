"""Дешёвая классификация при ручном архиве диалога: отказ HR vs пропуск кандидата.

По переписке (hr_in/hr_out) решаем, куда увести вакансию на доске: «Отказ» или «Пропущено».
Extract-tier, короткий JSON — без reasoning payload. Перед вызовом LLM проверяем локальные
факты (`local_evidence.has_scheduled_interview_stage`) — см. `classify_archive_disposition`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel

from core.config import get_settings
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.db.pool import Executor
from core.platform.observability import event

logger = logging.getLogger(__name__)

ArchiveDisposition = Literal["rejected", "skipped"]

_SYSTEM = """Ты классификатор Career Copilot. Пользователь закрыл диалог по вакансии в архив.
По фрагментам переписки с HR реши исход:

- "rejected" — в переписке есть явный отказ от HR/компании (отказ, не рассматриваем,
  выбрали другого, вакансия закрыта, «к сожалению» про кандидатуру и т.п.).
- "skipped" — явного отказа нет: кандидат сам перестал отвечать, процесс завис,
  «подумаю», тишина, вежливое завершение без отказа, или переписки почти нет.

Верни ТОЛЬКО JSON: {"disposition":"rejected"|"skipped","reasoning":"кратко на русском"}
"""


class ArchiveDispositionResult(BaseModel):
    disposition: ArchiveDisposition = "skipped"
    reasoning: str = ""


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


def _format_transcript(messages: list, *, limit: int = 24, max_chars: int = 4000) -> str:
    """Последние реплики HR-переписки (без llm_*) — хронология для классификатора."""
    hr = [m for m in messages if getattr(m, "kind", None) in ("hr_in", "hr_out")]
    if not hr:
        return "(переписки с HR нет)"
    chunk = hr[-limit:]
    lines: list[str] = []
    total = 0
    for m in chunk:
        who = "HR" if m.kind == "hr_in" else "Я"
        body = (m.body or "").strip().replace("\n", " ")
        if len(body) > 400:
            body = body[:400] + "…"
        line = f"{who}: {body}"
        if total + len(line) + 1 > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "(переписки с HR нет)"


async def classify_archive_disposition(
    *,
    company: str = "",
    title: str = "",
    messages: list | None = None,
    vacancy_id: str = "",
    account_id: int | None = None,
    db: Executor | None = None,
) -> ArchiveDispositionResult:
    """Вернуть disposition по переписке. Нет ключа/сбой LLM → skipped (безопасный дефолт).

    `vacancy_id`/`account_id` — тот же класс дыры, что уже чинили в `negotiations.py`
    (инцидент «ТехВилл», 2026-08-12): классификатор видит только переданную переписку, не
    `interview_stages`. Если по вакансии уже стоит запланированная встреча — не спрашиваем LLM
    вовсе (он может решить «Отказ» по тону переписки, хотя встреча ещё не состоялась), возвращаем
    `skipped` и оставляем решение владельцу."""
    if vacancy_id and account_id is not None:
        from core.domains.pipeline.local_evidence import has_scheduled_interview_stage

        if await has_scheduled_interview_stage(vacancy_id, account_id=account_id, db=db):
            return ArchiveDispositionResult(
                disposition="skipped",
                reasoning="есть запланированная встреча — авто-классификация отказа заблокирована",
            )

    transcript = _format_transcript(messages or [])
    if transcript == "(переписки с HR нет)":
        return ArchiveDispositionResult(
            disposition="skipped",
            reasoning="нет переписки с HR — считаем пропуском",
        )
    if not get_settings().openrouter_api_key:
        return ArchiveDispositionResult(
            disposition="skipped",
            reasoning="LLM недоступен — дефолт пропуск",
        )

    user = "\n".join(
        [
            f"Компания: {company or '—'}",
            f"Должность: {title or '—'}",
            "Переписка:",
            transcript,
        ]
    )
    content = ""
    try:
        content = await ports.llm().complete(
            "archive_disposition",
            system=_SYSTEM,
            user=user,
            temperature=0.0,
        )
        data = _extract_json(content)
        raw = str(data.get("disposition", "")).strip().lower()
        reasoning = str(data.get("reasoning", "")).strip()
        event(
            logger,
            "LLM",
            "archive_disposition: %s (vacancy_id=%s) — %s",
            raw or "не распознан",
            vacancy_id or "—",
            reasoning or "—",
            vacancy_id=vacancy_id,
            disposition=raw,
            reasoning=reasoning,
            fallback=raw not in ("rejected", "skipped"),
        )
        if raw in ("rejected", "skipped"):
            return ArchiveDispositionResult(disposition=raw, reasoning=reasoning)  # type: ignore[arg-type]
        logger.warning("archive_disposition: неизвестный disposition %r", raw)
    except (LlmError, json.JSONDecodeError, KeyError, TypeError) as exc:
        snippet = (content[:200] + "…") if content else "(пусто)"
        logger.warning("archive_disposition LLM failed: %s — %s", exc, snippet)
        event(
            logger,
            "LLM",
            "archive_disposition: сбой (vacancy_id=%s) — %s",
            vacancy_id or "—",
            exc,
            level=logging.WARNING,
            vacancy_id=vacancy_id,
            fallback=True,
            reasoning=str(exc),
        )

    return ArchiveDispositionResult(
        disposition="skipped",
        reasoning="fallback без LLM",
    )


__all__ = [
    "ArchiveDisposition",
    "ArchiveDispositionResult",
    "classify_archive_disposition",
]
