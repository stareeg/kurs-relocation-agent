"""§7 local_context_blind_spots: event_extract.py игнорировал author_uncertain, в отличие от
funnel_suggest.py (FR3-74) — последняя hr_in-реплика с неуверенной атрибуцией не должна
кормить извлечение события; нужно брать предыдущую уверенно атрибутированную.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.pipeline import event_extract, hr_threads


@pytest.mark.asyncio
async def test_extract_event_skips_uncertain_last_hr_in(monkeypatch: pytest.MonkeyPatch) -> None:
    thread = hr_threads.HrThread(id=1, vacancy_id="v1")
    messages = [
        hr_threads.HrMessage(
            id=1, thread_id=1, kind="hr_in", body="Созвон завтра в 15:00", author_uncertain=False
        ),
        hr_threads.HrMessage(id=2, thread_id=1, kind="hr_out", body="Ок, буду"),
        hr_threads.HrMessage(
            id=3,
            thread_id=1,
            kind="hr_in",
            body="Собес перенесём на другое время",
            author_uncertain=True,
        ),
    ]
    monkeypatch.setattr(hr_threads, "get_primary_thread", AsyncMock(return_value=thread))
    monkeypatch.setattr(hr_threads, "list_messages", AsyncMock(return_value=messages))
    monkeypatch.setattr(event_extract, "load_stages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        event_extract,
        "_call_llm",
        AsyncMock(return_value=event_extract._ExtractedEvent(note="звонок обсуждается")),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(event_extract, "_upsert_stage", upsert)

    await event_extract.extract_event("v1", account_id=7, db=AsyncMock())

    upsert.assert_awaited_once()
    assert upsert.await_args.kwargs["source_message_id"] == 1


@pytest.mark.asyncio
async def test_extract_event_no_confident_hr_in_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    thread = hr_threads.HrThread(id=1, vacancy_id="v1")
    messages = [
        hr_threads.HrMessage(
            id=3,
            thread_id=1,
            kind="hr_in",
            body="Собес перенесём на другое время",
            author_uncertain=True,
        ),
    ]
    monkeypatch.setattr(hr_threads, "get_primary_thread", AsyncMock(return_value=thread))
    monkeypatch.setattr(hr_threads, "list_messages", AsyncMock(return_value=messages))
    call_llm = AsyncMock()
    monkeypatch.setattr(event_extract, "_call_llm", call_llm)

    result = await event_extract.extract_event("v1", account_id=7, db=AsyncMock())

    assert result is None
    call_llm.assert_not_awaited()
