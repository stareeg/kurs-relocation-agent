"""Сервис лобби «Хрюши и Волки»: создать / список / join / закрыть по коду."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import date

from core.domains.multiplayer import repo
from core.domains.multiplayer.deck import daily_ordinal
from core.domains.multiplayer.limits import (
    MAX_ACTIVE_ROOMS_PER_HOST,
    allow_create,
    allow_join,
)
from core.domains.multiplayer.models import (
    JoinAs,
    RoomMode,
    RoomOut,
    RoomSeatView,
    RoomSettings,
    RoomStatus,
    SeatKind,
)
from core.platform.observability import event
from core.platform.repo.accounts import get_account_by_id

logger = logging.getLogger(__name__)

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PIN_PREFIX = "mp_pin:"
DEFAULT_CANDIDATE_SLOTS = 2
MAX_CANDIDATE_SLOTS = 6


class LobbyError(Exception):
    """Ошибка лобби с HTTP-кодом для роутера."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def sanitize_nick(raw: str | None) -> str | None:
    """Ник за столом: 2–24 символа, без пробелов по краям. Не ФИО."""
    if raw is None:
        return None
    s = " ".join(str(raw).split()).strip()
    if len(s) < 2:
        return None
    return s[:24]


async def resolve_nick(*, account_id: int, nick: str | None) -> str:
    """Явный nick → иначе @telegram → иначе «игрок{id}»."""
    cleaned = sanitize_nick(nick)
    if cleaned:
        return cleaned
    try:
        acc = await get_account_by_id(account_id)
    except Exception:  # noqa: BLE001
        acc = None
    if acc is not None and acc.telegram_username:
        return f"@{acc.telegram_username}"[:24]
    return f"игрок{account_id}"


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def hash_pin(pin: str) -> str:
    """Хэш PIN для хранения (не обратимый)."""
    return hashlib.sha256(f"{_PIN_PREFIX}{pin}".encode()).hexdigest()


def verify_pin(pin: str | None, pin_hash: str | None) -> bool:
    if not pin_hash:
        return True
    if not pin:
        return False
    return secrets.compare_digest(hash_pin(pin), pin_hash)


def _seat_counts(seats: list[dict], *, candidate_slots: int) -> tuple[int, int, int]:
    """(seats_total, seats_taken, seats_free).

    Free = слот без живого игрока (пустой или LLM-бот) — туда можно сесть.
    """
    total = 1 + candidate_slots  # хрюша + кандидаты
    taken = 0
    for s in seats:
        kind = s.get("seat_kind")
        if kind not in ("hr", "candidate"):
            continue
        if s.get("account_id") is not None:
            taken += 1
    free = max(0, total - taken)
    return total, taken, free


def build_room_out(
    room: dict,
    seats: list[dict],
    *,
    viewer_account_id: int | None = None,
) -> RoomOut:
    settings = repo.settings_from_json(room.get("settings"))
    candidate_slots = settings.candidate_slots
    total, taken, free = _seat_counts(seats, candidate_slots=candidate_slots)
    nicks = settings.nicks or {}
    views: list[RoomSeatView] = []
    for s in seats:
        view = repo.seat_view_from_row(s)
        aid = view.account_id
        if aid is not None:
            view = view.model_copy(update={"nick": nicks.get(str(aid))})
        elif view.is_bot:
            view = view.model_copy(update={"nick": "бот"})
        views.append(view)
    my_seat_id: int | None = None
    my_kind: SeatKind | None = None
    if viewer_account_id is not None:
        for s in seats:
            if s.get("account_id") == viewer_account_id:
                my_seat_id = int(s["id"])
                my_kind = SeatKind(s["seat_kind"])
                break
    return RoomOut(
        id=int(room["id"]),
        code=str(room["code"]),
        name=str(room["name"]),
        host_account_id=int(room["host_account_id"]),
        status=RoomStatus(room["status"]),
        mode=RoomMode(room["mode"]),
        has_pin=bool(room.get("pin_hash")),
        phase_label=str(room.get("phase_label") or "лобби"),
        seats_total=total,
        seats_free=free,
        seats_taken=taken,
        candidate_slots=candidate_slots,
        settings=settings,
        seats=views,
        my_seat_id=my_seat_id,
        my_seat_kind=my_kind,
    )


async def _next_table_name() -> str:
    n = await repo.count_rooms()
    return f"Стол №{n + 1}"


async def _set_nick(
    room_id: int, settings: RoomSettings, account_id: int, nick: str
) -> RoomSettings:
    nicks = dict(settings.nicks)
    nicks[str(account_id)] = nick
    updated = settings.model_copy(update={"nicks": nicks})
    await repo.update_room_settings(room_id, updated)
    return updated


