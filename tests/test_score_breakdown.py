"""EXT-S1/EXT-S2 (plans/extension_v2.md): численный вклад критериев + гейты overall_score.

`compute_score_breakdown` — чистая детерминированная функция уровень→баллы (не LLM-генерируемая,
см. docstring модуля). `detect_gates` — человекочитаемый бейдж ровно когда сработал дилбрейкер,
синхронно с гейтами из prompts/opportunities/instructions.md §«Жёсткие гейты».
`apply_calibration` форсит `recommendation=skip` по этому бейджу.

Этап 1 (plans/scoring_precision_2026_08_17.md §1.4): гейт больше не множитель — балл при гейте
остаётся взвешенной суммой, флаг и число разведены.
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.rules import (
    CandidateFormatPrefs,
    apply_calibration,
    detect_gates,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import (
    COMPANY_WEIGHT,
    GRADE_WEIGHT,
    MANAGEMENT_WEIGHT,
    RATE_CORPUS_MIN,
    ROLE_CONTENT_WEIGHT,
    SALARY_NEUTRAL_FRACTION,
    SALARY_WEIGHT,
    WORK_FORMAT_WEIGHT,
    SalaryPrefs,
    compat_fraction,
    compute_score_breakdown,
    flexibility_fraction,
    rate_fraction,
    salary_fraction,
    salary_prefs_from_profile,
)


def _make_score(
    *,
    salary_meets_min: bool = True,
    salary: SalaryInfo | None = None,
    format_level: str = "ok",
    grade_level: str = "match",
    off_profile_kind: str = "",
    role_score: int = 80,
    burnout_level: str = "low",
    overall_score: int = 80,
) -> ScoreResult:
    return ScoreResult(
        overall_score=overall_score,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level=format_level, reasoning="r"),
        grade_match=GradeMatch(
            level=grade_level, reasoning="r", off_profile_kind=off_profile_kind
        ),
        salary=salary
        or SalaryInfo(meets_min=salary_meets_min, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=role_score, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level=burnout_level, reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


def test_breakdown_weights_sum_to_100():
    assert (
        SALARY_WEIGHT
        + WORK_FORMAT_WEIGHT
        + GRADE_WEIGHT
        + ROLE_CONTENT_WEIGHT
        + MANAGEMENT_WEIGHT
        + COMPANY_WEIGHT
        == 100
    )


def test_breakdown_all_plusses_hits_max_per_criterion():
    score = _make_score(
        salary_meets_min=True, format_level="ideal", grade_level="match", role_score=100,
        burnout_level="low",
    )
    # hands_on + low = полный вес «Управление»; без role_kind дефолт unknown → 0.8.
    breakdown = compute_score_breakdown(score, role_kind="hands_on")
    assert breakdown == {
        "salary": SALARY_WEIGHT,
        "work_format": WORK_FORMAT_WEIGHT,
        "grade_match": GRADE_WEIGHT,
        "role_content": ROLE_CONTENT_WEIGHT,
        "management": MANAGEMENT_WEIGHT,
        "company": round(COMPANY_WEIGHT * 1.0),  # product → strong fraction
    }
    assert sum(breakdown.values()) == 100


def test_breakdown_management_scale_flips_with_role_kind():
    """Один ScoreResult (burnout=high): hands_on → 3, management → 15 при весе 15."""
    score = _make_score(burnout_level="high")
    hands = compute_score_breakdown(score, role_kind="hands_on")
    mgmt = compute_score_breakdown(score, role_kind="management")
    assert hands["management"] == round(MANAGEMENT_WEIGHT * 0.2)  # 3
    assert mgmt["management"] == MANAGEMENT_WEIGHT  # 15
    assert hands["management"] == 3
    assert mgmt["management"] == 15


def test_breakdown_management_mixed_scale_is_asymmetric():
    """Этап 3 (§5 плана): для mixed крайности больше не равны — 78% вакансий на проде получали
    одно и то же число из-за симметричной таблицы low == high."""
    low = compute_score_breakdown(_make_score(burnout_level="low"), role_kind="mixed")
    medium = compute_score_breakdown(_make_score(burnout_level="medium"), role_kind="mixed")
    high = compute_score_breakdown(_make_score(burnout_level="high"), role_kind="mixed")
    assert len({low["management"], medium["management"], high["management"]}) == 3
    assert medium["management"] == MANAGEMENT_WEIGHT
    # Совсем без управления — чуть хуже, чем чистый people-management, но лучше, чем крайний high.
    assert low["management"] > high["management"]


def test_breakdown_above_less_than_full_grade_weight():
    score = _make_score(grade_level="above")
    breakdown = compute_score_breakdown(score)
    assert breakdown["grade_match"] == round(GRADE_WEIGHT * 0.9)
    assert breakdown["grade_match"] < GRADE_WEIGHT


def test_breakdown_blocker_format_zeroes_out_format_points():
    score = _make_score(format_level="blocker")
    breakdown = compute_score_breakdown(score)
    assert breakdown["work_format"] == 0


def test_breakdown_role_content_scales_linearly_with_llm_subscore():
    score = _make_score(role_score=50)
    breakdown = compute_score_breakdown(score)
    assert breakdown["role_content"] == round(ROLE_CONTENT_WEIGHT * 0.5)


def test_breakdown_off_profile_zeroes_out_grade_points():
    score = _make_score(grade_level="off_profile")
    breakdown = compute_score_breakdown(score)
    assert breakdown["grade_match"] == 0


def test_breakdown_role_shift_costs_less_than_other_profession_for_mixed():
    """Этап 1 §1.3: «AI product manager» для mixed-кандидата — сдвиг роли, а не чужая профессия."""
    shift = _make_score(grade_level="off_profile", off_profile_kind="role_shift")
    other = _make_score(grade_level="off_profile", off_profile_kind="other_profession")
    assert compute_score_breakdown(shift, role_kind="mixed")["grade_match"] == round(
        GRADE_WEIGHT * 0.8
    )
    assert compute_score_breakdown(other, role_kind="mixed")["grade_match"] == 0


def test_breakdown_role_shift_direction_comes_from_role_kind():
    """Цена сдвига — из role_kind резюме: hands_on теряет заметно, mixed/management мягко."""
    shift = _make_score(grade_level="off_profile", off_profile_kind="role_shift")
    hands = compute_score_breakdown(shift, role_kind="hands_on")["grade_match"]
    mixed = compute_score_breakdown(shift, role_kind="mixed")["grade_match"]
    mgmt = compute_score_breakdown(shift, role_kind="management")["grade_match"]
    assert hands < mixed
    assert mixed == mgmt
    assert hands > 0  # не гейт: ноль остаётся за other_profession


# format_prefs теперь обязателен (Этап 8 §8.5: файлового фолбэка на resume_data владельца
# у detect_gates/apply_calibration больше нет) — везде передаём явный срез.
_REMOTE_ONLY = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
# Пустой schedule — гейты/минусы формата молчат (кандидат ещё не заполнил допустимые форматы).
_EMPTY_SCHEDULE = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=False,
    travel_is_dealbreaker=False,
)


def test_detect_gates_blocker_returns_format_gate_badge():
    text = "Обязательно присутствие в офисе, только офис 5/5, никаких исключений"
    score = _make_score(format_level="blocker", overall_score=90)
    assert detect_gates(score, text, format_prefs=_REMOTE_ONLY) == "Балл срезан: формат-гейт"


def test_detect_gates_far_below_grade_returns_grade_gate_badge():
    score = _make_score(grade_level="far_below", overall_score=90)
    badge = detect_gates(
        score, "обычный текст вакансии без гейтов формата", format_prefs=_EMPTY_SCHEDULE
    )
    assert badge == "Балл срезан: грейд-гейт"


def test_detect_gates_no_gate_returns_none_badge():
    score = _make_score(overall_score=80)
    assert (
        detect_gates(
            score,
            "полная удалёнка, senior позиция, без ограничений",
            format_prefs=_EMPTY_SCHEDULE,
        )
        is None
    )


def test_detect_gates_role_shift_off_profile_is_not_a_gate():
    """§1.3: сдвиг IC↔менеджмент внутри своей профессии — не дилбрейкер."""
    shift = _make_score(grade_level="off_profile", off_profile_kind="role_shift")
    other = _make_score(grade_level="off_profile", off_profile_kind="other_profession")
    assert detect_gates(shift, "полная удалёнка, senior позиция", format_prefs=_EMPTY_SCHEDULE) is None
    assert (
        detect_gates(other, "полная удалёнка, senior позиция", format_prefs=_EMPTY_SCHEDULE)
        == "Балл срезан: грейд-гейт"
    )


def test_gate_no_longer_cuts_the_score():
    """§1.4: балл при гейте — ровно взвешенная сумма; отдельно живёт только флаг."""
    text = "Обязательно присутствие в офисе, только офис 5/5, никаких исключений"
    score = _make_score(format_level="blocker", overall_score=90)
    result = apply_calibration(score, text, format_prefs=_REMOTE_ONLY, role_kind="hands_on")

    assert result.gate_triggered == "Балл срезан: формат-гейт"
    assert result.recommendation == "skip"
    assert result.adjustments == []  # мягких дельт тут нет — весь остаток был бы капом
    assert result.overall_score == sum(
        compute_score_breakdown(score, role_kind="hands_on").values()
    )
    assert result.overall_score == sum(result.score_breakdown.values())


def test_apply_calibration_gate_forces_skip_even_above_skip_threshold():
    """Число остаётся высоким («по существу подходит»), а решение — skip по флагу гейта."""
    score = _make_score(grade_level="far_below", overall_score=95, role_score=95)
    result = apply_calibration(
        score,
        "обычный текст вакансии без гейтов формата",
        format_prefs=_EMPTY_SCHEDULE,
        role_kind="unknown",
    )

    assert result.overall_score > 42
    assert result.gate_triggered == "Балл срезан: грейд-гейт"
    assert result.recommendation == "skip"


def test_apply_calibration_no_gate_keeps_score_based_recommendation():
    score = _make_score(overall_score=80)
    result = apply_calibration(
        score,
        "полная удалёнка, senior позиция, без ограничений",
        format_prefs=_EMPTY_SCHEDULE,
        role_kind="unknown",
    )

    assert result.gate_triggered is None
    assert result.recommendation == "strong_apply"


# --- Этап 2 (§2.1–2.2): зарплата — рампа по числам вилки вместо одного бита ---

# Пороги кандидата: «желаемая» 400к, «комфортная» 500к, обе — на руки.
_SALARY_PREFS = SalaryPrefs(floor=400_000, comfortable=500_000, basis="net")


def _salary(
    *,
    lo: int | None,
    hi: int | None = None,
    source: str = "explicit",
    confidence: str = "high",
    meets_min: bool = True,
    value: str = "вилка на руки",
) -> SalaryInfo:
    return SalaryInfo(
        meets_min=meets_min,
        value_or_range=value,
        estimated_min=lo,
        estimated_max=hi if hi is not None else lo,
        note="",
        confidence=confidence,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "mid,expected",
    [
        (600_000, 1.0),  # выше «комфортной»
        (500_000, 1.0),  # ровно «комфортная»
        (450_000, 0.9),  # середина между порогом и комфортом
        (400_000, 0.8),  # ровно порог
        (370_000, 0.65),  # чуть ниже порога
        (340_000, 0.5),  # нижняя граница «чуть ниже» (0.85 × порога)
        (270_000, 0.325),  # заметно ниже
        (200_000, 0.15),  # половина порога — пол
        (100_000, 0.15),  # ниже пола не проваливаемся
    ],
)
def test_salary_ramp_table(mid, expected):
    """§2.1: доля веса непрерывна по положению вилки, а не 1 бит на 20 баллов."""
    frac = salary_fraction(_salary(lo=mid), _SALARY_PREFS)
    assert frac == pytest.approx(expected, abs=1e-6)


def test_salary_ramp_is_monotonic_over_the_whole_grid():
    """Выше вилка → не меньше баллов. Свойство, а не отдельные точки."""
    fractions = [
        salary_fraction(_salary(lo=mid), _SALARY_PREFS) for mid in range(50_000, 900_001, 10_000)
    ]
    assert fractions == sorted(fractions)
    assert fractions[0] < fractions[-1]  # шкала действительно работает, а не константа


def test_salary_axis_has_resolution_not_two_values():
    """Метрика плана: различных значений баллов зарплаты было 2, цель — ≥ 8."""
    points = {
        compute_score_breakdown(_make_score(salary=_salary(lo=mid)), salary_prefs=_SALARY_PREFS)[
            "salary"
        ]
        for mid in range(150_000, 700_001, 10_000)
    }
    assert len(points) >= 8


def test_salary_no_numbers_is_neutral_regardless_of_model_guess():
    """§2.1: чисел нет (`source=none`) → 0.55 нейтрально, догадка модели не решает."""
    optimistic = _salary(lo=None, source="none", confidence="low", meets_min=True)
    pessimistic = _salary(lo=None, source="none", confidence="low", meets_min=False)
    assert salary_fraction(optimistic, _SALARY_PREFS) == pytest.approx(SALARY_NEUTRAL_FRACTION)
    assert salary_fraction(pessimistic, _SALARY_PREFS) == pytest.approx(SALARY_NEUTRAL_FRACTION)


def test_salary_trust_pulls_estimates_toward_neutral():
    """§2.2: та же вилка ниже порога давит тем слабее, чем меньше доверия к источнику."""
    low_range = dict(lo=300_000)
    named = salary_fraction(_salary(**low_range), _SALARY_PREFS)
    corpus_high = salary_fraction(_salary(**low_range, source="corpus"), _SALARY_PREFS)
    corpus_low = salary_fraction(
        _salary(**low_range, source="corpus", confidence="low"), _SALARY_PREFS
    )
    assert named < corpus_high < corpus_low < SALARY_NEUTRAL_FRACTION

    high_range = dict(lo=600_000)
    named_hi = salary_fraction(_salary(**high_range), _SALARY_PREFS)
    corpus_hi_low = salary_fraction(
        _salary(**high_range, source="corpus", confidence="low"), _SALARY_PREFS
    )
    assert named_hi > corpus_hi_low > SALARY_NEUTRAL_FRACTION


def test_llm_estimate_is_compared_in_net_not_gross():
    """§2.3: оценку LLM просят в gross — с порогом «на руки» её сравнивают после ×0.87."""
    numbers = dict(lo=480_000, hi=520_000)
    as_named = salary_fraction(_salary(**numbers, value="500 000 ₽ на руки"), _SALARY_PREFS)
    as_estimate = salary_fraction(
        _salary(**numbers, source="llm", confidence="high"), _SALARY_PREFS
    )
    assert as_named == 1.0
    assert as_estimate < as_named


def test_explicit_range_reads_its_own_scale_from_the_text():
    """«до вычета» в тексте вилки → сравниваем в net; без пометки — как есть."""
    gross = salary_fraction(
        _salary(lo=420_000, value="420 000 ₽ до вычета налогов"), _SALARY_PREFS
    )
    silent = salary_fraction(_salary(lo=420_000, value="420 000 ₽"), _SALARY_PREFS)
    assert gross < silent


def test_salary_without_prefs_falls_back_to_meets_min_bit():
    """Порога в резюме нет — сравнивать не с чем, остаётся булев вердикт модели."""
    yes = compute_score_breakdown(_make_score(salary_meets_min=True))["salary"]
    no = compute_score_breakdown(_make_score(salary_meets_min=False))["salary"]
    assert yes == SALARY_WEIGHT
    assert no == round(SALARY_WEIGHT * 0.45)


def test_salary_prefs_without_comfortable_use_min_times_1_3():
    """`salary_comfortable` пуст → верх рампы = min × 1.3 (конвенция salary_anchor_base)."""
    from core.domains.profile.profile import SearchProfile

    prefs = salary_prefs_from_profile(SearchProfile(salary_min=400_000, salary_comfortable=0))
    assert prefs == SalaryPrefs(floor=400_000, comfortable=520_000, basis="net")
    assert salary_fraction(_salary(lo=520_000), prefs) == 1.0
    assert salary_fraction(_salary(lo=460_000), prefs) == pytest.approx(0.9)
    assert salary_prefs_from_profile(SearchProfile(salary_min=0)).is_set is False


# --- Этап 4 (plans/scoring_precision_2026_08_17.md §4.1/§4.3): role_content — самая тяжёлая
# ось + смешивание с детерминированным оверлапом навыков ---


def test_role_content_is_the_heaviest_static_weight():
    """§1.6 плана: единственная ось с измеренной предиктивной силой на решениях владельца."""
    other_weights = (SALARY_WEIGHT, WORK_FORMAT_WEIGHT, GRADE_WEIGHT, MANAGEMENT_WEIGHT, COMPANY_WEIGHT)
    assert ROLE_CONTENT_WEIGHT > max(other_weights)


def test_breakdown_role_content_blends_deterministic_skill_overlap():
    """`skill_overlap` передан → балл смешивает LLM-оценку и оверлап, а не только LLM."""
    score = _make_score(role_score=80)
    pure_llm = compute_score_breakdown(score)["role_content"]
    blended_up = compute_score_breakdown(score, skill_overlap=1.0)["role_content"]
    blended_down = compute_score_breakdown(score, skill_overlap=0.0)["role_content"]
    assert blended_up > pure_llm > blended_down


def test_breakdown_role_content_neutral_without_requirements_data():
    """`skill_overlap=None` (требований по вакансии ещё нет) — тот же балл, что без смеси."""
    score = _make_score(role_score=80)
    assert compute_score_breakdown(score)["role_content"] == compute_score_breakdown(
        score, skill_overlap=None
    )["role_content"]


def test_flexibility_none_terms_is_neutral():
    assert flexibility_fraction(None) == pytest.approx(SALARY_NEUTRAL_FRACTION)


def test_compat_none_terms_is_neutral():
    from core.domains.profile.international import InternationalReadiness

    assert compat_fraction(None, InternationalReadiness()) == pytest.approx(SALARY_NEUTRAL_FRACTION)


def test_rate_fraction_few_observations_is_neutral():
    from core.domains.opportunities.models import VacancyWorkTerms

    terms = VacancyWorkTerms(currency="USD", rate_period="hour", rate_min=80, rate_max=100)
    assert rate_fraction(terms, floor=90, n_obs=RATE_CORPUS_MIN - 1) == pytest.approx(
        SALARY_NEUTRAL_FRACTION
    )
    assert rate_fraction(None, floor=90, n_obs=20) == pytest.approx(SALARY_NEUTRAL_FRACTION)
