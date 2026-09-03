"""Шаг 17–18: SalaryEstimate без пола 100к, относительный разброс, якорь от резюме."""

from __future__ import annotations

from pathlib import Path

from core.domains.opportunities.salary_estimator import (
    SalaryEstimate,
    clamp_and_narrow,
    round_step_for,
    spread_bounds,
)


def test_spread_bounds_relative_to_mid():
    lo_mid, hi_mid = spread_bounds(150_000)
    assert lo_mid == max(10_000, round(150_000 * 0.12))  # 18_000
    assert hi_mid == max(50_000, round(150_000 * 0.35))  # 52_500

    lo_hi, hi_hi = spread_bounds(500_000)
    assert lo_hi == max(10_000, round(500_000 * 0.12))  # 60_000
    assert hi_hi == max(50_000, round(500_000 * 0.35))  # 175_000


def test_round_step_by_order():
    assert round_step_for(150_000) == 5_000
    assert round_step_for(199_999) == 5_000
    assert round_step_for(200_000) == 10_000
    assert round_step_for(500_000) == 10_000


def test_mid_market_130_170_validates_without_50k_expand():
    """Пол 100к снят; min_spread от mid (~18к) не раздувает вилку 40к до 50к."""
    est = SalaryEstimate(
        salary_min=130_000,
        salary_max=170_000,
        meets_min=False,
        note="mid-рынок",
    )
    assert est.salary_min == 130_000
    assert est.salary_max == 170_000
    assert est.salary_max - est.salary_min == 40_000
    assert est.confidence == "low"
    assert est.source == "none"

    lo, hi = clamp_and_narrow(130_000, 170_000)
    assert (lo, hi) == (130_000, 170_000)


def test_senior_450_550_unchanged():
    """Старшая вилка 100к спреда — как раньше, без сужения/раздувания."""
    est = SalaryEstimate(
        salary_min=450_000,
        salary_max=550_000,
        meets_min=True,
        note="senior IT",
    )
    assert est.salary_min == 450_000
    assert est.salary_max == 550_000
    assert est.salary_max - est.salary_min == 100_000

    lo, hi = clamp_and_narrow(450_000, 550_000)
    assert (lo, hi) == (450_000, 550_000)


def test_pm_anchor_estimate_match_not_static_mid_bench():
    """Шаг 18: PM (250к, comfortable пуст) + match → 250–325к, не 340–440к."""
    from core.domains.opportunities.salary_estimator import anchor_estimate
    from core.domains.profile.profile import SearchProfile

    profile = SearchProfile(salary_min=250_000, salary_comfortable=0)
    assert profile.salary_anchor_base() == (250_000, 325_000)
    assert anchor_estimate(profile, "match") == (250_000, 325_000)
    assert anchor_estimate(profile, "off_profile") is None
    assert anchor_estimate(SearchProfile(salary_min=0), "match") is None


def test_optional_benchmarks_file_loads_when_path_set(tmp_path, monkeypatch):
    from core.config import get_settings
    from core.domains.opportunities import salary_estimator as se

    src = Path("deploy/salary_benchmarks.example.json")
    dest = tmp_path / "bench.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("SALARY_BENCHMARKS_PATH", str(dest))
    get_settings.cache_clear()
    se._cached_salary_benchmarks.cache_clear()
    try:
        bench = se.get_benchmark("startup", "senior_plus")
        assert bench == (380_000, 480_000)
        assert se.get_benchmark("unknown", "mid") == (340_000, 440_000)
    finally:
        monkeypatch.delenv("SALARY_BENCHMARKS_PATH", raising=False)
        get_settings.cache_clear()
        se._cached_salary_benchmarks.cache_clear()
        assert se.get_benchmark("startup", "senior_plus") is None


def test_apply_benchmarks_keeps_range_and_does_not_judge_vs_anchor():
    """2026-08-08: вилка NOT сравнивается с желаемой зарплатой резюме.

    Раньше `apply_benchmarks` понижал честную рыночную оценку до confidence=low просто
    потому, что она расходилась с ориентиром кандидата — это ломало карточки вакансий
    (все оценки ниже желаемого висели «грубая оценка»). Теперь числа нормализуются, а
    провенанс оценки не зависит от якоря.
    """
    from core.domains.opportunities.salary_estimator import apply_benchmarks, finalize_estimate
    from core.domains.profile.profile import SearchProfile

    profile = SearchProfile(salary_min=250_000, salary_comfortable=0)
    lo, hi = apply_benchmarks(130_000, 170_000, "media", "match", profile=profile)
    assert (lo, hi) == (130_000, 170_000)

    est = finalize_estimate(
        130_000, 170_000, "media", "match", "llm", source="llm", profile=profile
    )
    assert est.salary_min == 130_000
    assert est.salary_max == 170_000
    assert est.confidence == "medium"
    assert est.source == "llm"


def test_apply_benchmarks_scopes_wide_range():
    """Слишком широкую вилку все равно сужаем к середине — это единственная работа функции."""
    from core.domains.opportunities.salary_estimator import apply_benchmarks

    lo, hi = apply_benchmarks(200_000, 1_200_000, "product", "match", profile=None)
    # max_spread ≈ 35% от середины (700к) = 245к; не шире этого.
    assert (hi - lo) <= 245_000
