"""Этап 7 §7.4 (D12): сборка блока «Выученные предпочтения» — чисто, без БД."""

from __future__ import annotations

import pytest

from core.domains.opportunities import preferences_digest
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.preferences_digest import (
    build_preferences_block,
    learned_preferences_block_safe,
)
from core.kernel.schemas.funnel import FunnelStatus


def _job(job_id: int, *, status: str, niches: list[str] | None = None) -> Job:
    score = {"role_content_match": {"matched_niche": niches or []}} if niches is not None else {}
    return Job(id=job_id, vacancy_id=str(job_id), vacancy_text="x" * 40, status=status, score=score)


def test_empty_below_both_minimums():
    assert build_preferences_block([], []) == ""


def test_skip_reasons_below_minimum_are_dropped():
    jobs = [
        _job(i, status=FunnelStatus.APPLIED.value, niches=["MLOps"]) for i in range(1, 4)
    ]  # 3 responded — ровно минимум
    block = build_preferences_block(["Низкая зарплата", "Низкая зарплата"], jobs)  # 2 < минимума 5
    assert "Причины" not in block
    assert "MLOps" in block


def test_niches_below_minimum_are_dropped():
    skip_reasons = ["Низкая зарплата"] * 5
    jobs = [_job(1, status=FunnelStatus.VIEWED.value)]  # 0 responded < минимума 3
    block = build_preferences_block(skip_reasons, jobs)
    assert "Ниши" not in block
    assert "Низкая зарплата (5)" in block


def test_full_block_includes_both_sections_canonicalized_and_ranked():
    skip_reasons = ["Сомнительная компания"] * 6 + ["Низкая зарплата"] * 3
    jobs = [
        _job(1, status=FunnelStatus.APPLIED.value, niches=["MLOps", "LLM-инфраструктура"]),
        _job(2, status=FunnelStatus.APPLIED.value, niches=["MLOps"]),
        _job(3, status=FunnelStatus.REJECTED.value, niches=["RAG"]),
        _job(4, status=FunnelStatus.VIEWED.value, niches=["Не должно попасть"]),
    ]
    block = build_preferences_block(skip_reasons, jobs)
    assert block.startswith("ВЫУЧЕННЫЕ ПРЕДПОЧТЕНИЯ")
    assert "MLOps" in block
    assert "Не должно попасть" not in block
    # Legacy-строка канонизируется до подсчёта — попадает в «Избегать компанию», не под сырым именем.
    assert "Избегать компанию (6)" in block
    assert "Сомнительная компания" not in block


async def test_learned_preferences_block_safe_swallows_errors(monkeypatch: pytest.MonkeyPatch):
    async def boom(_account_id: int, **_kwargs: object) -> str:
        raise RuntimeError("Postgres недоступен")

    monkeypatch.setattr(preferences_digest, "learned_preferences_block", boom)

    result = await learned_preferences_block_safe(1)
    assert result == ""
