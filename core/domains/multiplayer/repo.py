"""Репозиторий лобби: mp_rooms / mp_seats (миграция 0151)."""

from __future__ import annotations

import json
from typing import Any

from core.domains.multiplayer.models import (
    RoomMode,
    RoomSeatView,
    RoomSettings,
    SeatKind,
)
from core.platform.db.pool import Executor, get_pool, row_to_dict

_ROOM_COLS = (
    "id, code, name, host_account_id, pin_hash, status, mode, settings, "
    "phase_label, created_at, updated_at"
)
_SEAT_COLS = (
    "id, room_id, account_id, seat_kind, seat_index, role_public, role_secret, is_bot, joined_at"
)


def seat_view_from_row(row: Any) -> RoomSeatView:
    d = row_to_dict(row)
    return RoomSeatView(
        id=int(d["id"]),
        seat_kind=SeatKind(d["seat_kind"]),
        seat_index=int(d["seat_index"]),
        account_id=int(d["account_id"]) if d.get("account_id") is not None else None,
        role_public=str(d.get("role_public") or "waiting"),
        is_bot=bool(d.get("is_bot")),
    )


def settings_from_json(raw: Any) -> RoomSettings:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        return RoomSettings()
    return RoomSettings.model_validate(raw)


async def insert_room(
    *,
    code: str,
    name: str,
    host_account_id: int,
    pin_hash: str | None,
    mode: RoomMode,
    settings: RoomSettings,
    db: Executor | None = None,
) -> dict[str, Any]:
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into mp_rooms "
        "(code, name, host_account_id, pin_hash, status, mode, settings) "
        f"values ($1, $2, $3, $4, 'open', $5, $6::jsonb) returning {_ROOM_COLS}",
        code,
        name.strip(),
        host_account_id,
        pin_hash,
        mode.value,
        json.dumps(settings.model_dump()),
    )
    assert row is not None
    return row_to_dict(row)


async def insert_seat(
    *,
    room_id: int,
    account_id: int | None,
    # `str` — потому что generic-хаб (session.py) больше не знает игровых enum'ов (Э17);
    # значения те же, что в SeatKind (это StrEnum, в БД уходит его строка).
    seat_kind: SeatKind | str,
    seat_index: int,
    is_bot: bool = False,
    db: Executor | None = None,
) -> dict[str, Any]:
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into mp_seats "
        "(room_id, account_id, seat_kind, seat_index, is_bot) "
        f"values ($1, $2, $3, $4, $5) returning {_SEAT_COLS}",
        room_id,
        account_id,
        # SeatKind — StrEnum, так что str() даёт ровно то же значение, что и .value.
        str(seat_kind),
        seat_index,
        is_bot,
    )
    assert row is not None
    return row_to_dict(row)


async def get_room_by_code(code: str, *, db: Executor | None = None) -> dict[str, Any] | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_ROOM_COLS} from mp_rooms where code = $1",
        code.upper().strip(),
    )
    return row_to_dict(row) if row is not None else None


async def get_room_by_id(room_id: int, *, db: Executor | None = None) -> dict[str, Any] | None:
    db = db or get_pool()
    row = await db.fetchrow(f"select {_ROOM_COLS} from mp_rooms where id = $1", room_id)
    return row_to_dict(row) if row is not None else None


async def list_open_rooms(*, limit: int = 50, db: Executor | None = None) -> list[dict[str, Any]]:
    """Открытые и играющие столы — в лобби можно войти mid-match."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_ROOM_COLS} from mp_rooms where status in ('open', 'playing') "
        "order by created_at desc limit $1",
        limit,
    )
    return [row_to_dict(r) for r in rows]


async def count_rooms(*, db: Executor | None = None) -> int:
    """Счётчик всех столов (для автоимени «Стол №N»)."""
    db = db or get_pool()
    row = await db.fetchrow("select count(*)::int as n from mp_rooms")
    return int(row["n"]) if row is not None else 0


async def count_active_rooms_for_host(host_account_id: int, *, db: Executor | None = None) -> int:
    """Сколько open|playing столов у хоста (лимит Э14)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select count(*)::int as n from mp_rooms "
        "where host_account_id = $1 and status in ('open', 'playing')",
        host_account_id,
    )
    return int(row["n"]) if row is not None else 0


async def list_idle_room_ids(
    *,
    older_than_hours: float,
    limit: int = 100,
    db: Executor | None = None,
) -> list[dict[str, Any]]:
    """Столы open|playing без активности дольше TTL (по updated_at)."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_ROOM_COLS} from mp_rooms "
        "where status in ('open', 'playing') "
        "  and updated_at < now() - ($1::float * interval '1 hour') "
        "order by updated_at asc limit $2",
        older_than_hours,
        limit,
    )
    return [row_to_dict(r) for r in rows]


async def update_room_settings(
    room_id: int,
    settings: RoomSettings,
    *,
    db: Executor | None = None,
) -> None:
    db = db or get_pool()
    await db.execute(
        "update mp_rooms set settings = $2::jsonb, updated_at = now() where id = $1",
        room_id,
        json.dumps(settings.model_dump()),
    )


async def list_seats(room_id: int, *, db: Executor | None = None) -> list[dict[str, Any]]:
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_SEAT_COLS} from mp_seats where room_id = $1 order by seat_kind, seat_index",
        room_id,
    )
    return [row_to_dict(r) for r in rows]


async def find_seat_for_account(
    room_id: int, account_id: int, *, db: Executor | None = None
) -> dict[str, Any] | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_SEAT_COLS} from mp_seats where room_id = $1 and account_id = $2",
        room_id,
        account_id,
    )
    return row_to_dict(row) if row is not None else None


async def claim_empty_candidate_seat(
    room_id: int,
    account_id: int,
    *,
    db: Executor | None = None,
) -> dict[str, Any] | None:
    """Занять пустой слот кандидата (account_id IS NULL, не бот)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = $2, is_bot = false, joined_at = now() "
        "where id = ("
        "  select id from mp_seats "
        "  where room_id = $1 and seat_kind = 'candidate' "
        "    and account_id is null and is_bot = false "
        "  order by seat_index for update skip locked limit 1"
        f") returning {_SEAT_COLS}",
        room_id,
        account_id,
    )
    return row_to_dict(row) if row is not None else None


