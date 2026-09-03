"""Репозиторий дружбы: friendship_codes + friendships (таблицы из миграции 0121).

Системные рёбра с оператором (`origin=system_admin`) заводит админ-контур, не `POST /add`.
Имя владельца для member всегда маскируется — даже если кто-то добавил его по коду.
"""

from __future__ import annotations

import secrets
import time
from typing import Literal

from core.domains.career.models import FriendEntry, FriendProfile, FriendshipCode
from core.platform.db.pool import Executor, get_pool, row_to_dict
from core.platform.repo.accounts import get_account_by_id, get_owner_account

ADMIN_DISPLAY_NAME = "Администратор"
RemoveResult = Literal["removed", "missing", "forbidden"]


def friend_display(*, viewer_role: str, friend_role: str, resume_name: str) -> tuple[str, bool]:
    """(имя для UI, это системный админ-пир). Маска по роли друга, не по origin."""
    if viewer_role != "owner" and friend_role == "owner":
        return ADMIN_DISPLAY_NAME, True
    return resume_name or "", False


def _generate_code() -> str:
    """6-буквенно-цифровой код (A-Z, 0-9), без схожих глифов 0/O, 1/I/L."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


async def get_or_create_friendship_code(
    *, account_id: int, db: Executor | None = None
) -> FriendshipCode:
    """Получить существующий код дружбы или сгенерировать новый (единственный на аккаунт)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select code, created_at, updated_at from account_friendship_codes where account_id = $1",
        account_id,
    )
    if row is not None:
        data = row_to_dict(row)
        return FriendshipCode(**data)

    for _ in range(3):
        code = _generate_code()
        try:
            row = await db.fetchrow(
                "insert into account_friendship_codes (account_id, code) "
                "values ($1, $2) "
                "on conflict (account_id) do update set code = excluded.code, updated_at = now() "
                "returning code, created_at, updated_at",
                account_id,
                code,
            )
        except Exception:
            continue
        assert row is not None
        return FriendshipCode(**row_to_dict(row))
    raise RuntimeError("Не удалось сгенерировать уникальный код дружбы")


async def resolve_code(code: str, *, db: Executor | None = None) -> int | None:
    """По коду дружбы найти account_id владельца. None — код не найден."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select account_id from account_friendship_codes where code = $1",
        code.upper().strip(),
    )
    return int(row["account_id"]) if row is not None else None


async def add_friend(
    friend_account_id: int, *, account_id: int, db: Executor | None = None
) -> FriendEntry | None:
    """Добавить друга по его account_id. origin всегда `user` — системные рёбра сюда не ходят."""
    db = db or get_pool()
    if account_id == friend_account_id:
        return None
    row = await db.fetchrow(
        "insert into friendships (account_id, friend_account_id, origin) "
        "values ($1, $2, 'user') "
        "on conflict (account_id, friend_account_id) do nothing "
        "returning id, account_id, friend_account_id, status, origin, created_at",
        account_id,
        friend_account_id,
    )
    if row is None:
        return None
    return await _enrich_friend_entry(row_to_dict(row), viewer_account_id=account_id, db=db)


async def list_friends(*, account_id: int, db: Executor | None = None) -> list[FriendEntry]:
    """Список друзей аккаунта (только active)."""
    db = db or get_pool()
    rows = await db.fetch(
        "select f.id, f.account_id, f.friend_account_id, f.status, f.origin, f.created_at "
        "from friendships f "
        "where f.account_id = $1 and f.status = 'active' "
        "order by f.created_at desc",
        account_id,
    )
    return [
        await _enrich_friend_entry(row_to_dict(r), viewer_account_id=account_id, db=db)
        for r in rows
    ]


async def are_friends(
    account_id: int, other_account_id: int, *, db: Executor | None = None
) -> bool:
    """Активная дружба в любую сторону (для friends-only столов мультиплеера)."""
    if account_id == other_account_id:
        return True
    db = db or get_pool()
    row = await db.fetchrow(
        "select 1 from friendships "
        "where status = 'active' and ("
        "(account_id = $1 and friend_account_id = $2) or "
        "(account_id = $2 and friend_account_id = $1)"
        ")",
        account_id,
        other_account_id,
    )
    return row is not None


async def get_friend_profile(
    friend_account_id: int, *, account_id: int, db: Executor | None = None
) -> FriendProfile | None:
    """Публичный профиль друга: балл резюме, шанс оффера, имя.
    Доступен только если дружба активна (в любую сторону)."""
    db = db or get_pool()
    if not await are_friends(account_id, friend_account_id, db=db):
        return None

    viewer = await get_account_by_id(account_id, db=db)
    friend = await get_account_by_id(friend_account_id, db=db)
    viewer_role = viewer.role if viewer is not None else "member"
    friend_role = friend.role if friend is not None else "member"
    name, is_admin_peer = friend_display(
        viewer_role=viewer_role, friend_role=friend_role, resume_name=""
    )
    if is_admin_peer:
        return FriendProfile(account_id=friend_account_id, name=name)

    name_row = await db.fetchrow(
        "select data->'personal'->>'full_name' as full_name "
        "from resumes where account_id = $1 limit 1",
        friend_account_id,
    )
    full_name = name_row["full_name"] if name_row and name_row["full_name"] else ""

    gap_row = await db.fetchrow(
        "select total from resume_score_history "
        "where account_id = $1 order by created_at desc limit 1",
        friend_account_id,
    )
    resume_score = int(gap_row["total"]) if gap_row and gap_row["total"] is not None else None

    market_row = await db.fetchrow(
        "select payload->>'offer_chance_score' as score "
        "from market_snapshots where account_id = $1 order by day desc limit 1",
        friend_account_id,
    )
    offer_chance_pct = market_row["score"] if market_row and market_row["score"] else None

    return FriendProfile(
        account_id=friend_account_id,
        name=full_name,
        resume_score=resume_score,
        offer_chance_pct=offer_chance_pct,
    )


async def _enrich_friend_entry(
    data: dict, *, viewer_account_id: int, db: Executor | None = None
) -> FriendEntry:
    db = db or get_pool()
    viewer = await get_account_by_id(viewer_account_id, db=db)
    friend = await get_account_by_id(int(data["friend_account_id"]), db=db)
    viewer_role = viewer.role if viewer is not None else "member"
    friend_role = friend.role if friend is not None else "member"

    name_row = await db.fetchrow(
        "select data->'personal'->>'full_name' as full_name "
        "from resumes where account_id = $1 limit 1",
        data["friend_account_id"],
    )
    resume_name = name_row["full_name"] if name_row and name_row["full_name"] else ""
    display, is_admin_peer = friend_display(
        viewer_role=viewer_role, friend_role=friend_role, resume_name=resume_name
    )
    data["friend_name"] = display
    data["friend_email"] = ""
    data["origin"] = data.get("origin") or "user"
    data["is_admin_peer"] = is_admin_peer
    return FriendEntry(**data)


async def remove_friend(
    friend_account_id: int, *, account_id: int, db: Executor | None = None
) -> RemoveResult:
    """Удалить друга. Системное ребро и связь с owner member удалить не может."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select origin from friendships where account_id = $1 and friend_account_id = $2",
        account_id,
        friend_account_id,
    )
    if row is None:
        return "missing"
    origin = str(row["origin"] or "user")
    viewer = await get_account_by_id(account_id, db=db)
    friend = await get_account_by_id(friend_account_id, db=db)
    if origin == "system_admin":
        return "forbidden"
    if (
        viewer is not None
        and viewer.role != "owner"
        and friend is not None
        and friend.role == "owner"
    ):
        return "forbidden"
    result = await db.execute(
        "delete from friendships where account_id = $1 and friend_account_id = $2 "
        "and origin = 'user'",
        account_id,
        friend_account_id,
    )
    return "removed" if result and "DELETE 1" in str(result) else "missing"


