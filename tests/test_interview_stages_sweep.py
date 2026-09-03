"""Регресс §8 плана local_context_blind_spots_2026_08_12.md: ничего в `core/` не писало
`interview_stages.status='completed'` после того, как `scheduled_at` проходил — этап,
который никто не трогал после даты, навсегда оставался `scheduled`, и витрины вида
`next_stage_at` (`hr_threads.py::_THREAD_SELECT`) показывали прошедшую встречу как
предстоящую. `complete_past_stages` — детерминированный кросс-аккаунтный sweep, без LLM."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.preparation import interview_stages as stages_mod


class _FakeDb:
    def __init__(self, *, execute_result: str) -> None:
        self._execute_result = execute_result
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return self._execute_result

    async def fetchrow(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("complete_past_stages must not fetchrow — a single bulk UPDATE")

    async def fetch(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("complete_past_stages must not fetch — a single bulk UPDATE")


@pytest.mark.asyncio
async def test_complete_past_stages_updates_only_past_scheduled_rows() -> None:
    db = _FakeDb(execute_result="UPDATE 3")

    n = await stages_mod.complete_past_stages(db=db)

    assert n == 3
    assert len(db.execute_calls) == 1
    sql, args = db.execute_calls[0]
    s = sql.lower()
    assert args == ()  # без account_id — системная кросс-аккаунтная чистка
    assert "update interview_stages" in s
    assert "status = 'completed'" in s
    assert "status = 'scheduled'" in s
    assert "scheduled_at < now()" in s


@pytest.mark.asyncio
async def test_complete_past_stages_no_matches_returns_zero() -> None:
    db = _FakeDb(execute_result="UPDATE 0")

    n = await stages_mod.complete_past_stages(db=db)

    assert n == 0
