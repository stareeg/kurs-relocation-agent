"""REST лобби столов «Хрюши и Волки» — `/api/multiplayer/wolves/rooms`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.schemas.multiplayer import CreateRoomRequest, JoinRoomRequest
from api.security import AccountContext, require_account_context
from core.domains.multiplayer.models import RoomOut
from core.domains.multiplayer.service import (
    LobbyError,
    close_room,
    create_room,
    get_room,
    join_room,
    list_rooms,
)

router = APIRouter(prefix="/api/multiplayer/wolves/rooms", tags=["multiplayer"])


def _raise(exc: LobbyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=list[RoomOut])
async def wolves_rooms_list(
    account: AccountContext = Depends(require_account_context),
) -> list[RoomOut]:
    """Открытые столы: имя, слоты, фаза."""
    return await list_rooms(account_id=account.account_id)


@router.post("", response_model=RoomOut, status_code=201)
async def wolves_rooms_create(
    body: CreateRoomRequest,
    account: AccountContext = Depends(require_account_context),
) -> RoomOut:
    """Создать стол (хост = хрюша). Опционально PIN / friends-only."""
    try:
        return await create_room(
            account_id=account.account_id,
            name=body.name,
            mode=body.mode,
            slots=body.slots,
            pin=body.pin,
            friends_only=body.friends_only,
            daily=body.daily,
            nick=body.nick,
        )
    except LobbyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{code}", response_model=RoomOut)
async def wolves_rooms_get(
    code: str,
    account: AccountContext = Depends(require_account_context),
) -> RoomOut:
    """Карточка стола по коду."""
    try:
        return await get_room(account_id=account.account_id, code=code)
    except LobbyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{code}/join", response_model=RoomOut)
async def wolves_rooms_join(
    code: str,
    body: JoinRoomRequest,
    account: AccountContext = Depends(require_account_context),
) -> RoomOut:
    """Сесть игроком или зрителем. Повторный join того же аккаунта — идемпотентен."""
    try:
        return await join_room(
            account_id=account.account_id,
            code=code,
            join_as=body.as_,
            pin=body.pin,
            nick=body.nick,
        )
    except LobbyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{code}/close", response_model=RoomOut)
async def wolves_rooms_close(
    code: str,
    account: AccountContext = Depends(require_account_context),
) -> RoomOut:
    """Хост завершает стол — он исчезает из списка открытых."""
    try:
        return await close_room(account_id=account.account_id, code=code)
    except LobbyError as exc:
        _raise(exc)
        raise  # pragma: no cover
