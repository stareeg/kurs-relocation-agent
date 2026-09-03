"""Журнал треков поиска: основная работа и опционально вторая.

Форма — копия `search_state.py`: текущий набор = последняя запись, история не
перезаписывается. `primary` тумблером не выключается (это делает режим `passive`).
Повторный выбор того же набора идемпотентен: новой строки и события нет.

Переход публикует `SearchTrackChanged` (лента + перескор доски + сброс кэша ситуации).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.kernel import ports
from core.kernel.events import SearchTrackChanged
from core.kernel.schemas.track import (
    DEFAULT_TRACKS,
    TRACK_LABELS,
    SearchTrack,
    normalize_tracks,
    track_labels,
)
from core.platform.db.pool import Executor, get_pool, row_to_dict

SearchTrackActor = Literal["owner", "suggestion"]

_COLS = "id, tracks, prev_tracks, actor, reason, created_at"


class TrackStateEntry(BaseModel):
    """Одна запись журнала треков (переход или стартовое состояние)."""

    id: int | None = None
    tracks: list[SearchTrack]
    prev_tracks: list[SearchTrack] = Field(default_factory=list)
    actor: SearchTrackActor = "owner"
    reason: str = ""
    created_at: datetime | None = None


class TrackState(BaseModel):
    """Текущее состояние для API/UI: набор + подписи + производный флаг второй работы."""

    tracks: list[SearchTrack]
    labels: list[str]
    second_job_enabled: bool
    since: datetime | None = None


def _entry_from_row(row: object) -> TrackStateEntry:
    raw = row_to_dict(row)  # type: ignore[arg-type]
    stored_prev = [str(x) for x in (raw.get("prev_tracks") or ())]
    raw["tracks"] = normalize_tracks([str(x) for x in (raw.get("tracks") or ())])
    # Пустой prev в журнале — не «только primary», а «журнала ещё не было».
    raw["prev_tracks"] = normalize_tracks(stored_prev) if stored_prev else []
    return TrackStateEntry(**raw)  # type: ignore[arg-type]


def _state_from_tracks(tracks: Sequence[SearchTrack], *, since: datetime | None) -> TrackState:
    canon = normalize_tracks(list(tracks))
    return TrackState(
        tracks=canon,
        labels=track_labels(canon),
        second_job_enabled="second_job" in canon,
        since=since,
    )


async def get_current_entry(
    *, account_id: int, db: Executor | None = None
) -> TrackStateEntry | None:
    """Последняя запись журнала аккаунта; None — на свежей установке (читай DEFAULT_TRACKS)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from search_track_log where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    return _entry_from_row(row) if row is not None else None


async def get_current_tracks(*, account_id: int, db: Executor | None = None) -> TrackState:
    """Текущий набор треков аккаунта. Пустой журнал = только основная работа, без строки в БД."""
    entry = await get_current_entry(account_id=account_id, db=db)
    if entry is None:
        return _state_from_tracks(DEFAULT_TRACKS, since=None)
    return _state_from_tracks(entry.tracks, since=entry.created_at)


async def set_tracks(
    tracks: Sequence[str],
    *,
    account_id: int,
    actor: SearchTrackActor = "owner",
    reason: str = "",
    db: Executor | None = None,
) -> TrackStateEntry:
    """Переключить набор треков: строка в журнал + событие `SearchTrackChanged`.

    `primary` всегда остаётся. Повторный выбор текущего набора идемпотентен: новой
    записи (и события) нет — возвращается текущая строка. Событие публикуется и не
    ждётся: журнал и лента не должны задерживать ответ PATCH.
    """
    db = db or get_pool()
    canon = normalize_tracks(list(tracks))
    current = await get_current_entry(account_id=account_id, db=db)
    if current is not None and current.tracks == canon:
        return current

    prev = list(current.tracks) if current is not None else []
    row = await db.fetchrow(
        "insert into search_track_log (account_id, tracks, prev_tracks, actor, reason) "
        f"values ($1, $2, $3, $4, $5) returning {_COLS}",
        account_id,
        canon,
        prev,
        actor,
        reason.strip(),
    )
    assert row is not None
    entry = _entry_from_row(row)

    ports.events().publish(
        SearchTrackChanged(
            tracks=tuple(canon),
            prev_tracks=tuple(prev),
            actor=actor,
            reason=reason.strip(),
            account_id=account_id,
        )
    )
    return entry


async def set_second_job_enabled(
    enabled: bool,
    *,
    account_id: int,
    actor: SearchTrackActor = "owner",
    reason: str = "",
    db: Executor | None = None,
) -> TrackStateEntry:
    """Продуктовая ручка: включить/выключить вторую работу, не трогая основную."""
    tracks: list[SearchTrack] = ["primary", "second_job"] if enabled else ["primary"]
    return await set_tracks(tracks, account_id=account_id, actor=actor, reason=reason, db=db)


__all__ = [
    "DEFAULT_TRACKS",
    "TRACK_LABELS",
    "SearchTrack",
    "SearchTrackActor",
    "TrackState",
    "TrackStateEntry",
    "get_current_entry",
    "get_current_tracks",
    "set_second_job_enabled",
    "set_tracks",
]
