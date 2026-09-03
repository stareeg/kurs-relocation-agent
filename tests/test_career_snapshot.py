"""Снимок «Где я сейчас» (Э9.2) — только факты, которые система уже знает."""

from __future__ import annotations

from datetime import UTC, datetime

import core.domains.career.search_state as search_state_mod
import core.domains.career.track_state as track_state_mod
import core.domains.market.stage_aging as stage_aging_mod
import core.domains.opportunities.jobs as jobs_mod
import core.domains.profile.profile as profile_mod
import core.domains.profile.resume_score as resume_score_mod
from core.app.scenarios.career_snapshot import career_snapshot
from core.domains.career.search_state import SearchModeState
from core.domains.career.track_state import TrackState
from core.domains.market.stage_aging import StageAging
from core.domains.profile.profile import CandidateProfile
from core.domains.profile.resume_score import ResumeScoreSnapshot


def _mock_empty_defaults(monkeypatch) -> None:
    """Замокать все куски снимка на пустые/дефолтные значения — как у свежего аккаунта.

    Тесты, которым важен один конкретный кусок, зовут это первым и переопределяют нужный
    мок поверх — так ни один тест не бьёт по реальному Postgres молча.
    """

    async def _mode(*, account_id, db=None):
        return SearchModeState(mode="active", label="Активно ищу")

    async def _tracks(*, account_id, db=None):
        return TrackState(tracks=["primary"], labels=["Основная работа"], second_job_enabled=False)

    async def _profile(*, account_id, db=None, **kw):
        return CandidateProfile()

    async def _days_active(*, account_id, db=None):
        return None

    async def _active_jobs(*, account_id, db=None):
        return 0

    async def _stage_aging(*, account_id, db=None):
        return StageAging()

    async def _score(*, cutoff=None, account_id, db=None):
        return None

    monkeypatch.setattr(search_state_mod, "get_current_state", _mode)
    monkeypatch.setattr(track_state_mod, "get_current_tracks", _tracks)
    monkeypatch.setattr(profile_mod, "load_candidate_profile_enriched", _profile)
    monkeypatch.setattr(jobs_mod, "get_days_active", _days_active)
    monkeypatch.setattr(jobs_mod, "count_active_jobs", _active_jobs)
    monkeypatch.setattr(stage_aging_mod, "get_stage_aging", _stage_aging)
    monkeypatch.setattr(resume_score_mod, "load_score_at", _score)


async def test_empty_account_gets_honest_defaults(monkeypatch) -> None:
    """Свежий аккаунт: ни одной оценённой вакансии, ни одного снимка балла — не нули-выдумки."""
    _mock_empty_defaults(monkeypatch)

    snap = await career_snapshot(account_id=1)

    assert snap.employment == "unknown"  # CandidateProfile() → currently_employed=None
    assert snap.days_active is None
    assert snap.resume_score is None
    assert snap.active_applications == 0
    assert snap.stalled == 0
    assert snap.tracks == ["Основная работа"]
    assert snap.search_mode_label == "Активно ищу"


async def test_employed_maps_to_employment_employed(monkeypatch) -> None:
    _mock_empty_defaults(monkeypatch)

    async def _profile(*, account_id, db=None, **kw):
        return CandidateProfile(currently_employed=True)

    monkeypatch.setattr(profile_mod, "load_candidate_profile_enriched", _profile)

    snap = await career_snapshot(account_id=1)
    assert snap.employment == "employed"


async def test_populated_account_reflects_real_numbers(monkeypatch) -> None:
    _mock_empty_defaults(monkeypatch)

    async def _mode(*, account_id, db=None):
        return SearchModeState(mode="passive", label="Рассматриваю")

    async def _tracks(*, account_id, db=None):
        return TrackState(
            tracks=["primary", "second_job"],
            labels=["Основная работа", "Вторая работа"],
            second_job_enabled=True,
        )

    async def _profile(*, account_id, db=None, **kw):
        return CandidateProfile(currently_employed=True, market_scope_label="Международный")

    async def _days_active(*, account_id, db=None):
        return 47

    async def _active_jobs(*, account_id, db=None):
        return 12

    async def _stage_aging(*, account_id, db=None):
        return StageAging(available=True, total_active=12, stalled_count=3)

    async def _score(*, cutoff=None, account_id, db=None):
        return ResumeScoreSnapshot(
            total=86,
            structure=90,
            writing=80,
            role_fit=88,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(search_state_mod, "get_current_state", _mode)
    monkeypatch.setattr(track_state_mod, "get_current_tracks", _tracks)
    monkeypatch.setattr(profile_mod, "load_candidate_profile_enriched", _profile)
    monkeypatch.setattr(jobs_mod, "get_days_active", _days_active)
    monkeypatch.setattr(jobs_mod, "count_active_jobs", _active_jobs)
    monkeypatch.setattr(stage_aging_mod, "get_stage_aging", _stage_aging)
    monkeypatch.setattr(resume_score_mod, "load_score_at", _score)

    snap = await career_snapshot(account_id=1)

    assert snap.employment == "employed"
    assert snap.search_mode_label == "Рассматриваю"
    assert snap.market_scope_label == "Международный"
    assert snap.tracks == ["Основная работа", "Вторая работа"]
    assert snap.days_active == 47
    assert snap.active_applications == 12
    assert snap.stalled == 3
    assert snap.resume_score == 86


async def test_one_broken_piece_does_not_break_whole_snapshot(monkeypatch) -> None:
    """Best-effort: сбой в одном куске (например, стейдж-эйджинг) не валит весь снимок."""
    _mock_empty_defaults(monkeypatch)

    async def _boom(*, account_id, db=None):
        raise RuntimeError("PG недоступен")

    monkeypatch.setattr(stage_aging_mod, "get_stage_aging", _boom)
    monkeypatch.setattr(jobs_mod, "count_active_jobs", _boom)

    snap = await career_snapshot(account_id=1)
    assert snap.search_mode_label == "Активно ищу"
    assert snap.stalled == 0
    assert snap.active_applications == 0
