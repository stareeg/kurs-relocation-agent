"""L-45: живая рассылка доменных событий по SSE вместо `refetchInterval`-поллинга.

Проверяем четыре вещи:
1. `LiveEventBroadcaster` разносит одно доменное событие во все зарегистрированные очереди
   ТОГО ЖЕ аккаунта и корректно снимает регистрацию (`stream` — генератор, отмена = отписка).
2. Событие чужого аккаунта до очереди не доходит (М6, plans/multitenancy_gaps_2026_08_06.md
   §3.12 — раньше уходило всем открытым вкладкам без разбора).
3. Издатель не блокируется, даже если очередь конкретного соединения переполнена.
4. Роутер `/api/events/stream` подключён и требует авторизации, как остальные ручки.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi.routing import iter_route_contexts

import pytest

from core.kernel.events import VacancyScored
from core.platform.events.live import LiveEventBroadcaster


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_same_account_queues_only() -> None:
    bc = LiveEventBroadcaster()
    q1 = bc.register(1)
    q2 = bc.register(1)
    q_other = bc.register(2)
    assert bc.connection_count() == 3

    bc.broadcast(VacancyScored(vacancy_id="v1", job_id=7, overall_score=81.5, account_id=1))

    for q in (q1, q2):
        payload = q.get_nowait()
        assert payload["type"] == "VacancyScored"
        assert payload["subject"] == "v1"
        assert payload["fields"]["job_id"] == 7

    assert q_other.empty()  # чужой аккаунт событие не получил


@pytest.mark.asyncio
async def test_broadcast_without_account_attribution_is_dropped() -> None:
    bc = LiveEventBroadcaster()
    q = bc.register(1)
    bc.broadcast(VacancyScored(vacancy_id="v1"))  # account_id=0 (default), нет ContextVar
    assert q.empty()  # fail-closed: без атрибуции — никому


@pytest.mark.asyncio
async def test_broadcast_without_listeners_is_a_noop() -> None:
    bc = LiveEventBroadcaster()
    bc.broadcast(VacancyScored(vacancy_id="v1", account_id=1))  # не должно падать без очередей


@pytest.mark.asyncio
async def test_full_queue_drops_event_instead_of_blocking_publisher() -> None:
    bc = LiveEventBroadcaster()
    q = bc.register(1)
    for i in range(300):  # больше _QUEUE_MAXSIZE (200) — не должно бросить исключение наружу
        bc.broadcast(VacancyScored(vacancy_id=f"v{i}", account_id=1))
    assert q.qsize() <= 200


@pytest.mark.asyncio
async def test_stream_unregisters_on_cancel() -> None:
    bc = LiveEventBroadcaster()
    q = bc.register(1)
    assert bc.connection_count() == 1

    agen: AsyncIterator = bc.stream(q)
    task = asyncio.create_task(agen.__anext__())
    await asyncio.sleep(0)  # дать задаче дойти до `await queue.get()`
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await agen.aclose()

    assert bc.connection_count() == 0


def test_events_router_registered() -> None:
    from api.routers import mount_routers
    from fastapi import FastAPI

    app = FastAPI()
    mount_routers(app, require_account=lambda: None)
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert "/api/events/stream" in paths


def test_events_stream_requires_auth() -> None:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.security import require_account

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI):
        yield

    from api.main import app

    app.router.lifespan_context = _noop_lifespan  # type: ignore[method-assign]

    async def _deny() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Не авторизован")

    app.dependency_overrides[require_account] = _deny
    try:
        with TestClient(app) as client:
            response = client.get("/api/events/stream")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(require_account, None)
