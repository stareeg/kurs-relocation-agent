"""`open_conversation` (FR2-87: привязка к известной вакансии без вставленного дампа).

Баг: клик по чипу «Привязать к …?» без дампа раньше не писал ничего в PG — тред не заводился,
диалог не появлялся в списке слева и терялся при уходе со вкладки без единого сообщения.
`open_conversation` обязан завести тред через `get_or_create_thread`, даже без единой реплики.
"""

from __future__ import annotations

import pytest

from core.app.scenarios import conversations
from core.domains.pipeline import hr_threads
from core.domains.pipeline.hr_threads import HrThread


async def test_open_conversation_creates_thread_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def fake_get_or_create_thread(
        vacancy_id, *, company="", channel="telegram", contact_name="", account_id, db=None
    ):
        calls["vacancy_id"] = vacancy_id
        calls["account_id"] = account_id
        calls["company"] = company
        return HrThread(id=1, vacancy_id=vacancy_id, company=company)

    async def fake_company(vacancy_id, *, account_id):
        return "ООО Ромашка"

    async def fake_load_conversation(vacancy_id, *, account_id):
        return conversations.ConversationView(vacancy_id=vacancy_id)

    monkeypatch.setattr(hr_threads, "get_or_create_thread", fake_get_or_create_thread)
    monkeypatch.setattr(conversations, "_company", fake_company)
    monkeypatch.setattr(conversations, "load_conversation", fake_load_conversation)

    view = await conversations.open_conversation("hh_1", account_id=7)

    assert view.vacancy_id == "hh_1"
    assert calls == {"vacancy_id": "hh_1", "account_id": 7, "company": "ООО Ромашка"}


async def test_open_conversation_no_store_raises_storage_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_get_or_create_thread(*_args, **_kwargs):
        raise RuntimeError("нет PG")

    async def fake_company(vacancy_id, *, account_id):
        return ""

    monkeypatch.setattr(hr_threads, "get_or_create_thread", failing_get_or_create_thread)
    monkeypatch.setattr(conversations, "_company", fake_company)

    with pytest.raises(conversations.StorageUnavailable):
        await conversations.open_conversation("hh_1", account_id=7)
