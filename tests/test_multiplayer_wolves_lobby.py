"""Лобби «Хрюши и Волки» (Э4): create/join/close двумя аккаунтами, API-ручки."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.multiplayer import rooms as rooms_router
from api.security import AccountContext, require_account_context
from core.domains.multiplayer import repo, service
from core.domains.multiplayer.models import JoinAs, RoomMode, SeatKind
from core.domains.multiplayer.service import (
    LobbyError,
    build_room_out,
    close_room,
    create_room,
    hash_pin,
    join_room,
    list_rooms,
    verify_pin,
)

_A = AccountContext(account_id=10, telegram_user_id=100, telegram_username="host", role="member")
_B = AccountContext(account_id=20, telegram_user_id=200, telegram_username="guest", role="member")


class _FakeLobbyDb:
    """In-memory mp_rooms / mp_seats для юнит-тестов без Postgres."""

    def __init__(self) -> None:
        self.rooms: dict[int, dict[str, Any]] = {}
        self.seats: dict[int, dict[str, Any]] = {}
        self._room_seq = 0
        self._seat_seq = 0

    async def insert_room(self, **kw: Any) -> dict[str, Any]:
        self._room_seq += 1
        rid = self._room_seq
        row = {
            "id": rid,
            "code": kw["code"],
            "name": kw["name"].strip(),
            "host_account_id": kw["host_account_id"],
            "pin_hash": kw["pin_hash"],
            "status": "open",
            "mode": kw["mode"].value if hasattr(kw["mode"], "value") else kw["mode"],
            "settings": json.loads(kw["settings"].model_dump_json())
            if hasattr(kw["settings"], "model_dump_json")
            else (
                dict(kw["settings"])
                if isinstance(kw["settings"], dict)
                else kw["settings"]
            ),
            "phase_label": "лобби",
            "created_at": None,
            "updated_at": None,
        }
        if any(r["code"] == row["code"] for r in self.rooms.values()):
            raise Exception("unique violation")
        self.rooms[rid] = row
        return dict(row)

    async def insert_seat(self, **kw: Any) -> dict[str, Any]:
        self._seat_seq += 1
        sid = self._seat_seq
        row = {
            "id": sid,
            "room_id": kw["room_id"],
            "account_id": kw["account_id"],
            "seat_kind": kw["seat_kind"].value if hasattr(kw["seat_kind"], "value") else kw["seat_kind"],
            "seat_index": kw["seat_index"],
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": bool(kw.get("is_bot", False)),
            "joined_at": None,
        }
        self.seats[sid] = row
        return dict(row)

    async def code_exists(self, code: str) -> bool:
        return any(r["code"] == code for r in self.rooms.values())

    async def get_room_by_code(self, code: str) -> dict[str, Any] | None:
        code = code.upper().strip()
        for r in self.rooms.values():
            if r["code"] == code:
                return dict(r)
        return None

    async def list_open_rooms(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.rooms.values()
            if r["status"] in ("open", "playing")
        ]
        return rows[:limit]

    async def count_rooms(self) -> int:
        return len(self.rooms)

    async def count_active_rooms_for_host(self, host_account_id: int) -> int:
        return sum(
            1
            for r in self.rooms.values()
            if r["host_account_id"] == host_account_id and r["status"] in ("open", "playing")
        )

    async def list_idle_room_ids(
        self, *, older_than_hours: float, limit: int = 100
    ) -> list[dict[str, Any]]:
        # В fake нет updated_at-часов — тесты GC монкают repo напрямую.
        return []

    async def list_seats(self, room_id: int) -> list[dict[str, Any]]:
        return [
            dict(s)
            for s in sorted(
                (s for s in self.seats.values() if s["room_id"] == room_id),
                key=lambda s: (s["seat_kind"], s["seat_index"]),
            )
        ]

    async def find_seat_for_account(self, room_id: int, account_id: int) -> dict[str, Any] | None:
        for s in self.seats.values():
            if s["room_id"] == room_id and s["account_id"] == account_id:
                return dict(s)
        return None

    async def claim_empty_candidate_seat(
        self, room_id: int, account_id: int
    ) -> dict[str, Any] | None:
        for s in sorted(self.seats.values(), key=lambda x: x["seat_index"]):
            if (
                s["room_id"] == room_id
                and s["seat_kind"] == "candidate"
                and s["account_id"] is None
                and not s["is_bot"]
            ):
                s["account_id"] = account_id
                s["is_bot"] = False
                return dict(s)
        return None

    async def claim_joinable_candidate_seat(
        self, room_id: int, account_id: int
    ) -> dict[str, Any] | None:
        candidates = sorted(
            (
                s
                for s in self.seats.values()
                if s["room_id"] == room_id
                and s["seat_kind"] == "candidate"
                and s["account_id"] is None
            ),
            key=lambda x: (x["is_bot"], x["seat_index"]),
        )
        if not candidates:
            return None
        s = candidates[0]
        s["account_id"] = account_id
        s["is_bot"] = False
        s["role_public"] = "waiting"
        return dict(s)

    async def close_room(self, room_id: int) -> dict[str, Any] | None:
        row = self.rooms.get(room_id)
        if row is None or row["status"] == "closed":
            return None
        row["status"] = "closed"
        row["phase_label"] = "закрыт"
        return dict(row)

    async def update_room_settings(self, room_id: int, settings: Any) -> None:
        row = self.rooms.get(room_id)
        if row is None:
            return
        payload = (
            settings.model_dump()
            if hasattr(settings, "model_dump")
            else dict(settings)
        )
        row["settings"] = payload


@pytest.fixture
def fake_lobby(monkeypatch: pytest.MonkeyPatch) -> _FakeLobbyDb:
    from core.domains.multiplayer.limits import reset_rate_limits_for_tests

    reset_rate_limits_for_tests()
    db = _FakeLobbyDb()
    monkeypatch.setattr(repo, "insert_room", db.insert_room)
    monkeypatch.setattr(repo, "insert_seat", db.insert_seat)
    monkeypatch.setattr(repo, "code_exists", db.code_exists)
    monkeypatch.setattr(repo, "get_room_by_code", db.get_room_by_code)
    monkeypatch.setattr(repo, "list_open_rooms", db.list_open_rooms)
    monkeypatch.setattr(repo, "count_rooms", db.count_rooms)
    monkeypatch.setattr(repo, "count_active_rooms_for_host", db.count_active_rooms_for_host)
    monkeypatch.setattr(repo, "list_idle_room_ids", db.list_idle_room_ids)
    monkeypatch.setattr(repo, "list_seats", db.list_seats)
    monkeypatch.setattr(repo, "find_seat_for_account", db.find_seat_for_account)
    monkeypatch.setattr(repo, "claim_empty_candidate_seat", db.claim_empty_candidate_seat)
    monkeypatch.setattr(repo, "claim_joinable_candidate_seat", db.claim_joinable_candidate_seat)
    monkeypatch.setattr(repo, "close_room", db.close_room)
    monkeypatch.setattr(repo, "update_room_settings", db.update_room_settings)
    monkeypatch.setattr(service, "event", lambda *a, **k: None)

    async def _fake_account(account_id: int, **_kw: Any) -> Any:
        from core.platform.repo.accounts import AccountRecord

        return AccountRecord(
            id=account_id,
            telegram_user_id=account_id * 10,
            telegram_username=f"user{account_id}",
            telegram_chat_id=None,
            role="member",
            status="active",
        )

    monkeypatch.setattr(service, "get_account_by_id", _fake_account)
    return db


@pytest.mark.asyncio
async def test_create_and_second_account_joins(fake_lobby: _FakeLobbyDb) -> None:
    host = await create_room(account_id=_A.account_id)
    assert host.code
    assert len(host.code) == 6
    assert host.name == "Стол №1"
    assert host.has_pin is False
    assert host.my_seat_kind == SeatKind.HR
    assert host.candidate_slots == 2
    # 2 бота = свободны для людей
    assert host.seats_free == 2
    assert host.seats_taken == 1

    guest = await join_room(
        account_id=_B.account_id,
        code=host.code,
        join_as=JoinAs.PLAYER,
    )
    assert guest.my_seat_kind == SeatKind.CANDIDATE
    assert guest.seats_taken == 2
    assert guest.seats_free == 1

    # Секретов ролей в публичном ответе нет
    assert all(not hasattr(s, "role_secret") for s in guest.seats)


@pytest.mark.asyncio
async def test_join_idempotent(fake_lobby: _FakeLobbyDb) -> None:
    host = await create_room(account_id=_A.account_id, name="Idem")
    first = await join_room(account_id=_B.account_id, code=host.code)
    second = await join_room(account_id=_B.account_id, code=host.code)
    assert first.my_seat_id == second.my_seat_id
    assert second.seats_taken == 2


@pytest.mark.asyncio
async def test_full_table_becomes_spectator(fake_lobby: _FakeLobbyDb) -> None:
    """2 слота заняты людьми → третий входит зрителем (не 409)."""
    host = await create_room(account_id=_A.account_id)
    await join_room(account_id=_B.account_id, code=host.code)
    third = await join_room(account_id=30, code=host.code)
    assert third.my_seat_kind == SeatKind.CANDIDATE
    fourth = await join_room(account_id=40, code=host.code)
    assert fourth.my_seat_kind == SeatKind.SPECTATOR
    assert fourth.seats_free == 0


@pytest.mark.asyncio
async def test_explicit_spectator(fake_lobby: _FakeLobbyDb) -> None:
    host = await create_room(account_id=_A.account_id)
    spec = await join_room(
        account_id=_B.account_id, code=host.code, join_as=JoinAs.SPECTATOR
    )
    assert spec.my_seat_kind == SeatKind.SPECTATOR
    # боты всё ещё «свободны» для игроков
    assert spec.seats_free == 2


@pytest.mark.asyncio
async def test_player_join_while_playing_takes_bot(fake_lobby: _FakeLobbyDb) -> None:
    """Идущая партия: друг садится на бот-слот как игрок."""
    host = await create_room(account_id=_A.account_id)
    room = fake_lobby.rooms[host.id]
    room["status"] = "playing"
    room["phase_label"] = "осмотр"
    guest = await join_room(account_id=_B.account_id, code=host.code, join_as=JoinAs.PLAYER)
    assert guest.my_seat_kind == SeatKind.CANDIDATE
    assert guest.status.value == "playing"


@pytest.mark.asyncio
async def test_create_fills_bots_by_default(fake_lobby: _FakeLobbyDb) -> None:
    room = await create_room(account_id=_A.account_id)
    assert room.mode.value == "friends"
    bots = [s for s in room.seats if s.seat_kind == SeatKind.CANDIDATE and s.is_bot]
    assert len(bots) == 2
    assert room.seats_free == 2


@pytest.mark.asyncio
async def test_list_rooms(fake_lobby: _FakeLobbyDb) -> None:
    await create_room(account_id=_A.account_id, name="A")
    await create_room(account_id=_B.account_id, name="B")
    listed = await list_rooms(account_id=_A.account_id)
    assert len(listed) == 2
    assert {r.name for r in listed} == {"A", "B"}


@pytest.mark.asyncio
async def test_host_closes_room(fake_lobby: _FakeLobbyDb) -> None:
    host = await create_room(account_id=_A.account_id, name="CloseMe")
    closed = await close_room(account_id=_A.account_id, code=host.code)
    assert closed.status.value == "closed"
    listed = await list_rooms(account_id=_A.account_id)
    assert all(r.code != host.code for r in listed)
    with pytest.raises(LobbyError) as ei:
        await join_room(account_id=_B.account_id, code=host.code)
    assert ei.value.status_code == 410


@pytest.mark.asyncio
async def test_guest_cannot_close(fake_lobby: _FakeLobbyDb) -> None:
    host = await create_room(account_id=_A.account_id, name="NoClose")
    await join_room(account_id=_B.account_id, code=host.code)
    with pytest.raises(LobbyError) as ei:
        await close_room(account_id=_B.account_id, code=host.code)
    assert ei.value.status_code == 403


def test_build_room_out_never_exposes_secret() -> None:
    room = {
        "id": 1,
        "code": "ABC234",
        "name": "X",
        "host_account_id": 1,
        "pin_hash": None,
        "status": "open",
        "mode": "friends",
        "settings": {"candidate_slots": 3, "match_slots": 5},
        "phase_label": "лобби",
    }
    seats = [
        {
            "id": 1,
            "room_id": 1,
            "account_id": 1,
            "seat_kind": "hr",
            "seat_index": 0,
            "role_public": "waiting",
            "role_secret": "wolf",
            "is_bot": False,
        }
    ]
    out = build_room_out(room, seats, viewer_account_id=1)
    payload = out.model_dump()
    assert "role_secret" not in str(payload)
    assert payload["has_pin"] is False


def test_api_create_list_join_two_accounts(monkeypatch: pytest.MonkeyPatch, fake_lobby: _FakeLobbyDb) -> None:
    app = FastAPI()
    app.include_router(rooms_router.router)

    # Переключаем account между запросами
    current = {"ctx": _A}

    def _ctx() -> AccountContext:
        return current["ctx"]

    app.dependency_overrides[require_account_context] = _ctx

    with TestClient(app) as client:
        r = client.post(
            "/api/multiplayer/wolves/rooms",
            json={},
        )
        assert r.status_code == 201, r.text
        code = r.json()["code"]
        assert r.json()["name"].startswith("Стол №")
        assert r.json()["has_pin"] is False
        assert r.json()["candidate_slots"] == 2
        assert r.json()["my_seat_kind"] == "hr"

        current["ctx"] = _B
        ok = client.post(
            f"/api/multiplayer/wolves/rooms/{code}/join",
            json={"as": "player"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["my_seat_kind"] == "candidate"
        assert ok.json()["seats_taken"] == 2

        listed = client.get("/api/multiplayer/wolves/rooms")
        assert listed.status_code == 200
        assert any(x["code"] == code for x in listed.json())

        current["ctx"] = _A
        closed = client.post(f"/api/multiplayer/wolves/rooms/{code}/close")
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        listed2 = client.get("/api/multiplayer/wolves/rooms")
        assert all(x["code"] != code for x in listed2.json())


def test_api_routes_registered() -> None:
    from api.main import app
    from fastapi.routing import iter_route_contexts

    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert "/api/multiplayer/wolves/rooms" in paths
    assert "/api/multiplayer/wolves/rooms/{code}/join" in paths
    assert "/api/multiplayer/wolves/rooms/{code}/close" in paths

def test_pin_hash_roundtrip() -> None:
    h = hash_pin("1234")
    assert verify_pin("1234", h)
    assert not verify_pin("9999", h)
    assert not verify_pin(None, h)
    assert verify_pin(None, None)


@pytest.mark.asyncio
async def test_pin_and_friends_only_ignored_on_unified_create(
    fake_lobby: _FakeLobbyDb,
) -> None:
    """Обычный стол — без PIN/friends-only (выбор убран из UI)."""
    room = await create_room(
        account_id=_A.account_id,
        name="X",
        pin="1234",
        friends_only=True,
    )
    assert room.has_pin is False
    assert room.settings.friends_only is False
    assert room.mode.value == "friends"
    guest = await join_room(account_id=_B.account_id, code=room.code)
    assert guest.my_seat_kind == SeatKind.CANDIDATE


@pytest.mark.asyncio
async def test_daily_room_sets_day_and_solo(fake_lobby: _FakeLobbyDb, monkeypatch) -> None:
    from datetime import date

    monkeypatch.setattr(
        "core.domains.multiplayer.service.date",
        type("D", (), {"today": staticmethod(lambda: date(2026, 8, 26))})(),
    )
    room = await create_room(
        account_id=_A.account_id,
        name="Стол дня",
        mode=RoomMode.FRIENDS,
        slots=4,
        pin="9999",
        friends_only=True,
        daily=True,
    )
    assert room.mode.value == "solo"
    assert room.has_pin is False
    assert room.settings.friends_only is False
    assert room.settings.daily_day == "2026-08-26"
    assert room.name == "День #238"
    assert room.candidate_slots == 4
    assert room.seats_free == 4  # боты свободны для takeover


def test_deep_link_join_query_shape() -> None:
    """Формат deep-link из плана: /multiplayer?join=CODE."""
    code = "ABC234"
    path = f"/multiplayer?join={code}"
    assert path.startswith("/multiplayer?join=")
    assert code in path


@pytest.mark.asyncio
async def test_active_room_limit_per_host(fake_lobby: _FakeLobbyDb) -> None:
    """Э14: хост не держит больше MAX_ACTIVE_ROOMS_PER_HOST открытых столов."""
    from core.domains.multiplayer.limits import MAX_ACTIVE_ROOMS_PER_HOST

    for i in range(MAX_ACTIVE_ROOMS_PER_HOST):
        room = await create_room(account_id=_A.account_id, name=f"T{i}")
        assert room.code
    with pytest.raises(LobbyError) as ei:
        await create_room(account_id=_A.account_id, name="overflow")
    assert ei.value.status_code == 429
    assert "Лимит столов" in ei.value.detail
    # Другой аккаунт — свой лимит.
    other = await create_room(account_id=_B.account_id, name="Other")
    assert other.code
    # Закрыли один — снова можно.
    first_code = next(iter(fake_lobby.rooms.values()))["code"]
    await close_room(account_id=_A.account_id, code=first_code)
    again = await create_room(account_id=_A.account_id, name="again")
    assert again.code


@pytest.mark.asyncio
async def test_create_rate_limit(fake_lobby: _FakeLobbyDb, monkeypatch: pytest.MonkeyPatch) -> None:
    """Э14: create rate-limit → 429."""
    from core.domains.multiplayer import limits

    monkeypatch.setattr(limits, "CREATE_RATE", (2, 60.0))
    limits.reset_rate_limits_for_tests()
    # Поднимаем потолок комнат, чтобы упереться именно в rate.
    monkeypatch.setattr(service, "MAX_ACTIVE_ROOMS_PER_HOST", 99)
    await create_room(account_id=_A.account_id, name="r1")
    await create_room(account_id=_A.account_id, name="r2")
    with pytest.raises(LobbyError) as ei:
        await create_room(account_id=_A.account_id, name="r3")
    assert ei.value.status_code == 429
    assert "часто" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_join_rate_limit(fake_lobby: _FakeLobbyDb, monkeypatch: pytest.MonkeyPatch) -> None:
    """Э14: join rate-limit → 429 (идемпотентный повтор тоже считается)."""
    from core.domains.multiplayer import limits

    host = await create_room(account_id=_A.account_id)
    monkeypatch.setattr(limits, "JOIN_RATE", (2, 60.0))
    limits.reset_rate_limits_for_tests()
    await join_room(account_id=_B.account_id, code=host.code)
    await join_room(account_id=_B.account_id, code=host.code)  # idempotent, но тик
    with pytest.raises(LobbyError) as ei:
        await join_room(account_id=_B.account_id, code=host.code)
    assert ei.value.status_code == 429
