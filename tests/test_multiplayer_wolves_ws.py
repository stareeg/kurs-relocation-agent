"""Э5: проекции state + session (apply/rules) + WS без утечки секретов."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.multiplayer import ws as ws_router
from api.security import AccountContext
from core.domains.multiplayer import session as sess_mod
from core.domains.multiplayer.models import Faction, IllegalMove, RoomMode
from core.domains.multiplayer.rules import HR_SEAT_ID, start_match
from core.domains.multiplayer.session import (
    Conn,
    RoomSession,
    _arm_phase_timer,
    _phase_timer,
    apply_client_intent,
    broadcast_state,
    hub,
    pause_match,
    reset_hub_for_tests,
    resume_match,
    start_match_for_room,
)
from core.domains.multiplayer.views import project_private, project_public

_HOST = AccountContext(account_id=10, telegram_user_id=100, telegram_username="host", role="member")
_GUEST = AccountContext(account_id=20, telegram_user_id=200, telegram_username="guest", role="member")


@pytest.fixture(autouse=True)
def _reset_hub() -> None:
    reset_hub_for_tests()


@pytest.fixture(autouse=True)
def _stub_wolves_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты хаба — про механику сессии, не про LLM (её расписание живёт в
    `test_multiplayer_wolves_engine_llm.py`). Без стаба `engine.step` уходит в реальный
    OpenRouter: на медленном/rate-limited провайдере `_run_brief` висит секунды, за это
    время срабатывает таймер фазы, и партия уезжает вперёд ещё до ассерта — тест «то падает,
    то нет» в зависимости от чужого эндпоинта.
    """
    from core.domains.multiplayer import wolves_llm
    from core.domains.multiplayer.rules import claim_is_correct

    async def _brief(_state: Any, **_kw: Any) -> str:
        return wolves_llm.FALLBACK_BRIEF

    async def _judge(state: Any, **_kw: Any) -> wolves_llm.JudgeCall:
        verdict = "confirm" if claim_is_correct(state) else "reject"
        return wolves_llm.JudgeCall(verdict, wolves_llm.FALLBACK_JUDGE_LINE, None)

    async def _ticker(_state: Any, **_kw: Any) -> str:
        return wolves_llm.FALLBACK_TICKER

    async def _bark(_state: Any, _seat_id: str, **_kw: Any) -> str:
        return wolves_llm.FALLBACK_BARK

    async def _line(_state: Any, _seat_id: str, *, on_delta: Any = None, **_kw: Any) -> str:
        return wolves_llm.FALLBACK_BOT_LINE

    monkeypatch.setattr(wolves_llm, "generate_brief", _brief)
    monkeypatch.setattr(wolves_llm, "generate_judge", _judge)
    monkeypatch.setattr(wolves_llm, "generate_ticker", _ticker)
    monkeypatch.setattr(wolves_llm, "generate_bark", _bark)
    monkeypatch.setattr(wolves_llm, "stream_bot_line", _line)


def test_public_view_hides_faction_and_hand() -> None:
    state = start_match(42)
    wolf = next(s for s in state.seats.values() if s.faction == Faction.WOLF)
    pub = project_public(state)
    dumped = str(pub)
    assert "faction" not in dumped or pub["phase"] in ("reveal", "ended")
    assert wolf.faction is not None
    assert pub["hr_energy_max"] == state.config.hr_energy_max
    for seat in pub["seats"]:
        assert "faction" not in seat
        assert "hand" not in seat
        assert "fraud_pair" not in seat
        assert "role_secret" not in dumped


def test_private_view_only_own_hand_and_faction() -> None:
    state = start_match(7)
    wolf = next(s for s in state.seats.values() if s.faction == Faction.WOLF)
    human = next(s for s in state.seats.values() if s.faction == Faction.HUMAN)
    priv_w = project_private(state, wolf.id)
    priv_h = project_private(state, human.id)
    assert priv_w["faction"] == "wolf"
    assert priv_h["faction"] == "human"
    assert len(priv_w["hand"]) == state.config.hand_size
    # Чужую руку не отдаём
    assert all(c["id"] in wolf.hand for c in priv_w["hand"])


