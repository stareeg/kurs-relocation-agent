"""Регресс для инцидента «ТехВилл» (2026-08-12): hh_negotiations-синк с LLM-guard-override
понизил вакансию со «Скрининг» в «Отказ», хотя в системе уже была назначенная встреча
(`interview_stages`) и импортированная переписка с HR (`hr_messages`) — LLM видел только
куцый бейдж hh.ru, не эти локальные факты. `_has_active_local_evidence` должно блокировать
сам вызов override-LLM, когда такие факты уже есть в БД."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.pipeline.negotiations import _has_active_local_evidence


class _FakeDb:
    def __init__(
        self,
        *,
        stage_rows: list[dict[str, Any]] | None = None,
        thread_row: dict[str, Any] | None = None,
        message_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._stage_rows = stage_rows or []
        self._thread_row = thread_row
        self._message_rows = message_rows or []

    async def fetch(self, sql: str, *_args: Any) -> list[dict[str, Any]]:
        s = sql.lower()
        if "from interview_stages" in s:
            return self._stage_rows
        if "from hr_messages" in s:
            return self._message_rows
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *_args: Any) -> dict[str, Any] | None:
        s = sql.lower()
        if "select id from hr_threads" in s:
            return {"id": self._thread_row["id"]} if self._thread_row else None
        if "from hr_threads t" in s:
            return self._thread_row
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def fetchval(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("_has_active_local_evidence must not call fetchval")

    async def execute(self, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("_has_active_local_evidence must not write")

    async def executemany(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("_has_active_local_evidence must not write")


def _stage_row(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 6,
        "vacancy_id": "135719770",
        "stage_type": "hr_screening",
        "scheduled_at": None,
        "format": "online",
        "status": "scheduled",
        "position": 0,
        "notes": "",
        "source_message_id": None,
        "created_at": None,
    }
    base.update(kwargs)
    return base


def _thread_row(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 11,
        "vacancy_id": "135719770",
        "contact_name": "Yulia",
        "channel": "telegram",
        "company": "ТехВилл",
        "status": "active",
        "created_at": None,
        "updated_at": None,
        "suggested_funnel_status": None,
        "suggested_stage_type": None,
        "suggestion_source_message_id": None,
        "message_count": 0,
        "last_message_at": None,
        "last_hr_kind": None,
        "last_hr_at": None,
        "next_stage_type": None,
        "next_stage_at": None,
    }
    base.update(kwargs)
    return base


def _message_row(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 58,
        "thread_id": 11,
        "direction": "in",
        "kind": "hr_in",
        "body": "Егор, добрый день!",
        "sent_at": None,
        "created_at": None,
        "author_uncertain": False,
        "reply_to_message_id": None,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_scheduled_interview_stage_is_active_evidence() -> None:
    db = _FakeDb(stage_rows=[_stage_row(status="scheduled")])
    assert await _has_active_local_evidence("135719770", account_id=1, db=db) is True


@pytest.mark.asyncio
async def test_real_hr_correspondence_is_active_evidence_without_stage() -> None:
    db = _FakeDb(
        stage_rows=[],
        thread_row=_thread_row(),
        message_rows=[_message_row()],
    )
    assert await _has_active_local_evidence("135719770", account_id=1, db=db) is True


@pytest.mark.asyncio
async def test_no_stage_no_thread_no_evidence() -> None:
    db = _FakeDb(stage_rows=[], thread_row=None, message_rows=[])
    assert await _has_active_local_evidence("135719770", account_id=1, db=db) is False


@pytest.mark.asyncio
async def test_thread_with_only_llm_chatter_is_not_evidence() -> None:
    # Тред существует (LLM-чат по вакансии открывали), но реальной hr_in/hr_out переписки нет —
    # llm_user/llm_assistant не считаются доказательством живого процесса с HR.
    db = _FakeDb(
        stage_rows=[],
        thread_row=_thread_row(),
        message_rows=[_message_row(kind="llm_user"), _message_row(kind="llm_assistant")],
    )
    assert await _has_active_local_evidence("135719770", account_id=1, db=db) is False


@pytest.mark.asyncio
async def test_cancelled_stage_is_not_active_evidence() -> None:
    db = _FakeDb(stage_rows=[_stage_row(status="cancelled")])
    assert await _has_active_local_evidence("135719770", account_id=1, db=db) is False


@pytest.mark.asyncio
async def test_empty_vacancy_id_short_circuits() -> None:
    db = _FakeDb()
    assert await _has_active_local_evidence("", account_id=1, db=db) is False
