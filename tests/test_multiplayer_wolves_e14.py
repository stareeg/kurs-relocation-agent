"""Э14: безопасность public WS, idle GC, reconnect storm, бюджет ассетов."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.multiplayer import ws as ws_router
from api.security import AccountContext
from core.domains.multiplayer import gc as mp_gc
from core.domains.multiplayer.limits import (
    ASSET_MAX_BYTES_PER_FILE,
    ASSET_MAX_TOTAL_BYTES,
)
from core.domains.multiplayer.models import Faction, Phase, RoomMode
from core.domains.multiplayer.rules import HR_SEAT_ID, start_match
from core.domains.multiplayer.session import (
    RoomSession,
    reset_hub_for_tests,
)
from core.domains.multiplayer.views import project_private, project_public

_HOST = AccountContext(account_id=10, telegram_user_id=100, telegram_username="host", role="member")

# Ключи/фрагменты, которых не должно быть в public mid-match.
_SECRET_KEYS = frozenset(
    {
        "hand",
        "fraud_pair",
        "role_secret",
        "sub_role",
        "pack_mates",
        "is_strong",
        "fraud",
    }
)


@pytest.fixture(autouse=True)
def _reset_hub() -> None:
    reset_hub_for_tests()


def _assert_no_secrets_in_public(pub: dict[str, Any], *, revealing: bool) -> None:
    dumped = json.dumps(pub, ensure_ascii=False)
    for key in _SECRET_KEYS:
        assert key not in dumped, f"утечка {key} в public"
    assert "role_secret" not in dumped
    for seat in pub.get("seats", []):
        for key in _SECRET_KEYS:
            assert key not in seat
        if not revealing:
            assert "faction" not in seat
            assert "revealed_as_wolf" not in seat
            assert "lifetime_stamps" not in seat


def test_public_payload_never_leaks_secret_role_mid_match() -> None:
    """Э14 security: faction/hand/fraud только private; public — без секретов."""
    state = start_match(4242)
    assert state.phase == Phase.BULLETIN
    pub = project_public(state)
    _assert_no_secrets_in_public(pub, revealing=False)

    # Прогон нескольких фаз — секреты не появляются.
    for phase in (Phase.PLAY, Phase.INSPECT, Phase.LINES, Phase.STAMP, Phase.RESULT):
        state.phase = phase
        pub = project_public(state)
        _assert_no_secrets_in_public(pub, revealing=False)

    wolf = next(s for s in state.seats.values() if s.faction == Faction.WOLF)
    priv = project_private(state, wolf.id)
    assert priv["faction"] == "wolf"
    human = next(s for s in state.seats.values() if s.faction == Faction.HUMAN)
    other = project_private(state, human.id)
    assert other["faction"] == "human"
    assert other["hand"] != priv["hand"] or wolf.id != human.id


def test_public_reveal_exposes_faction_only_then() -> None:
    from core.domains.multiplayer.models import Winner

    state = start_match(99)
    wolf = next(s for s in state.seats.values() if s.faction == Faction.WOLF)
    state.phase = Phase.REVEAL
    state.winner = Winner.HUMANS
    pub = project_public(state)
    by_id = {s["id"]: s for s in pub["seats"]}
    assert by_id[wolf.id]["faction"] == "wolf"
    dumped = json.dumps(pub, ensure_ascii=False)
    assert "role_secret" not in dumped
    assert "hand" not in dumped
    assert "fraud_pair" not in dumped


@pytest.mark.asyncio
async def test_idle_gc_closes_stale_rooms(monkeypatch: pytest.MonkeyPatch) -> None:
    rooms = [
        {
            "id": 1,
            "code": "IDLE01",
            "name": "Old",
            "host_account_id": 1,
            "pin_hash": None,
            "status": "open",
            "mode": "friends",
            "settings": {},
            "phase_label": "лобби",
            "created_at": None,
            "updated_at": None,
        }
    ]
    closed: list[int] = []

    async def fake_list(*, older_than_hours: float, limit: int = 100):
        assert older_than_hours > 0
        batch = list(rooms[:limit])
        rooms.clear()
        return batch

    async def fake_close(room_id: int):
        closed.append(room_id)
        return {"id": room_id, "code": "IDLE01", "status": "closed"}

    force = AsyncMock()

    class _Hub:
        async def force_close(self, code: str, *, detail: str = "") -> None:
            await force(code, detail=detail)

        def room_codes(self) -> list[str]:
            return []

        def get(self, _code: str) -> None:
            return None

        async def drop_if_empty(self, _code: str) -> None:
            return None

    monkeypatch.setattr(mp_gc.repo, "list_idle_room_ids", fake_list)
    monkeypatch.setattr(mp_gc.repo, "close_room", fake_close)
    monkeypatch.setattr("core.domains.multiplayer.session.hub", lambda: _Hub())

    n = await mp_gc.close_idle_rooms(older_than_hours=2.0)
    assert n == 1
    assert closed == [1]
    force.assert_awaited_once()


@pytest.mark.asyncio
async def test_hub_sweep_drops_empty_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.domains.multiplayer.session import hub

    session = RoomSession(
        room_code="SWP001",
        room_id=7,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=2,
    )
    session.match = start_match(3)
    session.match.phase = Phase.ENDED
    session.connections = {}
    h = hub()
    h._rooms["SWP001"] = session
    dropped = await mp_gc.sweep_empty_hub_sessions()
    assert dropped >= 1
    assert h.get("SWP001") is None


def test_reconnect_storm_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Э14: N быстрых connect/close одного стола — без исключений, welcome каждый раз."""
    room = {
        "id": 55,
        "code": "STRM01",
        "name": "Storm",
        "host_account_id": _HOST.account_id,
        "pin_hash": None,
        "status": "open",
        "mode": "friends",
        "settings": {"candidate_slots": 2},
        "phase_label": "лобби",
    }
    seats = [
        {
            "id": 1,
            "room_id": 55,
            "account_id": _HOST.account_id,
            "seat_kind": "hr",
            "seat_index": 0,
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": False,
        },
        {
            "id": 2,
            "room_id": 55,
            "account_id": None,
            "seat_kind": "candidate",
            "seat_index": 0,
            "role_public": "bot",
            "role_secret": None,
            "is_bot": True,
        },
        {
            "id": 3,
            "room_id": 55,
            "account_id": None,
            "seat_kind": "candidate",
            "seat_index": 1,
            "role_public": "bot",
            "role_secret": None,
            "is_bot": True,
        },
    ]

    async def _host(*_a: Any, **_k: Any) -> tuple[AccountContext, bool]:
        return _HOST, True

    monkeypatch.setattr(ws_router, "resolve_request_account", _host)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.get_room_by_code",
        AsyncMock(return_value=room),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.list_seats",
        AsyncMock(return_value=seats),
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(ws_router, "event", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(ws_router.router)

    welcomes = 0
    with TestClient(app) as client:
        for _ in range(25):
            with client.websocket_connect("/api/multiplayer/ws/STRM01") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "welcome"
                assert msg["engine_seat_id"] == HR_SEAT_ID
                welcomes += 1
                # lobby: единый конверт состояния (Э20.1)
                pub = ws.receive_json()
                assert pub["type"] == "state"
                dumped = json.dumps(pub, ensure_ascii=False)
                assert "role_secret" not in dumped
                assert "faction" not in dumped or pub.get("lobby")
    assert welcomes == 25


def test_multiplayer_asset_chunk_budget() -> None:
    """Э14: SVG в public/multiplayer укладываются в бюджет chunk size."""
    root = Path(__file__).resolve().parents[1] / "frontend" / "public" / "multiplayer"
    assert root.is_dir()
    files = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {".svg", ".webp", ".png"}]
    assert files, "ожидались SVG-ассеты"
    total = 0
    for path in files:
        size = path.stat().st_size
        total += size
        assert size <= ASSET_MAX_BYTES_PER_FILE, f"{path.name}={size} > {ASSET_MAX_BYTES_PER_FILE}"
    assert total <= ASSET_MAX_TOTAL_BYTES, f"total={total} > {ASSET_MAX_TOTAL_BYTES}"
