"""Тесты готовности левой панели, criteria_alignment и writing на быстром пути."""

from __future__ import annotations

from core.domains.profile.gap import (
    ResumeGapReport,
    ResumeScoreBreakdown,
    WeakBullet,
    assemble_score,
    reconcile_fast_writing,
)
from core.domains.profile.model import ResumeData, SearchCriteria, to_markdown
from core.domains.profile.score_criteria import (
    blend_role_fit,
    criteria_alignment_checks,
    left_panel_gaps,
    left_panel_hints,
    left_panel_ready_for_score,
    score_criteria_alignment,
)


def _criteria_resume(**overrides) -> ResumeData:
    base = ResumeData(
        position={
            "title": "Python-разработчик",
            "grade": ["Senior"],
            "schedule": ["Удалённо"],
            "salary_min": 300000,
        },
        search_criteria=SearchCriteria(
            role_kind="hands_on",
            market_segment="FinTech",
            niches=["LLM/RAG"],
        ),
    )
    return base.model_copy(update=overrides) if overrides else base


def test_left_panel_gaps_when_empty() -> None:
    empty = ResumeData()
    gaps = left_panel_gaps(empty)
    assert "role_kind" in gaps
    assert "market_segment" not in gaps
    assert "niches" in gaps
    assert "grade_or_salary" in gaps
    assert "schedule" in gaps
    assert not left_panel_ready_for_score(empty)
    assert len(left_panel_hints(empty)) == len(gaps)


def test_left_panel_ready_with_any_market_segment() -> None:
    """Пустой market_segment = «Любые» — панель готова, балл не блокируется."""
    data = _criteria_resume(search_criteria=SearchCriteria(role_kind="hands_on", niches=["LLM"]))
    assert left_panel_ready_for_score(data)
    assert left_panel_gaps(data) == []


def test_left_panel_ready_when_filled() -> None:
    data = _criteria_resume()
    assert left_panel_ready_for_score(data)
    assert left_panel_gaps(data) == []


def test_reconcile_fast_writing_updates_total() -> None:
    data = ResumeData(
        experience=[
            {
                "company": "Acme",
                "position": "Dev",
                "description": "- Отвечал за качество\n- Спроектировал API, latency 200ms → 40ms",
            }
        ]
    )
    report = ResumeGapReport(available=False, corpus_size=0)
    score = assemble_score(data, "text", report, weak=[], writing=100, role_fit=80)
    weak = [WeakBullet(section="experience", ref="Acme — Dev", index=0, text="Отвечал за качество")]
    reconciled = reconcile_fast_writing(score, data, weak)
    assert reconciled.writing < score.writing
    assert reconciled.total != score.total
    assert len(reconciled.weak_bullets) == 1


def test_reconcile_fast_writing_zero_bullets_not_inflated() -> None:
    """Проса без маркеров буллетов — writing=0, не завышать из снимка."""
    data = ResumeData(
        experience=[
            {
                "company": "Acme",
                "position": "Dev",
                "description": "Просто абзац без списка — LLM иногда так пишет после ATS.",
            }
        ]
    )
    score = ResumeScoreBreakdown(
        total=75,
        structure=80,
        market_coverage=None,
        writing=90,
        role_fit=70,
    )
    reconciled = reconcile_fast_writing(score, data, [])
    assert reconciled.writing == 0


def test_criteria_alignment_high_when_axes_in_text() -> None:
    data = _criteria_resume()
    text = to_markdown(data)
    alignment = score_criteria_alignment(data, text)
    assert alignment >= 70
    checks = dict(criteria_alignment_checks(data, text))
    assert checks.get("title") is True
    assert checks.get("niches") is True


def test_blend_role_fit_weights() -> None:
    assert blend_role_fit(80, 100) == 83
    assert blend_role_fit(0, 0) == 0


def test_criteria_alignment_low_when_text_off_profile() -> None:
    data = _criteria_resume()
    text = "Случайный текст без следов роли и ниш."
    assert score_criteria_alignment(data, text) < 50
