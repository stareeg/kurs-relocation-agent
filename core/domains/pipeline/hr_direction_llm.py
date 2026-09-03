"""LLM-фолбэк направления реплики HR-треда (`hr_in`/`hr_out`), когда DOM-эвристика
(`extension/src/dom/selectors.ts::_hrMessageDirection`) не нашла надёжного сигнала (EXT-H1).

Батч на весь тред, не на реплику: дешевле одного вызова на тред, и даёт LLM контекст соседних
уже классифицированных реплик — переписка обычно чередуется отправитель/получатель, сильный
сигнал даже без разметки. Если LLM недоступна/упала — возвращаем {} (тот же принцип, что
`stage_type_llm.py`/`funnel_status_llm.py`: без надёжного сигнала не угадываем), вызывающий код
(расширение) реплику просто пропускает, как и раньше.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from core.config import get_settings
from core.kernel import ports

logger = logging.getLogger(__name__)

_DirectionKind = Literal["hr_in", "hr_out"]


class ThreadMessageIn(BaseModel):
    """Одна реплика треда на входе классификатора: kind=None — нужно определить направление."""

    index: int
    kind: _DirectionKind | None = None
    body: str


class _DirectionResult(BaseModel):
    index: int = Field(description="Тот же index, что и у входной реплики с kind=null")
    kind: _DirectionKind


class _DirectionBatch(BaseModel):
    items: list[_DirectionResult] = Field(default_factory=list)


_SYSTEM_TEMPLATE = """Ты помощник Job Hunter — определяешь направление реплики в переписке кандидата с HR.
Кандидат — {identity}. Вторая сторона — рекрутер/HR/работодатель.

Значения направления:
- "hr_in" — писал рекрутер/HR (входящее для кандидата);
- "hr_out" — писал кандидат (владелец), исходящее.

Тебе даётся тред целиком, в хронологическом порядке. У части реплик направление уже известно
(kind заполнен) — это надёжный сигнал от разметки страницы, не оспаривай его. У части реплик
kind=null — определи направление именно для них, используя как контекст соседние реплики с
известным направлением (переписка обычно чередуется HR/кандидат) и содержание (вопросы про
вакансию/условия/оффер обычно от HR, ответы про свой опыт/готовность/согласие — от кандидата).

Верни ТОЛЬКО реплики, у которых был kind=null (по их index), с определённым направлением. Если
контекста для какой-то реплики совсем недостаточно — всё равно выбери наиболее вероятное
направление, не пропускай её."""


def _format_thread(messages: list[ThreadMessageIn]) -> str:
    lines = []
    for m in messages:
        tag = m.kind or "null"
        lines.append(f"[{m.index}] ({tag}) {m.body[:1000]}")
    return "\n".join(lines)


async def classify_hr_directions_llm(
    messages: list[ThreadMessageIn],
    *,
    account_id: int,
    llm: ports.LlmPort | None = None,
) -> dict[int, str]:
    """Батч-классификация направления реплик с kind=None.

    Возвращает {index: "hr_in"|"hr_out"} только для реплик, у которых входной kind был None
    (остальные индексы игнорируются, даже если LLM вернула их). {} — реплик с kind=None нет,
    LLM недоступна (нет API key) или упала — в любом из случаев вызывающий код падает на прежний
    fallback (пропуск неопознанной реплики).

    `llm` — подмена порта в тестах; по умолчанию связанный порт процесса. `account_id` — чьё
    резюме подставлять в identity (S-critical 2026-08-26: раньше брали резюме владельца
    инсталляции для любого аккаунта, см. `core.domains.pipeline.cover_letter`).
    """
    unresolved_idx = {m.index for m in messages if m.kind is None}
    if not unresolved_idx:
        return {}
    if not get_settings().openrouter_api_key:
        return {}

    from core.domains.opportunities.prompt import load_candidate_identity
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    user = _format_thread(messages)
    system = _SYSTEM_TEMPLATE.format(identity=load_candidate_identity(data=resume_data))
    try:
        port = llm or ports.llm()
        result = await port.structured(
            "hr_direction",
            schema=_DirectionBatch,
            system=system,
            user=user,
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort фолбэк, сеть/схема не должны ронять синк
        logger.warning("hr-direction: батч-классификация не удалась: %s", exc)
        return {}

    resolved: dict[int, str] = {}
    for item in result.items:
        if item.index in unresolved_idx:
            resolved[item.index] = item.kind
    return resolved


__all__ = ["ThreadMessageIn", "classify_hr_directions_llm"]