async def create_room(
    *,
    account_id: int,
    name: str | None = None,
    mode: RoomMode = RoomMode.FRIENDS,
    slots: int = DEFAULT_CANDIDATE_SLOTS,
    pin: str | None = None,
    friends_only: bool = False,
    daily: bool = False,
    nick: str | None = None,
) -> RoomOut:
    """Создать стол: хост = хрюша; слоты кандидатов с LLM-ботами; стол виден всем."""
    if not allow_create(account_id):
        raise LobbyError(429, "Слишком часто создаёте столы — подождите минуту")

    active = await repo.count_active_rooms_for_host(account_id)
    if active >= MAX_ACTIVE_ROOMS_PER_HOST:
        raise LobbyError(
            429,
            f"Лимит столов: не больше {MAX_ACTIVE_ROOMS_PER_HOST} открытых на аккаунт. "
            "Закройте старый стол.",
        )

    daily_day: str | None = None
    fill_bots = True
    _ = friends_only  # legacy API; стол всегда публичный
    if daily:
        mode = RoomMode.SOLO
        pin = None
        today = date.today()
        daily_day = today.isoformat()
        name = f"День #{daily_ordinal(day=today)}"
        slots = max(DEFAULT_CANDIDATE_SLOTS, min(slots, MAX_CANDIDATE_SLOTS))
    else:
        # Единый публичный стол: боты + mid-join любого аккаунта.
        mode = RoomMode.FRIENDS
        pin = None
        slots = DEFAULT_CANDIDATE_SLOTS
        name = name or await _next_table_name()

    if mode == RoomMode.SOLO:
        pin = None

    host_nick = await resolve_nick(account_id=account_id, nick=nick)
    settings = RoomSettings(
        candidate_slots=slots,
        friends_only=False,
        daily_day=daily_day,
        nicks={str(account_id): host_nick},
    )
    pin_hash = hash_pin(pin) if pin else None
    room: dict | None = None
    code = ""
    for _ in range(8):
        code = _generate_code()
        if await repo.code_exists(code):
            continue
        try:
            room = await repo.insert_room(
                code=code,
                name=name,
                host_account_id=account_id,
                pin_hash=pin_hash,
                mode=mode,
                settings=settings,
            )
            break
        except Exception:
            continue
    if room is None:
        raise LobbyError(500, "Не удалось сгенерировать код стола")

    room_id = int(room["id"])
    await repo.insert_seat(
        room_id=room_id,
        account_id=account_id,
        seat_kind=SeatKind.HR,
        seat_index=0,
    )
    for i in range(slots):
        await repo.insert_seat(
            room_id=room_id,
            account_id=None,
            seat_kind=SeatKind.CANDIDATE,
            seat_index=i,
            is_bot=fill_bots,
        )

    seats = await repo.list_seats(room_id)
    event(
        logger,
        "ЗАДАЧА",
        "mp_room_created code=%s mode=%s slots=%s friends_only=%s pin=%s daily=%s",
        code,
        mode.value,
        slots,
        False,
        bool(pin_hash),
        daily_day,
        room_code=code,
        account_id=account_id,
        mode=mode.value,
    )
    return build_room_out(room, seats, viewer_account_id=account_id)


async def list_rooms(*, account_id: int, limit: int = 50) -> list[RoomOut]:
    """Все open|playing столы — видны любому аккаунту (не только друзьям)."""
    rooms = await repo.list_open_rooms(limit=limit)
    out: list[RoomOut] = []
    for room in rooms:
        seats = await repo.list_seats(int(room["id"]))
        out.append(build_room_out(room, seats, viewer_account_id=account_id))
    return out


async def _sync_player_join_to_session(
    *,
    room_code: str,
    account_id: int,
    seat_index: int,
    nick: str | None = None,
) -> None:
    """Если партия уже в хабе — привязать игрока к engine-seat (замена бота/пусто)."""
    try:
        from core.domains.multiplayer.session import apply_human_takeover, hub

        session = hub().get(room_code)
        if session is None:
            return
        if nick:
            session.nicks[account_id] = nick
        await apply_human_takeover(session, account_id=account_id, seat_index=seat_index)
    except Exception:  # noqa: BLE001
        logger.exception("mp_join_sync_failed code=%s account=%s", room_code, account_id)