async def claim_joinable_candidate_seat(
    room_id: int,
    account_id: int,
    *,
    db: Executor | None = None,
) -> dict[str, Any] | None:
    """Занять свободный слот: сначала пустой, иначе LLM-бот (для mid-join друга)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = $2, is_bot = false, role_public = 'waiting', "
        "joined_at = now() "
        "where id = ("
        "  select id from mp_seats "
        "  where room_id = $1 and seat_kind = 'candidate' "
        "    and account_id is null "
        "  order by is_bot asc, seat_index "
        "  for update skip locked limit 1"
        f") returning {_SEAT_COLS}",
        room_id,
        account_id,
    )
    return row_to_dict(row) if row is not None else None


async def code_exists(code: str, *, db: Executor | None = None) -> bool:
    db = db or get_pool()
    row = await db.fetchrow("select 1 from mp_rooms where code = $1", code)
    return row is not None


async def update_room_playing(
    room_id: int, *, phase_label: str, db: Executor | None = None
) -> None:
    db = db or get_pool()
    await db.execute(
        "update mp_rooms set status = 'playing', phase_label = $2, updated_at = now() "
        "where id = $1",
        room_id,
        phase_label,
    )


async def update_phase_label(room_id: int, phase_label: str, *, db: Executor | None = None) -> None:
    db = db or get_pool()
    await db.execute(
        "update mp_rooms set phase_label = $2, updated_at = now() where id = $1",
        room_id,
        phase_label,
    )


async def close_room(room_id: int, *, db: Executor | None = None) -> dict[str, Any] | None:
    """Пометить стол закрытым; возвращает обновлённую строку или None."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_rooms set status = 'closed', phase_label = 'закрыт', updated_at = now() "
        f"where id = $1 and status <> 'closed' returning {_ROOM_COLS}",
        room_id,
    )
    return row_to_dict(row) if row is not None else None


async def claim_candidate_by_index(
    room_id: int,
    seat_index: int,
    account_id: int,
    *,
    db: Executor | None = None,
) -> dict[str, Any] | None:
    """Занять конкретный пустой слот кандидата (mid-join / promote)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = $3, is_bot = false, joined_at = now() "
        "where room_id = $1 and seat_kind = 'candidate' and seat_index = $2 "
        "  and account_id is null "
        f"returning {_SEAT_COLS}",
        room_id,
        seat_index,
        account_id,
    )
    return row_to_dict(row) if row is not None else None


async def delete_spectator_for_account(
    room_id: int, account_id: int, *, db: Executor | None = None
) -> None:
    db = db or get_pool()
    await db.execute(
        "delete from mp_seats where room_id = $1 and account_id = $2 and seat_kind = 'spectator'",
        room_id,
        account_id,
    )


async def mark_account_seat_bot(
    room_id: int, account_id: int, *, db: Executor | None = None
) -> dict[str, Any] | None:
    """Дисконнект истёк: слот остаётся, но играет бот (account_id сбрасываем)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = null, is_bot = true, role_public = 'bot' "
        "where room_id = $1 and account_id = $2 "
        f"returning {_SEAT_COLS}",
        room_id,
        account_id,
    )
    return row_to_dict(row) if row is not None else None


async def clear_candidate_to_empty(
    room_id: int, seat_index: int, *, db: Executor | None = None
) -> dict[str, Any] | None:
    """Kick: освободить слот кандидата под mid-join."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = null, is_bot = false, role_public = 'waiting' "
        "where room_id = $1 and seat_kind = 'candidate' and seat_index = $2 "
        f"returning {_SEAT_COLS}",
        room_id,
        seat_index,
    )
    return row_to_dict(row) if row is not None else None


async def set_candidate_bot(
    room_id: int, seat_index: int, *, db: Executor | None = None
) -> dict[str, Any] | None:
    """Добор бота на пустой слот."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update mp_seats set account_id = null, is_bot = true, role_public = 'bot' "
        "where room_id = $1 and seat_kind = 'candidate' and seat_index = $2 "
        f"returning {_SEAT_COLS}",
        room_id,
        seat_index,
    )
    return row_to_dict(row) if row is not None else None


async def transfer_hr_seat(
    room_id: int,
    *,
    to_account_id: int,
    from_account_id: int | None,
    db: Executor | None = None,
) -> None:
    """Назначить хрюшу: to занимает hr; from (если был) → spectator."""
    db = db or get_pool()
    await db.execute(
        "update mp_seats set account_id = $2, is_bot = false, role_public = 'waiting' "
        "where room_id = $1 and seat_kind = 'hr'",
        room_id,
        to_account_id,
    )
    await db.execute(
        "delete from mp_seats where room_id = $1 and account_id = $2 and seat_kind = 'spectator'",
        room_id,
        to_account_id,
    )
    if from_account_id is not None and from_account_id != to_account_id:
        # бывший hr → зритель
        specs = await db.fetchval(
            "select count(*) from mp_seats where room_id = $1 and seat_kind = 'spectator'",
            room_id,
        )
        await db.execute(
            "insert into mp_seats (room_id, account_id, seat_kind, seat_index, is_bot) "
            "values ($1, $2, 'spectator', $3, false)",
            room_id,
            from_account_id,
            int(specs or 0),
        )
