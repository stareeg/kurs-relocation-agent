"""FR3-72: матч вакансии по компании — ярус воронки + дизамбигуация без silent pick."""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.opportunities.jobs import Job, company_match_tier, pick_company_match_candidates
from core.kernel.schemas.funnel import FunnelStatus
from core.domains.pipeline.vacancy_attach_suggest import _label, _relative_activity


def _job(
    vacancy_id: str,
    *,
    status: str | None,
    title: str = "Lead LLM",
    scored_at: datetime | None = None,
    is_archived: bool = False,
) -> Job:
    return Job(
        vacancy_id=vacancy_id,
        company="Яндекс",
        title=title,
        vacancy_text="x",
        status=status,
        is_archived=is_archived,
        scored_at=scored_at,
    )


def test_company_match_tier_prefers_engaged_over_terminal():
    assert company_match_tier(FunnelStatus.SCREENING.value) == 0
    assert company_match_tier(FunnelStatus.VIEWED.value) == 1
    assert company_match_tier(FunnelStatus.REJECTED.value) == 2
    assert company_match_tier(FunnelStatus.ARCHIVE.value) == 2
    assert company_match_tier(FunnelStatus.APPLIED.value, is_archived=True) == 2


def test_pick_prefers_single_active_over_newer_rejected():
    """Активная побеждает даже если отказ свежее по scored_at (раньше был silent bug)."""
    newer_reject = _job(
        "rej",
        status=FunnelStatus.REJECTED.value,
        scored_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    older_active = _job(
        "act",
        status=FunnelStatus.SCREENING.value,
        scored_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    cands = pick_company_match_candidates([newer_reject, older_active])
    assert [j.vacancy_id for j in cands] == ["act"]


def test_pick_two_active_returns_both_for_disambiguation():
    """Две активные одной компании → оба кандидата, не «последняя по scored_at»."""
    a = _job(
        "a",
        status=FunnelStatus.APPLIED.value,
        title="Lead LLM A",
        scored_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    b = _job(
        "b",
        status=FunnelStatus.SCREENING.value,
        title="Lead LLM B",
        scored_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    archived = _job(
        "old",
        status=FunnelStatus.ARCHIVE.value,
        scored_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    cands = pick_company_match_candidates([a, b, archived])
    assert {j.vacancy_id for j in cands} == {"a", "b"}


def test_pick_only_terminals_ambiguous_returns_all():
    cands = pick_company_match_candidates(
        [
            _job("r1", status=FunnelStatus.REJECTED.value),
            _job("r2", status=FunnelStatus.ARCHIVE.value),
        ]
    )
    assert {j.vacancy_id for j in cands} == {"r1", "r2"}


def test_label_includes_status_and_relative_date():
    """FR3-73: подпись различает две роли одной компании."""
    at = datetime(2026, 7, 20, tzinfo=UTC)
    now = datetime(2026, 7, 22, tzinfo=UTC)
    assert _relative_activity(at, now=now) == "2 дн назад"
    assert _relative_activity(now, now=now) == "сегодня"
    label = _label("Яндекс", "Lead LLM", "123", status="Скрининг", activity_at=None)
    assert label == "Яндекс · Lead LLM · Скрининг"
