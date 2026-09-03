"""Этап 2 (plans/scoring_precision_2026_08_17.md §4): ось зарплаты вокруг рампы.

Здесь — обвязка, без которой рампа не доедет до балла: пересчёт оси после фоновой вилки
(81% вакансий прода получают её уже ПОСЛЕ скоринга), вердикт `meets_min` по числам вместо
догадки основного скоринга и сравнение gross-оценки с net-порогом кандидата.
Сама таблица рампы — в `tests/test_score_breakdown.py`.
"""

from __future__ import annotations

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.rules import recompute_salary_axis
from core.domains.opportunities.salary_estimator import SalaryEstimate, finalize_estimate
from core.domains.opportunities.score_breakdown import SalaryPrefs
from core.domains.opportunities.scorer import _merge_salary_estimate
from core.domains.profile.profile import SearchProfile
from core.kernel.money import detect_tax_basis

_PREFS = SalaryPrefs(floor=400_000, comfortable=500_000, basis="net")

# Скор уже посчитан и сохранён: ось зарплаты стоит нейтрально (11 из 20), вилки ещё нет.
_PENDING_BREAKDOWN = {
    "salary": 11,
    "work_format": 20,
    "grade_match": 15,
    "role_content": 12,
    "management": 12,
    "company": 10,
}


def _scored(
    *,
    salary: SalaryInfo,
    breakdown: dict[str, int] | None = _PENDING_BREAKDOWN,
    overall: int = 80,
    gate: str | None = None,
) -> ScoreResult:
    return ScoreResult(
        overall_score=overall,
        recommendation="skip" if gate else "strong_apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=salary,
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
        score_breakdown=dict(breakdown) if breakdown else {},
        gate_triggered=gate,
    )


def _arrived(lo: int, hi: int, *, source: str = "llm", confidence: str = "medium") -> SalaryInfo:
    return SalaryInfo(
        meets_min=True,
        value_or_range="",
        estimated_range="оценка",
        estimated_min=lo,
        estimated_max=hi,
        note="",
        confidence=confidence,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
    )


def test_background_range_moves_only_the_salary_axis():
    """Приехала сильная вилка → ось выросла, остальные оси и итог сдвинулись ровно на дельту."""
    score = _scored(salary=_arrived(560_000, 640_000, source="corpus", confidence="high"))
    result = recompute_salary_axis(score, salary_prefs=_PREFS)

    assert result.score_breakdown["salary"] > _PENDING_BREAKDOWN["salary"]
    delta = result.score_breakdown["salary"] - _PENDING_BREAKDOWN["salary"]
    assert result.overall_score == 80 + delta
    for axis, points in _PENDING_BREAKDOWN.items():
        if axis != "salary":
            assert result.score_breakdown[axis] == points


def test_background_low_range_lowers_score_and_recommendation():
    """Вилка вдвое ниже порога — балл падает, вердикт пересчитывается по новому числу."""
    score = _scored(salary=_arrived(190_000, 210_000, source="corpus", confidence="high"))
    result = recompute_salary_axis(score, salary_prefs=_PREFS)

    assert result.score_breakdown["salary"] < _PENDING_BREAKDOWN["salary"]
    assert result.overall_score < 80
    assert result.recommendation == "apply"  # 80 → ниже strong_apply, но выше maybe


def test_recompute_keeps_gate_verdict():
    """Гейт — отдельный флаг: пересчёт оси не выпускает вакансию из skip."""
    score = _scored(
        salary=_arrived(700_000, 800_000, source="corpus", confidence="high"),
        gate="Балл срезан: формат-гейт",
    )
    result = recompute_salary_axis(score, salary_prefs=_PREFS)

    assert result.overall_score > 80
    assert result.recommendation == "skip"


def test_recompute_without_stored_breakdown_is_a_noop():
    """Старый jsonb без breakdown — пересчитывать не от чего, число не трогаем."""
    score = _scored(salary=_arrived(600_000, 700_000), breakdown=None)
    assert recompute_salary_axis(score, salary_prefs=_PREFS) is score


def test_recompute_without_prefs_does_not_invent_a_threshold():
    """Порога в резюме нет → булев путь; здесь meets_min=True, значит ось идёт на полный вес."""
    score = _scored(salary=_arrived(120_000, 140_000))
    result = recompute_salary_axis(score)
    assert result.score_breakdown["salary"] == 20


def test_merged_estimate_verdict_comes_from_numbers_not_from_the_guess():
    """§1.3: `meets_min` основного скоринга — догадка «нейтрально по контексту», числа сильнее."""
    base = _scored(salary=SalaryInfo(meets_min=True, value_or_range="", note=""))
    estimate = SalaryEstimate(
        salary_min=200_000,
        salary_max=240_000,
        meets_min=False,
        note="оценка",
        confidence="medium",
        source="llm",
    )
    merged = _merge_salary_estimate(base, estimate)

    assert merged.salary.meets_min is False
    assert merged.salary.source == "llm"
    assert merged.salary.estimate_pending is False


def test_llm_estimate_meets_min_is_measured_in_net():
    """§2.3: вилку просят в gross, порог кандидата — на руки; сравниваем после ×0.87."""
    profile = SearchProfile(salary_min=400_000, salary_comfortable=500_000)
    borderline = finalize_estimate(
        450_000, 550_000, "product", "match", "оценка", source="llm", profile=profile
    )
    clearly_above = finalize_estimate(
        500_000, 600_000, "product", "match", "оценка", source="llm", profile=profile
    )

    # 450k gross ≈ 390k на руки — порог 400k не проходит, хотя «по цифрам» выглядит выше.
    assert borderline.meets_min is False
    assert clearly_above.meets_min is True
    # Сами числа остаются gross: рыночная аналитика читает их как gross (market._salary_net_mid).
    assert borderline.salary_min == 450_000


def test_gross_profile_threshold_is_not_converted_twice():
    """Порог указан «до вычета» — обе стороны в gross, лишнего ×0.87 не случается."""
    profile = SearchProfile(salary_min=450_000, salary_basis="gross")
    est = finalize_estimate(
        450_000, 550_000, "product", "match", "оценка", source="llm", profile=profile
    )
    assert est.meets_min is True


def test_detect_tax_basis_reads_words_not_numbers():
    assert detect_tax_basis("350 000 ₽ на руки") == "net"
    assert detect_tax_basis("до 500 000 до вычета налогов") == "gross"
    assert detect_tax_basis("gross 400k") == "gross"
    # Молчание ≠ gross: иначе любая вилка без подписи теряла бы 13%.
    assert detect_tax_basis("от 300 000 ₽") is None
    assert detect_tax_basis("") is None
    # Обе пометки сразу («оклад до вычета, на руки ~») — net выигрывает, как в parse_net_range.
    assert detect_tax_basis("до вычета 500 000, на руки 435 000") == "net"
