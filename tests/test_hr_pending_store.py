"""TB-7.3: hr_pending в Postgres (мок пула) — TTL, round-trip, pop, PG-down fallback."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bot_app.storage import hr_pending as hp
from core.domains.pipeline.models import HrMessageAnalysis


def _analysis(**kwargs: Any) -> HrMessageAnalysis:
    base = {
        "raw_text": "привет",
        "intent": "follow_up",
        "company": "Acme",
        "position": "Dev",
        "summary": "ок",
    }
    base.update(kwargs)
    return HrMessageAnalysis(**base)


def _ctx(**kwargs: Any) -> hp.PendingHrContext:
    defaults = {
        "analysis": _analysis(),
        "pending_resolve_vacancy_id": "123",
        "telegram_msg_id": 9,
        "chat_id": 42,
    }
    defaults.update(kwargs)
    return hp.PendingHrContext(**defaults)


@pytest.fixture(autouse=True)
def _clear_mem() -> None:
    hp.clear_memory()
    yield
    hp.clear_memory()


@pytest.mark.asyncio
async def test_save_get_pop_roundtrip_memory_when_pg_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hp, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("no pg")))

    token = await hp.save(_ctx(), account_id=1)
    assert token
    got = await hp.get(token, account_id=1)
    assert got is not None
    assert got.chat_id == 42
    assert got.pending_resolve_vacancy_id == "123"
    assert got.analysis.company == "Acme"

    popped = await hp.pop(token, account_id=1)
    assert popped is not None
    assert await hp.get(token, account_id=1) is None
    assert await hp.pop(token, account_id=1) is None


@pytest.mark.asyncio
async def test_save_writes_pg_and_get_from_pg_after_mem_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict[str, Any] = {}

    class FakePool:
        async def execute(self, *_a: Any, **_k: Any) -> str:
            return "INSERT 0 1"

        async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
            token = args[0]
            if "delete" in sql.lower():
                row = stored.pop(token, None)
                return row
            return stored.get(token)

        async def fetch(self, *_a: Any, **_k: Any) -> list[Any]:
            return []

    pool = FakePool()

    async def _execute(sql: str, *args: Any) -> str:
        # insert: token, chat_id, payload, created_at, expires_at, account_id
        if sql.strip().lower().startswith("insert"):
            token, chat_id, payload, _created, expires, _account_id = args
            stored[token] = {"payload": payload, "expires_at": expires, "chat_id": chat_id}
        return "INSERT 0 1"

    async def _fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        token = args[0]
        if "delete" in sql.lower():
            return stored.pop(token, None)
        return stored.get(token)

    pool.execute = AsyncMock(side_effect=_execute)  # type: ignore[method-assign]
    pool.fetchrow = AsyncMock(side_effect=_fetchrow)  # type: ignore[method-assign]
    monkeypatch.setattr(hp, "get_pool", lambda: pool)

    ctx = _ctx(analysis=_analysis(hr_link="tg:@anna"))
    token = await hp.save(ctx, account_id=1)
    assert token in stored
    assert stored[token]["payload"]["analysis"]["hr_link"] == "tg:@anna"

    hp.clear_memory()
    got = await hp.get(token, account_id=1)
    assert got is not None
    assert got.analysis.hr_link == "tg:@anna"

    popped = await hp.pop(token, account_id=1)
    assert popped is not None
    assert token not in stored
    assert await hp.get(token, account_id=1) is None


@pytest.mark.asyncio
async def test_put_updates_hr_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hp, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("no pg")))

    token = await hp.save(_ctx(), account_id=1)
    got = await hp.get(token, account_id=1)
    assert got is not None
    updated = hp.PendingHrContext(
        analysis=got.analysis.model_copy(update={"hr_link": "tg:@bob"}),
        pending_resolve_vacancy_id=got.pending_resolve_vacancy_id,
        telegram_msg_id=got.telegram_msg_id,
        chat_id=got.chat_id,
        created_at=got.created_at,
    )
    assert await hp.put(token, updated, account_id=1)
    again = await hp.get(token, account_id=1)
    assert again is not None
    assert again.analysis.hr_link == "tg:@bob"


@pytest.mark.asyncio
async def test_expired_mem_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hp, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("no pg")))

    old = _ctx(created_at=time.time() - hp._TTL_SEC - 10)
    token = await hp.save(old, account_id=1)
    assert await hp.get(token, account_id=1) is None


@pytest.mark.asyncio
async def test_expire_due_deletes_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    class FakePool:
        async def fetch(self, *_a: Any, **_k: Any) -> list[dict[str, str]]:
            deleted.extend(["a", "b"])
            return [{"token": "a"}, {"token": "b"}]

    monkeypatch.setattr(hp, "get_pool", lambda: FakePool())
    hp._MEM["a"] = _ctx()
    hp._MEM["b"] = _ctx()
    n = await hp.expire_due()
    assert n == 2
    assert "a" not in hp._MEM
    assert "b" not in hp._MEM


@pytest.mark.asyncio
async def test_payload_roundtrip_preserves_fields() -> None:
    ctx = _ctx(
        analysis=_analysis(
            vacancy_id="v1",
            hr_link="tg:@x",
            salary_match="yes",
            interview_dt=None,
        ),
        pending_resolve_vacancy_id="v1",
    )
    payload = hp._payload_from_ctx(ctx)
    restored = hp._ctx_from_payload(payload)
    assert restored is not None
    assert restored.analysis.vacancy_id == "v1"
    assert restored.analysis.hr_link == "tg:@x"
    assert restored.analysis.salary_match == "yes"
    assert restored.pending_resolve_vacancy_id == "v1"
    assert restored.chat_id == 42
