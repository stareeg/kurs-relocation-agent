"""plans/local_context_blind_spots_2026_08_12.md §8: `interview_stages_sweep` — новый cron-слот
в `bot_app.services.scheduler`, зовёт `complete_past_stages` раз в сутки (не зависит от `Bot`)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bot_app.services import scheduler


@pytest.mark.asyncio
async def test_run_interview_stages_sweep_calls_complete_past_stages() -> None:
    with patch(
        "core.domains.preparation.interview_stages.complete_past_stages",
        AsyncMock(return_value=5),
    ) as fake_sweep:
        await scheduler._run_interview_stages_sweep({})

    fake_sweep.assert_awaited_once_with()


def test_interview_stages_sweep_registered() -> None:
    assert scheduler.KIND_INTERVIEW_STAGES_SWEEP == "interview_stages_sweep"
