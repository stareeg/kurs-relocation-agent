"""Режим поиска: первоклассная сущность, которую читает вся система.

Два режима стартового набора (`paused`/`planning` приедут в CY-01 с сущностью цикла):
``active`` — активный поиск; ``passive`` — рассматриваю. Третий режим ``offer_endgame``
(«оффер на руках») убран (0094): наличие принятого оффера и так видно по воронке/разделу
«Офферы» — отдельный ручной тумблер под это дублировал факт, который система знает сама.
Хранение — журнал `search_state_log`: текущий режим = последняя запись, история не
перезаписывается (видно, кто и почему переключал).

Переход публикует `SearchModeChanged` на шину (через подписку пишется и в `career_timeline` —
см. `events.py`/`timeline.py`). Система никогда не переключает режим сама (ST-02 — только
предложение в очередь); здесь `actor="suggestion"` — это принятое владельцем предложение.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.kernel import ports
from core.kernel.events import SearchModeChanged
from core.platform.db.pool import Executor, get_pool, row_to_dict

SearchMode = Literal["active", "passive"]
SearchModeActor = Literal["owner", "suggestion"]

#: Стартовый режим свежей установки: журнал пуст → активный поиск.
DEFAULT_MODE: SearchMode = "active"

#: Человеческие названия для UI и журнала (русский канон продукта).
MODE_LABELS: dict[SearchMode, str] = {
    "active": "Активно ищу",
    "passive": "Рассматриваю",
}

_COLS = "id, mode, prev_mode, actor, reason, created_at"


class SearchStateEntry(BaseModel):
    """Одна запись журнала режима (переход или стартовое состояние)."""

    id: int | None = None
    mode: SearchMode
    prev_mode: SearchMode | None = None
    actor: SearchModeActor = "owner"
    reason: str = ""
    created_at: datetime | None = None


class SearchModeState(BaseModel):
    """Текущее состояние для API/UI: режим + подпись + когда переключён."""

    mode: SearchMode
    label: str = Field(min_length=1)
    since: datetime | None = None


def mode_label(mode: SearchMode) -> str:
    return MODE_LABELS[mode]


def _entry_from_row(row: object) -> SearchStateEntry:
    return SearchStateEntry(**row_to_dict(row))  # type: ignore[arg-type]


async def get_current_entry(
    *, account_id: int, db: Executor | None = None
) -> SearchStateEntry | None:
    """Последняя запись журнала аккаунта; None — на свежей установке (читай DEFAULT_MODE)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from search_state_log where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    return _entry_from_row(row) if row is not None else None


async def get_current_state(*, account_id: int, db: Executor | None = None) -> SearchModeState:
    """Текущий режим аккаунта с подписью. Пустой журнал = дефолт без записи в БД."""
    entry = await get_current_entry(account_id=account_id, db=db)
    mode = entry.mode if entry is not None else DEFAULT_MODE
    return SearchModeState(
        mode=mode,
        label=mode_label(mode),
        since=entry.created_at if entry is not None else None,
    )


async def list_mode_history(
    *, account_id: int, limit: int = 20, db: Executor | None = None
) -> list[SearchStateEntry]:
    """История переходов аккаунта (свежие первыми) — аудит и будущие предложения ST-02."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLS} from search_state_log where account_id = $1 "
        "order by created_at desc, id desc limit $2",
        account_id,
        capped,
    )
    return [_entry_from_row(r) for r in rows]


async def set_search_mode(
    mode: SearchMode,
    *,
    account_id: int,
    actor: SearchModeActor = "owner",
    reason: str = "",
    db: Executor | None = None,
) -> SearchStateEntry:
    """Переключить режим аккаунта: строка в журнал + событие `SearchModeChanged`.

    Повторный выбор текущего режима идемпотентен: новой записи (и события) нет —
    возвращается текущая строка. Событие публикуется и не ждётся: журнал и лента
    не должны задерживать ответ PATCH (подписчик надёжно догоняет фоном).
    """
    db = db or get_pool()
    current = await get_current_entry(account_id=account_id, db=db)
    if current is not None and current.mode == mode:
        return current

    prev_mode = current.mode if current is not None else None
    row = await db.fetchrow(
        "insert into search_state_log (account_id, mode, prev_mode, actor, reason) "
        f"values ($1, $2, $3, $4, $5) returning {_COLS}",
        account_id,
        mode,
        prev_mode,
        actor,
        reason.strip(),
    )
    assert row is not None
    entry = _entry_from_row(row)

    ports.events().publish(
        SearchModeChanged(
            mode=mode,
            prev_mode=prev_mode or "",
            actor=actor,
            reason=reason.strip(),
            account_id=account_id,
        )
    )
    return entry


__all__ = [
    "DEFAULT_MODE",
    "MODE_LABELS",
    "SearchMode",
    "SearchModeActor",
    "SearchModeState",
    "SearchStateEntry",
    "get_current_entry",
    "get_current_state",
    "list_mode_history",
    "mode_label",
    "set_search_mode",
]
