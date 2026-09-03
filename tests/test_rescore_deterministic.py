"""Этап 5 §5.2 (plans/scoring_precision_2026_08_17.md): перескор рубрики без LLM.

`overall_score` — детерминированная функция сохранённого `score` jsonb + `vacancy_text` +
текущих весов: `rescore_all_with_current_weights`/`recompute_job_weights` зовут ровно тот же
`apply_calibration`, что и живой скоринг (`_postprocess` в `scorer.py`) — определизм проверяется
на этом равенстве, а не на моке всего пайплайна.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities import rescore
from core.domains.opportunities.jobs import SOURCE_SKIP_STUB, Job
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.profile.model import DesiredPosition, ResumeData, SearchCriteria


def _score(**overrides: Any) -> ScoreResult:
    base = dict(
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
    base.update(overrides)
    return ScoreResult(**base)


def _job(*, score: ScoreResult | None = None, **overrides: Any) -> Job:
    fields = dict(
        id=1,
        vacancy_id="vac-1",
        vacancy_text="текст вакансии, формат работы: удалённо",
        company="ООО Ромашка",
        source="hh",
        is_archived=False,
        overall_score=score.overall_score if score else None,
        recommendation=score.recommendation if score else None,
        score=score.model_dump(mode="json") if score else {},
    )
    fields.update(overrides)
    return Job(**fields)


def _resume() -> ResumeData:
    return ResumeData(
        position=DesiredPosition(schedule=["Удалённо"]),
        search_criteria=SearchCriteria(),
    )


@pytest.fixture(autouse=True)
def _patch_resume_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resume(_account_id: int, db: object | None = None) -> ResumeData:
        return _resume()

    async def fake_manual_rules(_account_id: int) -> list:
        return []

    async def fake_skill_overlap(_vacancy_id: str | None, _profile: Any) -> None:
        return None

    monkeypatch.setattr(rescore, "read_resume_data_for_account", fake_resume)
    monkeypatch.setattr(rescore, "load_manual_company_adjustments", fake_manual_rules)
    monkeypatch.setattr(rescore, "load_list_company_adjustments", lambda _data: [])
    monkeypatch.setattr(rescore, "_load_skill_overlap", fake_skill_overlap)


@pytest.mark.asyncio
async def test_rescore_matches_live_apply_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Определизм: `_recompute_one` и прямой вызов `apply_calibration` с теми же входами дают
    один и тот же результат — это и есть гарантия, на которой стоит Этап 5.2."""
    from core.domains.opportunities.rules import apply_calibration, format_prefs_from_profile
    from core.domains.opportunities.score_breakdown import salary_prefs_from_profile
    from core.domains.profile.profile import derive_candidate_profile

    job = _job(score=_score())
    ctx = await rescore._resolve_rescore_context(account_id=1)

    live = apply_calibration(
        ScoreResult.model_validate(job.score),
        job.vacancy_text,
        company=job.company,
        company_adjustments=ctx.manual_rules,
        list_rules=ctx.list_rules,
        scoring_weights=ctx.scoring_weights,
        format_prefs=format_prefs_from_profile(ctx.profile),
        role_kind=ctx.profile.role_kind,
        salary_prefs=salary_prefs_from_profile(ctx.profile),
        skill_overlap=None,
    )
    via_rescore = await rescore._recompute_one(job, ctx=ctx)
    assert via_rescore is not None
    assert via_rescore.overall_score == live.overall_score
    assert via_rescore.score_breakdown == live.score_breakdown
    assert via_rescore.weights_version == live.weights_version
    # Определённые профилем/резюме входы стабильны — вызов дважды даёт одну и ту же версию.
    assert derive_candidate_profile(_resume()).role_kind == ctx.profile.role_kind


@pytest.mark.asyncio
async def test_recompute_keeps_manual_track_override() -> None:
    job = _job(score=_score(), track="second_job", track_override=True)
    ctx = await rescore._resolve_rescore_context(account_id=1)
    result = await rescore._recompute_one(job, ctx=ctx)
    assert result is not None
    assert result.track == "second_job"


@pytest.mark.asyncio
async def test_recompute_one_skips_empty_stub() -> None:
    stub = _job(score=None, source=SOURCE_SKIP_STUB, overall_score=99, recommendation="strong_apply")
    ctx = await rescore._resolve_rescore_context(account_id=1)
    result = await rescore._recompute_one(stub, ctx=ctx)
    assert result is None


@pytest.mark.asyncio
async def test_recompute_one_skips_invalid_score() -> None:
    broken = _job(score=None, overall_score=50, recommendation="apply")
    broken = broken.model_copy(update={"score": {"not": "a valid ScoreResult"}})
    ctx = await rescore._resolve_rescore_context(account_id=1)
    result = await rescore._recompute_one(broken, ctx=ctx)
    assert result is None


@pytest.mark.asyncio
async def test_rescore_all_writes_only_changed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    unchanged_score = _score()
    ctx = await rescore._resolve_rescore_context(account_id=1)
    fresh = await rescore._recompute_one(_job(score=unchanged_score), ctx=ctx)
    assert fresh is not None
    up_to_date = _job(
        id=1,
        vacancy_id="vac-up-to-date",
        score=fresh,
        overall_score=fresh.overall_score,
        recommendation=fresh.recommendation,
    )
    stale = _job(
        id=2,
        vacancy_id="vac-stale",
        score=unchanged_score,
        overall_score=1,
        recommendation="skip",
    )

    async def fake_list_jobs(*, account_id: int) -> list[Job]:
        return [up_to_date, stale]

    updates: list[str] = []

    async def fake_update_job_score(vacancy_id: str, **_kwargs: Any) -> None:
        updates.append(vacancy_id)

    monkeypatch.setattr(rescore, "list_jobs_for_rescore", fake_list_jobs)
    monkeypatch.setattr(rescore, "update_job_score", fake_update_job_score)
    monkeypatch.setattr(rescore, "publish_vacancy_scored", lambda **_kwargs: None)

    changed = await rescore.rescore_all_with_current_weights(account_id=1)

    assert changed == 1
    assert updates == ["vac-stale"]


@pytest.mark.asyncio
async def test_recompute_job_weights_skips_hr_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`hr_format_override` со слов HR не хранится в jsonb — узкий пересчёт без него тихо
    отменил бы override. hr_confirmed вакансии остаются как есть (Этап 5 §5.3)."""
    hr_job = _job(score=_score(), score_basis="hr_confirmed")

    async def fake_get_job(_vacancy_id: str, *, account_id: int) -> Job:
        return hr_job

    called = False

    async def fake_update_job_score(*_args: Any, **_kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job)
    monkeypatch.setattr(rescore, "update_job_score", fake_update_job_score)

    result = await rescore.recompute_job_weights("vac-1", account_id=1)

    assert result is hr_job
    assert called is False
