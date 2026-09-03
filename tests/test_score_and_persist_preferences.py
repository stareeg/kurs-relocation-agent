"""Этап 7 §7.4 (D12): `score_and_persist` наконец передаёт `preferences` в `score_vacancy`.

До фикса ни один продовый вызывающий `score_vacancy(..., preferences=...)` не передавал —
параметр был мёртвой обвязкой (plans/scoring_precision_2026_08_17.md §1.9). `persist.py` — тот
единственный путь, который план указывает чинить (§7.4); best-effort-фетч не должен ронять
скоринг при сбое.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities import persist
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    VacancyInput,
)


def _score() -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_remote(_text: str) -> None:
        return None

    async def fake_persist_scored(vac: VacancyInput, score: ScoreResult, **_kwargs: Any):
        job = Job(vacancy_id=vac.vacancy_id, vacancy_text=vac.text, overall_score=score.overall_score)
        return persist.ScoredJob(job=job, score=score)

    monkeypatch.setattr(persist, "assess_remote_feasibility_safe", fake_remote)
    monkeypatch.setattr(persist, "persist_scored", fake_persist_scored)


async def test_score_and_persist_forwards_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_score_vacancy(_text: str, **kwargs: Any) -> ScoreResult:
        captured.update(kwargs)
        return _score()

    async def fake_preferences(_account_id: int, **_kwargs: Any) -> str:
        return "ВЫУЧЕННЫЕ ПРЕДПОЧТЕНИЯ: ниши — MLOps."

    monkeypatch.setattr(persist, "score_vacancy", fake_score_vacancy)
    monkeypatch.setattr(persist, "learned_preferences_block_safe", fake_preferences)

    await persist.score_and_persist(
        VacancyInput(text="x" * 60), account_id=1
    )

    assert captured["preferences"] == "ВЫУЧЕННЫЕ ПРЕДПОЧТЕНИЯ: ниши — MLOps."


async def test_score_and_persist_scores_normally_when_preferences_come_back_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Резильентность живёт в `learned_preferences_block_safe` (см. test_preferences_digest.py):
    любой её сбой уже превращён в `""`. Здесь проверяем внешнюю границу — пустой блок не мешает
    скорингу пройти как обычно, промпт остаётся «как раньше»."""
    captured: dict[str, Any] = {}

    async def fake_score_vacancy(_text: str, **kwargs: Any) -> ScoreResult:
        captured.update(kwargs)
        return _score()

    async def empty_preferences(_account_id: int, **_kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(persist, "score_vacancy", fake_score_vacancy)
    monkeypatch.setattr(persist, "learned_preferences_block_safe", empty_preferences)

    scored = await persist.score_and_persist(VacancyInput(text="x" * 60), account_id=1)

    assert captured["preferences"] == ""
    assert scored.score.overall_score == 80
