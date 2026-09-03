"""L-21: сборка контекста подготовки — блоки параллельно, не последовательно.

`gather_prep_context` гоняет 8 независимых блоков через `core.app.pipeline.Pipeline`
вместо 7 последовательных `await`. Тест бьёт тревогу, если кто-то вернёт
блоки к последовательной сборке: с задержкой `DELAY` на блок сумма при `await`
подряд была бы ~8×DELAY, при параллельной сборке — ~1×DELAY.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.domains.preparation.interview.prep_context import PrepContext, gather_prep_context

DELAY = 0.05
_BLOCKS = (
    "_next_stage_block",
    "_hr_facts_block",
    "_weak_topics_block",
    "_strong_answers_block",
    "_recruiter_feedback_block",
    "_asked_questions_block",
    "_past_sessions_block",
)


@pytest.mark.asyncio
async def test_gather_prep_context_runs_blocks_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_empty(*_a, **_k) -> str:
        await asyncio.sleep(DELAY)
        return ""

    for name in _BLOCKS:
        monkeypatch.setattr(
            f"core.domains.preparation.interview.prep_context.{name}", _slow_empty
        )

    async def _slow_career_facts(*_a, **_k) -> str:
        await asyncio.sleep(DELAY)
        return ""

    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._career_facts_block",
        _slow_career_facts,
    )

    fake_db = object()
    started = time.monotonic()
    ctx = await gather_prep_context("hh-next", "theory", account_id=1, db=fake_db)  # type: ignore[arg-type]
    elapsed = time.monotonic() - started

    assert isinstance(ctx, PrepContext)
    # Последовательно 8 блоков заняли бы ~8×DELAY; параллельно — ~1×DELAY.
    assert elapsed < DELAY * 4