async def join_room(
    *,
    account_id: int,
    code: str,
    join_as: JoinAs = JoinAs.PLAYER,
    pin: str | None = None,
    nick: str | None = None,
) -> RoomOut:
    """Войти: игрок на свободный/бот-слот; если все люди — зритель (auto). Публично."""
    if not allow_join(account_id):
        raise LobbyError(429, "Слишком частые входы — подождите немного")

    room = await repo.get_room_by_code(code)
    if room is None:
        raise LobbyError(404, "Стол не найден")
    if room["status"] == RoomStatus.CLOSED.value:
        raise LobbyError(410, "Стол распущен")

    room_id = int(room["id"])
    settings = repo.settings_from_json(room.get("settings"))
    table_nick = await resolve_nick(account_id=account_id, nick=nick)

    existing = await repo.find_seat_for_account(room_id, account_id)
    if existing is not None:
        settings = await _set_nick(room_id, settings, account_id, table_nick)
        room = {**room, "settings": settings.model_dump()}
        seats = await repo.list_seats(room_id)
        return build_room_out(room, seats, viewer_account_id=account_id)

    # friends_only больше не блокирует: стол виден и доступен всем аккаунтам.
    if not verify_pin(pin, room.get("pin_hash")):
        raise LobbyError(403, "Неверный PIN")

    effective = join_as
    if effective == JoinAs.PLAYER:
        claimed = await repo.claim_joinable_candidate_seat(room_id, account_id)
        if claimed is None:
            effective = JoinAs.SPECTATOR
        else:
            settings = await _set_nick(room_id, settings, account_id, table_nick)
            room = {**room, "settings": settings.model_dump()}
            await _sync_player_join_to_session(
                room_code=str(room["code"]),
                account_id=account_id,
                seat_index=int(claimed["seat_index"]),
                nick=table_nick,
            )
            seats = await repo.list_seats(room_id)
            event(
                logger,
                "ЗАДАЧА",
                "mp_room_joined code=%s as=player seat=%s",
                room["code"],
                claimed["seat_index"],
                room_code=room["code"],
                account_id=account_id,
                join_as="player",
            )
            return build_room_out(room, seats, viewer_account_id=account_id)

    if effective == JoinAs.SPECTATOR:
        seats_before = await repo.list_seats(room_id)
        spec_idx = sum(1 for s in seats_before if s["seat_kind"] == "spectator")
        await repo.insert_seat(
            room_id=room_id,
            account_id=account_id,
            seat_kind=SeatKind.SPECTATOR,
            seat_index=spec_idx,
        )

    settings = await _set_nick(room_id, settings, account_id, table_nick)
    room = {**room, "settings": settings.model_dump()}
    seats = await repo.list_seats(room_id)
    event(
        logger,
        "ЗАДАЧА",
        "mp_room_joined code=%s as=%s",
        room["code"],
        effective.value,
        room_code=room["code"],
        account_id=account_id,
        join_as=effective.value,
    )
    return build_room_out(room, seats, viewer_account_id=account_id)


async def get_room(*, account_id: int, code: str) -> RoomOut:
    room = await repo.get_room_by_code(code)
    if room is None:
        raise LobbyError(404, "Стол не найден")
    seats = await repo.list_seats(int(room["id"]))
    return build_room_out(room, seats, viewer_account_id=account_id)


async def close_room(*, account_id: int, code: str) -> RoomOut:
    """Хост завершает стол — status=closed, WS-сессия сбрасывается."""
    room = await repo.get_room_by_code(code)
    if room is None:
        raise LobbyError(404, "Стол не найден")
    if int(room["host_account_id"]) != account_id:
        raise LobbyError(403, "Только хост может завершить стол")
    if room["status"] == RoomStatus.CLOSED.value:
        seats = await repo.list_seats(int(room["id"]))
        return build_room_out(room, seats, viewer_account_id=account_id)

    closed = await repo.close_room(int(room["id"]))
    if closed is None:
        # гонка: уже закрыли
        closed = await repo.get_room_by_code(code) or room

    # Сбросить живую WS-сессию, если есть (ленивый импорт — без цикла на старте).
    try:
        from core.domains.multiplayer.session import hub

        await hub().force_close(str(closed["code"]), detail="Стол завершён хостом")
    except Exception:  # noqa: BLE001
        logger.exception("mp_room_close_hub_failed code=%s", closed.get("code"))

    seats = await repo.list_seats(int(closed["id"]))
    event(
        logger,
        "ЗАДАЧА",
        "mp_room_closed code=%s",
        closed["code"],
        room_code=closed["code"],
        account_id=account_id,
    )
    return build_room_out(closed, seats, viewer_account_id=account_id)
