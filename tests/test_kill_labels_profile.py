"""Шаг 27: подписи kill-факторов и KPI из SearchProfile."""

from __future__ import annotations

from core.domains.market.pulse import _kpi_defs
from core.domains.market.relevance import _kill_flags, compute_supply_report, kill_labels
from core.domains.profile.profile import SearchProfile


def test_kill_labels_without_profile() -> None:
    labels = kill_labels(None)
    assert labels["salary"] == "Зарплата ниже целевой"
    assert labels["remote"] == "Формат не подходит"
    assert labels["grade"] == "Грейд не тот"
    assert labels["stack"] == "Роль не по профилю"
    assert "Senior+" not in labels["grade"]
    assert "стек" not in labels["stack"].casefold()


def test_kill_labels_from_profile() -> None:
    profile = SearchProfile(
        salary_min=250_000,
        allows_remote=True,
        allows_hybrid=True,
        allows_office=False,
    )
    labels = kill_labels(profile)
    assert labels["salary"] == "Зарплата ниже 250к"
    assert "удалённый" in labels["remote"]
    assert "гибрид" in labels["remote"]
    assert "офис" not in labels["remote"]


def test_kill_flags_grade_uses_relative_scale() -> None:
    assert _kill_flags({"grade_match": {"level": "match"}})["grade"] is False
    assert _kill_flags({"grade_match": {"level": "above"}})["grade"] is False
    assert _kill_flags({"grade_match": {"level": "slightly_below"}})["grade"] is True
    assert _kill_flags({"grade_match": {"level": "senior_plus"}})["grade"] is True


def test_supply_kill_labels_follow_profile() -> None:
    rows = [
        (
            40,
            {
                "recommendation": "skip",
                "salary": {"meets_min": False},
                "grade_match": {"level": "far_below"},
                "role_content_match": {"score": 20},
                "remote_abroad_compat": {"level": "blocker"},
            },
            None,
        )
    ]
    profile = SearchProfile(salary_min=200_000, allows_hybrid=True)
    report = compute_supply_report(rows, profile=profile)
    by_key = {k.key: k.label for k in report.kill_factors}
    assert by_key["salary"] == "Зарплата ниже 200к"
    assert "гибрид" in by_key["remote"]
    assert by_key["grade"] == "Грейд не тот"
    assert by_key["stack"] == "Роль не по профилю"


def test_kpi_defs_addressable_from_profile() -> None:
    profile = SearchProfile(salary_min=250_000, allows_remote=True)
    defs = {key: (label, hint) for key, label, _unit, hint in _kpi_defs(profile)}
    assert "250к" in (defs["salary_meets"][0] or "")
    assert "250к" in (defs["addressable"][1] or "")
    assert "удалённый" in (defs["addressable"][1] or "")
    assert "450" not in (defs["addressable"][1] or "")
    assert "удалёнк" not in (defs["addressable"][1] or "")
    assert "удалёнк" not in (defs["real_remote"][0] or "")