@pytest.mark.asyncio
async def test_session_start_and_ack_via_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)

    session = RoomSession(
        room_code="ABC234",
        room_id=1,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    # no-op broadcast targets
    session.connections = {}

    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    assert session.match.phase.value == "bulletin"
    assert session.phase_ends_at is not None

    await apply_client_intent(
        session,
        account_id=_HOST.account_id,
        payload={"type": "ack_bulletin"},
    )
    # Соло-боты сразу кладут карты → PLAY может проскочить в INSPECT.
    assert session.match.phase.value in ("play", "inspect")


@pytest.mark.asyncio
async def test_spectator_cannot_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)

    session = RoomSession(
        room_code="XYZ789",
        room_id=2,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    await start_match_for_room(session, by_account_id=_HOST.account_id)

    with pytest.raises(IllegalMove):
        await apply_client_intent(
            session,
            account_id=_GUEST.account_id,  # нет места
            payload={"type": "ack_bulletin"},
        )


@pytest.mark.asyncio
async def test_phase_timeout_reaches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Д1: истёкший таймер фазы обязан РАЗОСЛАТЬ новое состояние, а не только сменить его.

    `_phase_timer`, доведя фазу до следующей, взводит таймер на неё же — и `_arm_phase_timer`
    раньше отменял `session._timer_task`, которым в этот момент была сама выполняющаяся
    задача. Отмена прилетала на ближайшем `await` (`repo.update_phase_label`), то есть до
    `broadcast_state`: сервер уходил по фазам до конца партии, а экран игрока замирал на той,
    где его застали, и следующий клик получал «не та фаза». На проде это выглядело как
    «игра сломана», а в `copilot_logs` `mp_ws_timeout` не появлялся ни разу.
    """
    monkeypatch.setattr("core.domains.multiplayer.session.repo.update_room_playing", AsyncMock())
    monkeypatch.setattr("core.domains.multiplayer.session.repo.update_phase_label", AsyncMock())
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)

    broadcasts: list[str] = []

    async def _spy(sess: RoomSession) -> None:
        broadcasts.append(sess.match.phase.value if sess.match else "—")

    monkeypatch.setattr("core.domains.multiplayer.session.broadcast_state", _spy)

    session = RoomSession(
        room_code="TMR234",
        room_id=3,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    assert session.match.phase.value == "bulletin"
    broadcasts.clear()

    # Своя задача вместо восьмисекундной: важно, что она лежит в session._timer_task —
    # именно это и делало отмену самоотменой.
    armed = session._timer_task
    if armed is not None:
        armed.cancel()
    task = asyncio.create_task(_phase_timer(session, "bulletin", 0.0))
    session._timer_task = task
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.CancelledError:
        pytest.fail("таймер фазы отменил сам себя и умер до broadcast_state (Д1)")
    finally:
        pending = session._timer_task
        if pending is not None and not pending.done():
            pending.cancel()

    assert session.match.phase.value != "bulletin", "фаза обязана была смениться по таймауту"
    assert broadcasts, "смена фазы по таймеру не разослана — клиент останется на прошлой фазе"


@pytest.mark.asyncio
async def test_arm_phase_timer_does_not_cancel_itself() -> None:
    """Тот же инвариант точечно: перевзвод изнутри таймера не убивает текущую задачу."""
    session = RoomSession(
        room_code="TMR567",
        room_id=4,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.match = start_match(11)

    async def _rearm_from_inside() -> bool:
        _arm_phase_timer(session)
        # Отмена текущей задачи не срабатывает мгновенно — она ждёт ближайшего await.
        # Проверяем не «упали ли мы», а «запрошена ли отмена нас самих».
        cur = asyncio.current_task()
        assert cur is not None
        return cur.cancelling() > 0

    task = asyncio.create_task(_rearm_from_inside())
    session._timer_task = task
    try:
        cancelled_self = await task
    finally:
        pending = session._timer_task
        if pending is not None and not pending.done():
            pending.cancel()

    assert not cancelled_self, "_arm_phase_timer отменил задачу, из которой его вызвали (Д1)"
    assert session.phase_ends_at is not None


def test_warn_if_multiple_workers_logs_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Э20.5: `--workers > 1` ломает in-process хаб столов — старт обязан кричать в журнал."""
    from api import main as main_mod

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(main_mod, "event", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(main_mod.sys, "argv", ["uvicorn", "api.main:app", "--workers", "3"])
    main_mod._warn_if_multiple_workers()
    assert calls and calls[0].get("level") == logging.ERROR


def test_single_worker_start_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_mod

    calls: list[Any] = []
    monkeypatch.setattr(main_mod, "event", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(main_mod.sys, "argv", ["uvicorn", "api.main:app"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    main_mod._warn_if_multiple_workers()
    assert not calls


def test_warn_if_multiple_workers_reads_web_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_mod

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(main_mod, "event", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(main_mod.sys, "argv", ["uvicorn", "api.main:app"])
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    main_mod._warn_if_multiple_workers()
    assert calls and calls[0].get("level") == logging.ERROR


def test_ws_route_registered() -> None:
    from fastapi.routing import iter_route_contexts

    from api.main import app

    paths = {
        getattr(ctx.route, "path", None) or ctx.path
        for ctx in iter_route_contexts(app.routes)
        if type(ctx.route).__name__ == "APIWebSocketRoute"
    }
    assert "/api/multiplayer/ws/{room_code}" in paths


def test_ws_rejects_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_account(*_a: Any, **_k: Any) -> tuple[None, bool]:
        return None, False

    monkeypatch.setattr(ws_router, "resolve_request_account", _no_account)

    app = FastAPI()
    app.include_router(ws_router.router)
    with TestClient(app) as client:
        with client.websocket_connect("/api/multiplayer/ws/ABC234") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "auth" in str(msg.get("detail", "")).lower()
            # сервер закрывает 4401 — дальнейший receive падает
            with pytest.raises(Exception):
                ws.receive_json()


def test_ws_welcome_and_start(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _host(*_a: Any, **_k: Any) -> tuple[AccountContext, bool]:
        return _HOST, True

    room = {
        "id": 1,
        "code": "ABC234",
        "name": "WS",
        "host_account_id": _HOST.account_id,
        "pin_hash": None,
        "status": "open",
        "mode": "solo",
        "settings": {"candidate_slots": 3, "match_slots": 5},
        "phase_label": "лобби",
    }
    seats = [
        {
            "id": 1,
            "room_id": 1,
            "account_id": _HOST.account_id,
            "seat_kind": "hr",
            "seat_index": 0,
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": False,
        },
        {
            "id": 2,
            "room_id": 1,
            "account_id": None,
            "seat_kind": "candidate",
            "seat_index": 0,
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": True,
        },
        {
            "id": 3,
            "room_id": 1,
            "account_id": None,
            "seat_kind": "candidate",
            "seat_index": 1,
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": True,
        },
        {
            "id": 4,
            "room_id": 1,
            "account_id": None,
            "seat_kind": "candidate",
            "seat_index": 2,
            "role_public": "waiting",
            "role_secret": None,
            "is_bot": True,
        },
    ]

    monkeypatch.setattr(ws_router, "resolve_request_account", _host)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.get_room_by_code",
        AsyncMock(return_value=room),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.list_seats",
        AsyncMock(return_value=seats),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(ws_router, "event", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(ws_router.router)

    with TestClient(app) as client:
        with client.websocket_connect("/api/multiplayer/ws/ABC234") as ws:
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert welcome["is_host"] is True
            assert welcome["engine_seat_id"] == "hr"
            assert welcome["seat_token"]
            # Э20.1: единый конверт состояния вместо пары state_public + state_private.
            lobby = ws.receive_json()
            assert lobby["type"] == "state"
            assert lobby["lobby"] is True
            assert isinstance(lobby["rev"], int)
            last_rev = lobby["rev"]

            ws.send_json({"type": "start"})
            # после старта — конверт состояния (+ возможно bot ticks)
            saw_match = False
            for _ in range(8):
                msg = ws.receive_json()
                if msg.get("type") == "state" and not msg.get("lobby"):
                    assert msg["public"]["phase"] == "bulletin"
                    assert "phase_ends_at" in msg
                    assert "private" in msg  # приватная половина едет тем же кадром
                    # Э20.6: rev монотонно растёт.
                    assert msg["rev"] > last_rev
                    last_rev = msg["rev"]
                    # секреты
                    for seat in msg["public"]["seats"]:
                        assert "faction" not in seat
                    saw_match = True
                    break
            assert saw_match

            ws.send_json({"type": "intent", "intent": {"type": "ack_bulletin"}})
            saw_after_ack = False
            for _ in range(16):
                msg = ws.receive_json()
                if msg.get("type") != "state":
                    continue
                assert msg["rev"] > last_rev
                last_rev = msg["rev"]
                phase = msg.get("public", {}).get("phase")
                # Боты могут мгновенно пройти PLAY → INSPECT.
                if phase in ("play", "inspect"):
                    saw_after_ack = True
                    break
            assert saw_after_ack


@pytest.mark.asyncio
async def test_rematch_from_reveal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Э9: «Ещё раунд» — новый seed из фазы reveal, тот же стол."""
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)

    seeds = iter([111, 222])
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow",
        lambda _n: next(seeds),
    )

    session = RoomSession(
        room_code="REM001",
        room_id=9,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.connections = {}

    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    first_seed = session.match.seed
    assert first_seed == 112  # randbelow+1

    # Форсим конец партии.
    from core.domains.multiplayer.models import Phase, Winner

    session.match.phase = Phase.REVEAL
    session.match.winner = Winner.FREEZE

    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    assert session.match.phase.value == "bulletin"
    assert session.match.seed == 223
    assert session.match.seed != first_seed
    assert session.match.winner is None


def test_public_hides_ghost_slot_flag() -> None:
    """Ghost JD не светится в public — иначе оффер становится тривиальным."""
    state = start_match(50)
    state.ghost_slot_indices = (0,)
    state.slot_index = 0
    pub = project_public(state)
    assert "is_ghost_slot" not in pub
    assert "ghost_slot" not in str(pub)
@pytest.mark.asyncio
async def test_friends_start_keeps_bots_on_unclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Незанятые слоты = LLM-боты (друг может сесть mid-match)."""
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 99
    )

    session = RoomSession(
        room_code="FRI001",
        room_id=11,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=4,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.account_seats[_GUEST.account_id] = "c0"
    session.connections = {}

    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    assert session.match.seats["c0"].filled
    assert session.match.seats["c0"].account_id == _GUEST.account_id
    assert session.match.seats["c0"].is_bot is False
    for sid in ("c1", "c2", "c3"):
        assert session.match.seats[sid].filled
        assert session.match.seats[sid].is_bot is True
        assert session.match.seats[sid].account_id is None


@pytest.mark.asyncio
async def test_claim_seat_between_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Третий игрок садится на пустой слот в BETWEEN."""
    from core.domains.multiplayer.models import Phase
    from core.domains.multiplayer.session import claim_seat

    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.claim_candidate_by_index",
        AsyncMock(
            return_value={
                "id": 9,
                "room_id": 12,
                "account_id": 30,
                "seat_kind": "candidate",
                "seat_index": 2,
                "is_bot": False,
            }
        ),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.delete_spectator_for_account",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 55
    )

    session = RoomSession(
        room_code="CLM001",
        room_id=12,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=4,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.connections = {}
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    session.match.phase = Phase.BETWEEN
    session.match.slot_index = 2

    spectator = 30
    await claim_seat(session, account_id=spectator, seat_id="c2")
    assert session.account_seats[spectator] == "c2"
    seat = session.match.seats["c2"]
    assert seat.filled
    assert seat.faction is not None
    assert seat.faction.value == "human"
    assert seat.account_id == spectator
    pub = project_public(session.match)
    by_id = {s["id"]: s for s in pub["seats"]}
    assert "faction" not in by_id["c2"]


@pytest.mark.asyncio
async def test_claim_empty_rejected_outside_between(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой слот — только BETWEEN; бота можно занять в любой фазе."""
    from core.domains.multiplayer.models import Phase
    from core.domains.multiplayer.rules import vacate_candidate_seat
    from core.domains.multiplayer.session import claim_seat

    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 56
    )

    session = RoomSession(
        room_code="CLM002",
        room_id=13,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    session.match = vacate_candidate_seat(session.match, "c1")
    session.match.phase = Phase.PLAY
    with pytest.raises(IllegalMove, match="между слотами"):
        await claim_seat(session, account_id=99, seat_id="c1")


@pytest.mark.asyncio
async def test_client_cannot_send_mid_join(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_phase_label", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 57
    )

    session = RoomSession(
        room_code="CLM003",
        room_id=14,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    with pytest.raises(IllegalMove, match="claim_seat"):
        await apply_client_intent(
            session,
            account_id=_HOST.account_id,
            payload={"type": "mid_join", "seat_id": "c1", "account_id": 1},
        )


@pytest.mark.asyncio
async def test_hold_expire_converts_to_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.domains.multiplayer import session as sess_mod

    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.mark_account_seat_bot",
        AsyncMock(return_value={"id": 1}),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 58
    )
    monkeypatch.setattr(sess_mod, "DISCONNECT_HOLD_S", 0.05)

    session = RoomSession(
        room_code="HLD001",
        room_id=15,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.account_seats[_GUEST.account_id] = "c0"
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    session.match.seats["c0"].account_id = _GUEST.account_id
    session.match.seats["c0"].is_bot = False

    ws = object()
    session.connections[id(ws)] = sess_mod.Conn(
        ws=ws,
        account_id=_GUEST.account_id,
        engine_seat_id="c0",
        seat_token="tok",
        is_spectator=False,
    )
    await sess_mod.unbind_connection(session, ws)
    assert _GUEST.account_id in session.disconnect_hold_until
    import asyncio

    await asyncio.sleep(0.15)
    for _ in range(20):
        if session.match.seats["c0"].is_bot:
            break
        await asyncio.sleep(0.05)
    assert session.match.seats["c0"].is_bot
    assert session.match.seats["c0"].account_id is None
    assert _GUEST.account_id not in session.account_seats


@pytest.mark.asyncio
async def test_host_kick_and_fill_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.domains.multiplayer.models import Phase
    from core.domains.multiplayer.session import host_action

    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.update_room_playing", AsyncMock()
    )
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.clear_candidate_to_empty",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.set_candidate_bot",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "core.domains.multiplayer.session.secrets.randbelow", lambda _n: 59
    )

    session = RoomSession(
        room_code="HST001",
        room_id=16,
        host_account_id=_HOST.account_id,
        mode=RoomMode.FRIENDS,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.account_seats[_GUEST.account_id] = "c0"
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.match is not None
    session.match.phase = Phase.BETWEEN

    await host_action(
        session, by_account_id=_HOST.account_id, action="kick", seat_id="c0"
    )
    assert not session.match.seats["c0"].filled
    assert _GUEST.account_id not in session.account_seats

    await host_action(
        session, by_account_id=_HOST.account_id, action="fill_bot", seat_id="c0"
    )
    assert session.match.seats["c0"].filled
    assert session.match.seats["c0"].is_bot
    assert session.match.seats["c0"].faction is not None
    assert session.match.seats["c0"].faction.value == "human"


class _RecordingWs:
    """WS-заглушка: копит разосланные конверты."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


def _session_with_conn(ws: _RecordingWs, *, seat: str = HR_SEAT_ID) -> RoomSession:
    session = RoomSession(
        room_code="BRD001",
        room_id=40,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = seat
    session.connections[id(ws)] = Conn(
        ws=ws,
        account_id=_HOST.account_id,
        engine_seat_id=seat,
        seat_token="tok",
    )
    return session


@pytest.mark.asyncio
async def test_state_frame_is_one_envelope_with_rev() -> None:
    """Э20.1: public и private едут одним кадром `{type:"state", …}`, а не двумя."""
    ws = _RecordingWs()
    session = _session_with_conn(ws)
    session.match = start_match(1)

    await broadcast_state(session)
    await asyncio.sleep(0.1)

    assert len(ws.sent) == 1
    frame = ws.sent[0]
    assert frame["type"] == "state"
    assert "public" in frame and "private" in frame
    assert frame["rev"] == 1
    assert "state_public" not in {f["type"] for f in ws.sent}


@pytest.mark.asyncio
async def test_broadcast_coalesces_a_burst() -> None:
    """Э20.2: пачка запросов в пределах окна склейки → один разосланный кадр."""
    ws = _RecordingWs()
    session = _session_with_conn(ws)
    session.match = start_match(2)

    for _ in range(4):
        await broadcast_state(session)
    await asyncio.sleep(0.1)

    assert len(ws.sent) == 1, "каскад должен был склеиться в один кадр"

    # Следующий отдельный запрос — новый кадр с большим rev.
    await broadcast_state(session)
    await asyncio.sleep(0.1)
    assert [f["rev"] for f in ws.sent] == [1, 2]


@pytest.mark.asyncio
async def test_lobby_state_frame_has_no_private() -> None:
    """До старта партии приватной половины нет — клиент не должен её ждать."""
    ws = _RecordingWs()
    session = _session_with_conn(ws)

    await broadcast_state(session)
    await asyncio.sleep(0.1)

    assert ws.sent[0]["type"] == "state"
    assert ws.sent[0]["lobby"] is True
    assert "private" not in ws.sent[0]


# --- Пауза (Dota-стиль) --------------------------------------------------------------


def _solo_session(*, code: str, room_id: int) -> RoomSession:
    session = RoomSession(
        room_code=code,
        room_id=room_id,
        host_account_id=_HOST.account_id,
        mode=RoomMode.SOLO,
        candidate_slots=3,
    )
    session.account_seats[_HOST.account_id] = HR_SEAT_ID
    session.connections = {}
    return session


@pytest.fixture
def _repo_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.domains.multiplayer.session.repo.update_room_playing", AsyncMock())
    monkeypatch.setattr("core.domains.multiplayer.session.repo.update_phase_label", AsyncMock())
    monkeypatch.setattr("core.domains.multiplayer.session.event", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_pause_freezes_phase_timer(_repo_stub: None) -> None:
    session = _solo_session(code="PAU001", room_id=50)
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    assert session.phase_ends_at is not None
    phase_before = session.match.phase.value

    # Подменяем таймер фазы на быстрый — чтобы проверить, что пауза его гасит.
    if session._timer_task:
        session._timer_task.cancel()
    session._timer_task = asyncio.create_task(_phase_timer(session, phase_before, 0.1))
    fast_timer = session._timer_task

    await pause_match(session, account_id=_HOST.account_id, by_label="Костя")
    assert session.paused is True
    assert session.paused_by_label == "Костя"
    assert session.phase_ends_at is None
    assert session.paused_phase_left_s is not None and session.paused_phase_left_s > 0

    await asyncio.sleep(0.25)  # быстрый таймер (0.1с) успел бы сработать, если бы не пауза
    assert fast_timer.cancelled()
    assert session.match.phase.value == phase_before, "фаза не должна съезжать на паузе"


@pytest.mark.asyncio
async def test_intent_rejected_while_paused(_repo_stub: None) -> None:
    session = _solo_session(code="PAU002", room_id=51)
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    await pause_match(session, account_id=_HOST.account_id, by_label="")

    with pytest.raises(IllegalMove, match="пауза|паузе"):
        await apply_client_intent(
            session, account_id=_HOST.account_id, payload={"type": "ack_bulletin"}
        )


@pytest.mark.asyncio
async def test_resume_countdown_then_rearm_with_remaining(
    monkeypatch: pytest.MonkeyPatch, _repo_stub: None
) -> None:
    monkeypatch.setattr(sess_mod, "RESUME_COUNTDOWN_S", 0.1)
    session = _solo_session(code="PAU003", room_id=52)
    ws = _RecordingWs()
    session.connections[id(ws)] = Conn(
        ws=ws, account_id=_HOST.account_id, engine_seat_id=HR_SEAT_ID, seat_token="t"
    )
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    await pause_match(session, account_id=_HOST.account_id, by_label="")
    left_at_pause = session.paused_phase_left_s
    assert left_at_pause is not None
    ws.sent.clear()

    await resume_match(session, account_id=_GUEST.account_id, by_label="Аня")
    assert session.resume_at is not None  # идёт отсчёт

    # Второй resume во время отсчёта — no-op.
    await resume_match(session, account_id=_HOST.account_id, by_label="")

    await asyncio.sleep(0.4)
    assert session.paused is False
    assert session.resume_at is None
    assert session.phase_ends_at is not None
    remaining = (session.phase_ends_at - sess_mod._utc_now()).total_seconds()
    # Таймер вернулся на остаток фазы, а не на её полную длину.
    assert remaining <= left_at_pause + 0.5
    # Кадр «снято с паузы» реально ушёл клиенту (отсчёт не оборвал себя на broadcast).
    resumed_frames = [f for f in ws.sent if f.get("pause", {}).get("paused") is False]
    assert resumed_frames, "после продолжения клиент не получил кадр без паузы"


@pytest.mark.asyncio
async def test_pause_during_resume_countdown_cancels_it(
    monkeypatch: pytest.MonkeyPatch, _repo_stub: None
) -> None:
    monkeypatch.setattr(sess_mod, "RESUME_COUNTDOWN_S", 0.1)
    session = _solo_session(code="PAU004", room_id=53)
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    await pause_match(session, account_id=_HOST.account_id, by_label="")
    await resume_match(session, account_id=_HOST.account_id, by_label="")
    assert session.resume_at is not None

    await pause_match(session, account_id=_GUEST.account_id, by_label="")
    assert session.resume_at is None  # отсчёт отменён
    assert session.paused is True

    await asyncio.sleep(0.2)
    assert session.paused is True  # остались на бессрочной паузе


@pytest.mark.asyncio
async def test_pause_block_in_state_envelope() -> None:
    ws = _RecordingWs()
    session = _session_with_conn(ws)
    session.match = start_match(3)

    await broadcast_state(session)
    await asyncio.sleep(0.05)
    assert ws.sent[-1]["pause"] == {"paused": False}

    session.paused_at = sess_mod._utc_now()
    session.paused_by_label = "Костя"
    await broadcast_state(session)
    await asyncio.sleep(0.05)
    assert ws.sent[-1]["pause"]["paused"] is True
    assert ws.sent[-1]["pause"]["by"] == "Костя"


@pytest.mark.asyncio
async def test_bots_only_match_closes(monkeypatch: pytest.MonkeyPatch, _repo_stub: None) -> None:
    """Все живые ушли и стали ботами → стол закрывается, а не висит активным."""
    monkeypatch.setattr(sess_mod, "DISCONNECT_HOLD_S", 0.05)
    monkeypatch.setattr(
        "core.domains.multiplayer.session.repo.mark_account_seat_bot",
        AsyncMock(return_value={"id": 1}),
    )
    closed: list[int] = []

    async def _close_room(room_id: int, **_kw: Any) -> dict[str, Any]:
        closed.append(room_id)
        return {"id": room_id}

    monkeypatch.setattr("core.domains.multiplayer.session.repo.close_room", _close_room)

    session = _solo_session(code="ABN001", room_id=60)
    await start_match_for_room(session, by_account_id=_HOST.account_id)
    hub()._rooms["ABN001"] = session

    ws = object()
    session.connections[id(ws)] = Conn(
        ws=ws, account_id=_HOST.account_id, engine_seat_id=HR_SEAT_ID, seat_token="t"
    )
    await sess_mod.unbind_connection(session, ws)

    for _ in range(30):
        if hub().get("ABN001") is None:
            break
        await asyncio.sleep(0.05)

    assert hub().get("ABN001") is None, "стол с одними ботами должен закрыться"
    assert closed == [60], "закрытие должно доехать и до БД"