async def _insert_system_edge(account_id: int, friend_account_id: int, *, db: Executor) -> None:
    await db.execute(
        "insert into friendships (account_id, friend_account_id, origin) "
        "values ($1, $2, 'system_admin') "
        "on conflict (account_id, friend_account_id) do nothing",
        account_id,
        friend_account_id,
    )


async def ensure_system_admin_friendships(
    member_account_id: int, *, db: Executor | None = None
) -> None:
    """Два ребра owner↔member. Не трогает member↔member. Идемпотентно."""
    try:
        db = db or get_pool()
        owner = await get_owner_account(db=db)
        if owner is None or owner.id == member_account_id:
            return
        member = await get_account_by_id(member_account_id, db=db)
        if member is None or member.role != "member":
            return
        await _insert_system_edge(owner.id, member.id, db=db)
        await _insert_system_edge(member.id, owner.id, db=db)
    except Exception:
        return


_REPAIR_MIN_INTERVAL_S = 600.0
_last_repair_monotonic: float | None = None


async def ensure_all_system_admin_friendships_throttled(*, db: Executor | None = None) -> bool:
    """Тот же ремонт, но не чаще раза в 10 минут на процесс. Возвращает, прошёл ли проход.

    Ремонт — подстраховка на дыры в пути создания (сам путь зовёт `ensure_system_admin_
    friendships` при выдаче токена и в меню бота). Витрина оператора опрашивается по таймеру,
    и без троттлинга проход по всем активным member шёл дважды в минуту на каждую открытую
    вкладку — запись в горячем пути чтения. Постоянное место — кнопка в разделе «Система».
    """
    global _last_repair_monotonic
    now = time.monotonic()
    if _last_repair_monotonic is not None and now - _last_repair_monotonic < _REPAIR_MIN_INTERVAL_S:
        return False
    _last_repair_monotonic = now
    await ensure_all_system_admin_friendships(db=db)
    return True


def reset_friendship_repair_throttle() -> None:
    """Сброс троттлинга — для тестов, не для продакшн-кода."""
    global _last_repair_monotonic
    _last_repair_monotonic = None


async def ensure_all_system_admin_friendships(*, db: Executor | None = None) -> None:
    """Repair: все активные member связаны с owner. Дыра в пути создания — не дыра в UI."""
    try:
        db = db or get_pool()
        owner = await get_owner_account(db=db)
        if owner is None:
            return
        rows = await db.fetch(
            "select id from accounts where role = 'member' and status = 'active' and id <> $1",
            owner.id,
        )
        for row in rows:
            await ensure_system_admin_friendships(int(row["id"]), db=db)
    except Exception:
        return


__all__ = [
    "ADMIN_DISPLAY_NAME",
    "add_friend",
    "are_friends",
    "ensure_all_system_admin_friendships",
    "ensure_all_system_admin_friendships_throttled",
    "ensure_system_admin_friendships",
    "friend_display",
    "get_friend_profile",
    "get_or_create_friendship_code",
    "list_friends",
    "remove_friend",
    "resolve_code",
]
