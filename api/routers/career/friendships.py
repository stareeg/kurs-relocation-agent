"""Дружба: код для шаринга, добавление/удаление, профиль друга — `/api/career/friends`.

Тонкий транспорт над `core.domains.career.friendships_repo` (0120).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import AddFriendRequest, FriendshipCodeOut
from api.security import AccountContext, require_account_context
from core.domains.career.friendships_repo import (
    add_friend,
    get_friend_profile,
    get_or_create_friendship_code,
    list_friends,
    remove_friend,
    resolve_code,
)
from core.domains.career.models import FriendEntry, FriendProfile

router = APIRouter(prefix="/api/career/friends", tags=["career"])


@router.get("/code", response_model=FriendshipCodeOut)
async def friends_code(
    account: AccountContext = Depends(require_account_context),
) -> FriendshipCodeOut:
    """Код дружбы аккаунта (генерируется при первом запросе)."""
    fc = await get_or_create_friendship_code(account_id=account.account_id)
    return FriendshipCodeOut(code=fc.code)


@router.post("/add", response_model=FriendEntry)
async def friends_add(
    body: AddFriendRequest,
    account: AccountContext = Depends(require_account_context),
) -> FriendEntry:
    """Добавить друга по коду. 400 — собственный код; 404 — код не найден."""
    friend_account_id = await resolve_code(body.code.upper().strip())
    if friend_account_id is None:
        raise HTTPException(status_code=404, detail="Код дружбы не найден")
    if friend_account_id == account.account_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя")
    entry = await add_friend(friend_account_id, account_id=account.account_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="Уже в друзьях или свой аккаунт")
    return entry


@router.get("", response_model=list[FriendEntry])
async def friends_list(
    account: AccountContext = Depends(require_account_context),
) -> list[FriendEntry]:
    """Список друзей аккаунта."""
    return await list_friends(account_id=account.account_id)


@router.get("/{friend_account_id}/profile", response_model=FriendProfile)
async def friends_profile(
    friend_account_id: int,
    account: AccountContext = Depends(require_account_context),
) -> FriendProfile:
    """Публичный профиль друга (балл резюме, шанс оффера). Требует активной дружбы."""
    profile = await get_friend_profile(friend_account_id, account_id=account.account_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Друг не найден или дружба не активна")
    return profile


@router.delete("/{friend_account_id}", status_code=204)
async def friends_remove(
    friend_account_id: int,
    account: AccountContext = Depends(require_account_context),
) -> None:
    """Удалить друга."""
    removed = await remove_friend(friend_account_id, account_id=account.account_id)
    if removed == "forbidden":
        raise HTTPException(status_code=403, detail="Эту связь нельзя удалить")
    if removed != "removed":
        raise HTTPException(status_code=404, detail="Друг не найден")
