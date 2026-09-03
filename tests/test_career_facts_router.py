"""Роутер `/api/career/facts` — тонкий транспорт над `repo.update_fact`/`delete_fact` (Э9.4)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routers.career.facts import facts_delete, facts_list, facts_patch
from api.schemas.career import CareerFactPatch
from api.security import AccountContext
from core.domains.career.models import CareerFact

_ACCOUNT = AccountContext(account_id=1, telegram_user_id=1, telegram_username=None, role="owner")


async def test_facts_list_forwards_type_and_source(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _list(*, account_id, fact_type=None, source_kind=None, limit=30, db=None):
        captured.update(account_id=account_id, fact_type=fact_type, source_kind=source_kind)
        return []

    monkeypatch.setattr("api.routers.career.facts.list_active_facts", _list)

    await facts_list(type="strength", source="debrief", account=_ACCOUNT)

    assert captured == {"account_id": 1, "fact_type": "strength", "source_kind": "debrief"}


async def test_facts_patch_404_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _update(fact_id, *, account_id, fact=None, pinned=None, db=None):
        return None

    monkeypatch.setattr("api.routers.career.facts.update_fact", _update)

    with pytest.raises(HTTPException) as exc_info:
        await facts_patch(999, CareerFactPatch(fact="x"), account=_ACCOUNT)
    assert exc_info.value.status_code == 404


async def test_facts_patch_returns_updated_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    updated = CareerFact(id=1, fact="Новый текст", fact_type="note", source_kind="manual")

    async def _update(fact_id, *, account_id, fact=None, pinned=None, db=None):
        assert fact_id == 1
        assert account_id == 1
        assert fact == "Новый текст"
        assert pinned is True
        return updated

    monkeypatch.setattr("api.routers.career.facts.update_fact", _update)

    result = await facts_patch(
        1, CareerFactPatch(fact="Новый текст", pinned=True), account=_ACCOUNT
    )
    assert result.fact == "Новый текст"


async def test_facts_delete_404_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _delete(fact_id, *, account_id, db=None):
        return False

    monkeypatch.setattr("api.routers.career.facts.delete_fact", _delete)

    with pytest.raises(HTTPException) as exc_info:
        await facts_delete(1, account=_ACCOUNT)
    assert exc_info.value.status_code == 404


async def test_facts_delete_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _delete(fact_id, *, account_id, db=None):
        return True

    monkeypatch.setattr("api.routers.career.facts.delete_fact", _delete)

    result = await facts_delete(1, account=_ACCOUNT)
    assert result == {"deleted": True}
