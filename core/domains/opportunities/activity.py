"""Лента действий по вакансии: короткие подписи из фактов, без LLM-текста.

Чистые функции: на вход — уже загруженные строки воронки/скора/пропуска/этапов, на выход —
список событий для дровера. I/O живёт в `core.app.scenarios.vacancy_activity` (кросс-домен).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

# Короткие ярлыки этапов собеса / разбора — локальная копия канона preparation, чтобы
# opportunities не импортировал соседний домен (A-10).
_STAGE_TYPE_LABELS: dict[str, str] = {
    "hr_screening": "HR-скрининг",
    "live_coding": "Live coding",
    "system_design": "System design",
    "theory": "Теория",
    "soft_skills": "Soft skills",
    "manager": "Менеджер",
    "business_case": "Бизнес-кейс",
    "final": "Финал",
    "screening": "HR-скрининг",
    "tech": "Техничка",
    "hr_final": "HR-финал",
    "other": "Другое",
}

_CANONICAL_SKIP: frozenset[str] = frozenset(
    {
        "Низкий грейд",
        "Низкая зарплата",
        "Не тот стек/домен",
        "Не тот формат",
        "Не та роль (IC vs рук)",
        "Избегать компанию",
    }
)


class ActivityItem(BaseModel):
    """Одно событие ленты: время + короткая подпись, без обоснований модели."""

    id: str
    kind: str
    at: datetime
    label: str
    source: str = ""


def _stage_label(raw: str) -> str:
    key = (raw or "").strip()
    return _STAGE_TYPE_LABELS.get(key, key or "этап")


def _is_auto_apply(source: str) -> bool:
    return (source or "").startswith("auto_apply")


def funnel_items(
    rows: list[tuple[int | None, str, str, datetime | None]],
) -> list[ActivityItem]:
    """Переходы воронки. `rows` — (id, stage, source, changed_at) по возрастанию времени."""
    items: list[ActivityItem] = []
    prev = ""
    for row_id, stage, source, changed_at in rows:
        name = (stage or "").strip()
        if not name or changed_at is None:
            continue
        if name == prev:
            continue
        if _is_auto_apply(source) and name == "Отклик":
            label = "Автоотклик" if not prev else f"{prev} → автоотклик"
        elif prev:
            label = f"{prev} → {name}"
        else:
            label = name
        items.append(
            ActivityItem(
                id=f"funnel:{row_id or len(items)}",
                kind="funnel",
                at=changed_at,
                label=label,
                source=source or "",
            )
        )
        prev = name
    return items


def score_items(
    rows: list[tuple[int | None, int, int, str, datetime | None]],
) -> list[ActivityItem]:
    """Ревизии скора. `rows` — (id, overall_score, delta, basis, created_at), любые по порядку.

    Подпись — только числа и «HR», без rationale: это LLM-текст, в ленте он шум.
    """
    dated = [(i, score, delta, basis, at) for i, score, delta, basis, at in rows if at is not None]
    dated.sort(key=lambda r: (r[4], r[0] or 0))
    items: list[ActivityItem] = []
    prev: int | None = None
    for row_id, score, delta, basis, at in dated:
        if prev is not None and score == prev and not delta:
            continue
        label = f"Скор {score}" if prev is None or score == prev else f"Скор {prev} → {score}"
        if basis == "hr_confirmed":
            label += " · HR"
        items.append(
            ActivityItem(
                id=f"score:{row_id or len(items)}",
                kind="score",
                at=at,
                label=label,
            )
        )
        prev = score
    return items


def score_fallback(overall: int | None, scored_at: datetime | None) -> list[ActivityItem]:
    """Нет ревизий — одна строка по текущему баллу (старые вакансии до score_revisions)."""
    if overall is None or scored_at is None:
        return []
    return [ActivityItem(id="score:current", kind="score", at=scored_at, label=f"Скор {overall}")]


def skip_item(
    *,
    reason: str,
    canonical: str | None,
    at: datetime | None,
    row_id: int | None = None,
) -> ActivityItem | None:
    if at is None:
        return None
    extra = (canonical or "").strip() or (reason or "").strip()
    label = f"Пропущено · {extra}" if extra in _CANONICAL_SKIP else "Пропущено"
    return ActivityItem(
        id=f"skip:{row_id or 0}",
        kind="skip",
        at=at,
        label=label,
    )


def hr_view_item(at: datetime | None) -> ActivityItem | None:
    if at is None:
        return None
    return ActivityItem(id="hr_view", kind="hr_view", at=at, label="HR открыл резюме")


def interview_items(
    rows: list[tuple[int | None, str, datetime | None]],
) -> list[ActivityItem]:
    """Добавление этапа собеса. `rows` — (id, stage_type, created_at)."""
    items: list[ActivityItem] = []
    for row_id, stage_type, created_at in rows:
        if created_at is None:
            continue
        items.append(
            ActivityItem(
                id=f"interview:{row_id or len(items)}",
                kind="interview",
                at=created_at,
                label=f"Этап: {_stage_label(stage_type)}",
            )
        )
    return items


def debrief_items(
    rows: list[tuple[int | None, str, datetime | None]],
) -> list[ActivityItem]:
    """Разбор собеса. `rows` — (id, stage, created_at). Без summary/анализа."""
    items: list[ActivityItem] = []
    for row_id, stage, created_at in rows:
        if created_at is None:
            continue
        items.append(
            ActivityItem(
                id=f"debrief:{row_id or len(items)}",
                kind="debrief",
                at=created_at,
                label=f"Разбор: {_stage_label(stage)}",
            )
        )
    return items


def offer_item(at: datetime | None) -> ActivityItem | None:
    if at is None:
        return None
    return ActivityItem(id="offer", kind="offer", at=at, label="Оффер")


def merge_activity(*groups: Sequence[ActivityItem | None]) -> list[ActivityItem]:
    """Свежие сверху; стабильный порядок при равном времени — по kind, затем id."""
    items = [it for group in groups for it in group if it is not None]
    items.sort(key=lambda it: (it.at, it.kind, it.id), reverse=True)
    return items


__all__ = [
    "ActivityItem",
    "debrief_items",
    "funnel_items",
    "hr_view_item",
    "interview_items",
    "merge_activity",
    "offer_item",
    "score_fallback",
    "score_items",
    "skip_item",
]
