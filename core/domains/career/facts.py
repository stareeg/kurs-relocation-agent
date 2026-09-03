"""Долгая память кандидата: таблица `career_facts`.

Извлечение из разбора — детерминированно из `DebriefAnalysis` (без нового LLM).
Чтение — блок для prep/chat; протухшие (`expires_at`) не попадают в выборку.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.career.models import CareerFact, FactType
from core.domains.career.repo import insert_fact, list_active_facts, merge_fact
from core.kernel.events import InterviewDebriefed
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

#: Срок годности фактов из разбора (полгода) — потом не шумят в промпте.
_DEBRIEF_TTL = timedelta(days=180)
_MAX_FACTS_PER_DEBRIEF = 20
_PROMPT_FACTS_LIMIT = 20

_FACT_TYPE_RU = {
    "skill_gap": "пробел",
    "strength": "сила",
    "preference": "предпочтение",
    "constraint": "ограничение",
    "company": "компания",
    "note": "заметка",
    "other": "другое",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _source_ref_debrief(debrief_id: int | None, vacancy_id: str) -> str:
    if debrief_id is not None:
        return f"debrief:{debrief_id}"
    return (vacancy_id or "").strip()


def extract_facts_from_debrief_analysis(
    analysis: dict[str, Any],
    *,
    vacancy_id: str = "",
    stage: str = "",
    debrief_id: int | None = None,
    summary: str = "",
    recorded_at: datetime | None = None,
) -> list[CareerFact]:
    """Чистый маппер: jsonb analysis разбора → список `CareerFact` (без I/O)."""
    when = recorded_at or _utcnow()
    expires = when + _DEBRIEF_TTL
    source_ref = _source_ref_debrief(debrief_id, vacancy_id)
    base_payload = {
        "vacancy_id": vacancy_id,
        "stage": stage,
        "debrief_id": debrief_id,
    }
    out: list[CareerFact] = []
    seen: set[str] = set()

    def _add(
        text: str,
        fact_type: FactType,
        *,
        confidence: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        clean = " ".join(str(text).split()).strip()
        if not clean or clean in seen:
            return
        seen.add(clean)
        payload = {**base_payload, **(extra or {})}
        out.append(
            CareerFact(
                fact=clean,
                fact_type=fact_type,
                source_kind="debrief",
                source_ref=source_ref,
                confidence=confidence,
                recorded_at=when,
                expires_at=expires,
                payload=payload,
            )
        )

    for topic in analysis.get("topics_to_study") or []:
        topic_s = str(topic).strip()
        if topic_s:
            _add(
                f"Подтянуть: {topic_s}",
                "skill_gap",
                confidence=0.75,
                extra={"topic": topic_s},
            )

    for answer in analysis.get("strong_answers") or []:
        answer_s = str(answer).strip()
        if answer_s:
            _add(
                f"Сильный ответ: {answer_s}",
                "strength",
                confidence=0.8,
            )

    for weak in analysis.get("weak_answers") or []:
        if not isinstance(weak, dict):
            continue
        improve = str(weak.get("how_to_improve") or "").strip()
        question = str(weak.get("question") or "").strip()
        if improve:
            _add(
                f"Улучшить ответ: {improve}",
                "skill_gap",
                confidence=0.7,
                extra={"question": question},
            )
        elif question:
            _add(
                f"Слабо на вопросе: {question}",
                "skill_gap",
                confidence=0.65,
                extra={"question": question},
            )

    for item in analysis.get("competency_map") or []:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        level = str(item.get("level") or "").strip().lower()
        if not topic:
            continue
        if level == "weak":
            _add(
                f"Компетенция слабая: {topic}",
                "skill_gap",
                confidence=0.7,
                extra={"topic": topic, "level": level},
            )
        elif level == "confident":
            _add(
                f"Компетенция уверенная: {topic}",
                "strength",
                confidence=0.75,
                extra={"topic": topic, "level": level},
            )

    summary_s = (summary or str(analysis.get("summary") or "")).strip()
    if summary_s:
        _add(summary_s[:500], "note", confidence=0.6)

    return out[:_MAX_FACTS_PER_DEBRIEF]


def render_facts_block(facts: list[CareerFact]) -> str:
    """Непустой блок для промпта prep/chat. Пустой список → пустая строка."""
    if not facts:
        return ""
    lines: list[str] = []
    for fact in facts[:_PROMPT_FACTS_LIMIT]:
        label = _FACT_TYPE_RU.get(fact.fact_type, fact.fact_type)
        pct = int(round(fact.confidence * 100))
        lines.append(f"- [{label}] {fact.fact} ({pct}%)")
    body = "\n".join(lines)
    return (
        f"{body}\n\n"
        "Учитывай эти факты о кандидате из прошлых разборов и заметок. "
        "Не повторяй уже закрытые пробелы как будто они новые."
    )


def _topic_of(fact: CareerFact) -> str:
    return str(fact.payload.get("topic") or "").strip().lower()


async def _find_mergeable(
    new_fact: CareerFact, *, account_id: int, db: Executor | None
) -> CareerFact | None:
    """Активный факт того же `fact_type` с тем же `payload.topic` — цель мерджа (Этап 4.1):
    формулировка одного и того же сигнала меняется от разбора к разбору, поэтому ключ мерджа —
    заранее положенный `topic`, а не дословное сравнение текста."""
    topic = _topic_of(new_fact)
    if not topic:
        return None
    candidates = await list_active_facts(account_id=account_id, fact_type=new_fact.fact_type, db=db)
    for candidate in candidates:
        if _topic_of(candidate) == topic:
            return candidate
    return None


async def persist_facts(
    facts: list[CareerFact],
    *,
    account_id: int,
    db: Executor | None = None,
) -> list[CareerFact]:
    """Идемпотентно по теме (Этап 4.1 редизайна «Карьеры»): повторный разбор с тем же
    `fact_type` + `payload.topic` обновляет уже активный факт (текст/`recorded_at`/
    `confidence`/`source_ref`) вместо новой почти дословно повторяющей строки. Закреплённый
    факт (`expires_at=None`) при мердже остаётся закреплённым — новый срок годности не
    затирает ручное решение владельца."""
    saved: list[CareerFact] = []
    for fact in facts:
        existing = await _find_mergeable(fact, account_id=account_id, db=db)
        if existing is not None and existing.id is not None:
            saved.append(
                await merge_fact(
                    existing.id,
                    account_id=account_id,
                    fact=fact.fact,
                    confidence=fact.confidence,
                    source_ref=fact.source_ref,
                    recorded_at=fact.recorded_at,
                    expires_at=fact.expires_at if existing.expires_at is not None else None,
                    payload=fact.payload,
                    db=db,
                )
            )
        else:
            saved.append(await insert_fact(fact, account_id=account_id, db=db))
    return saved


async def record_facts_from_debrief(
    evt: InterviewDebriefed,
    *,
    account_id: int,
    db: Executor | None = None,
) -> list[CareerFact]:
    """Загрузить разбор по событию → извлечь факты → записать. Пусто = нечего писать."""
    from core.domains.preparation.debrief import get_debrief, load_debrief_history

    record = None
    if evt.debrief_id is not None:
        record = await get_debrief(evt.debrief_id, account_id=account_id, db=db)
    if record is None:
        vacancy_id = str(evt.vacancy_id or "").strip()
        if vacancy_id:
            history = await load_debrief_history(vacancy_id, limit=1, account_id=account_id, db=db)
            record = history[0] if history else None
    if record is None:
        return []

    facts = extract_facts_from_debrief_analysis(
        record.analysis or {},
        vacancy_id=record.vacancy_id,
        stage=record.stage or evt.stage,
        debrief_id=record.id,
        summary=record.summary or "",
        recorded_at=record.created_at,
    )
    if not facts:
        return []
    try:
        return await persist_facts(facts, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — память не валит разбор
        logger.warning("career_facts: не записаны из debrief_id=%s: %s", record.id, exc)
        return []


async def load_facts_context_block(
    *,
    account_id: int,
    limit: int = _PROMPT_FACTS_LIMIT,
    db: Executor | None = None,
) -> str:
    """Best-effort блок активных фактов для промпта. Нет PG → пусто."""
    try:
        facts = await list_active_facts(account_id=account_id, limit=limit, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("career_facts: чтение недоступно: %s", exc)
        return ""
    return render_facts_block(facts)


__all__ = [
    "extract_facts_from_debrief_analysis",
    "load_facts_context_block",
    "persist_facts",
    "record_facts_from_debrief",
    "render_facts_block",
]
