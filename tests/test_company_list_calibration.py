"""FR2-43: калибровка из target/avoid + приоритет ручных company_adjustments."""

from __future__ import annotations

from core.domains.opportunities.rules import (
    TARGET_COMPANY_DELTA,
    CandidateFormatPrefs,
    CompanyAdjustmentRule,
    apply_calibration,
    compute_adjustments,
    rules_from_search_lists,
)

# Изоляция от resume_data владельца: формат не вмешивается в тесты списков компаний.
_REMOTE_PREFS = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import compute_score_breakdown


def _make_score(*, overall_score: int = 80) -> ScoreResult:
    return ScoreResult(
        overall_score=overall_score,
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


def test_rules_from_search_lists_canonicalizes_aliases():
    rules = rules_from_search_lists(["ПАО Сбербанк", "Yandex"], ["VK"])
    by_canon = {r.company_canonical: r for r in rules}
    assert set(by_canon) == {"Сбербанк", "Яндекс", "VK"}
    assert by_canon["Сбербанк"].delta == TARGET_COMPANY_DELTA
    assert by_canon["Сбербанк"].gate is False
    # Avoid — дилбрейкер-флаг, а не множитель балла (Этап 1 §1.4).
    assert by_canon["VK"].gate is True
    assert by_canon["VK"].delta == 0


def test_canonical_match_target_bonus_on_pao_sberbank():
    """Лайкнули «Сбербанк» — матчится «ПАО Сбербанк» из вакансии."""
    list_rules = rules_from_search_lists(["Сбербанк"], [])
    score = _make_score(overall_score=70)
    # Ручных правил нет (пустой список, не None — иначе подтянется хардкод-дефолт со Сбером).
    adj = compute_adjustments(
        score,
        "текст вакансии без упоминания банка",
        company_adjustments=[],
        company="ПАО Сбербанк",
        list_rules=list_rules,
        format_prefs=_REMOTE_PREFS,
    )
    assert any(a.delta == TARGET_COMPANY_DELTA and "Сбербанк" in a.reason for a in adj)

    result = apply_calibration(
        score,
        "полная удалёнка, senior позиция",
        company_adjustments=[],
        company="ПАО Сбербанк",
        list_rules=list_rules,
        format_prefs=_REMOTE_PREFS,
        role_kind="unknown",
    )
    # База — детерминированный breakdown по весам, не сырой overall_score из фикстуры (apply_calibration
    # игнорирует его нарочно, см. core/domains/opportunities/rules.py); поверх breakdown ложится только
    # TARGET_COMPANY_DELTA от совпадения по target-списку, с капом в 100.
    # role_kind="unknown" — изоляция от resume_data владельца (см. _REMOTE_PREFS выше): без него
    # apply_calibration тянет реальный SearchProfile.role_kind и шкала «Управление» уезжает от
    # дефолта, которым посчитан expected.
    expected = min(
        100,
        sum(compute_score_breakdown(score, role_kind="unknown").values()) + TARGET_COMPANY_DELTA,
    )
    assert result.overall_score == expected
    assert result.gate_triggered is None
    assert result.recommendation != "skip"
    # B-05: причина калибровки не теряется в логах, а лежит в jsonb для UI-остатка.
    assert any(
        a.delta == TARGET_COMPANY_DELTA and "Сбербанк" in a.reason for a in result.adjustments
    )


def test_avoid_list_forces_skip_gate():
    list_rules = rules_from_search_lists([], ["АутсорсКомпания"])
    score = _make_score(overall_score=90)
    result = apply_calibration(
        score,
        "полная удалёнка, senior позиция без офиса",
        company_adjustments=[],
        company="АутсорсКомпания",
        list_rules=list_rules,
        format_prefs=_REMOTE_PREFS,
        role_kind="unknown",
    )
    assert result.gate_triggered is not None
    assert "избегать" in (result.gate_triggered or "")
    assert result.recommendation == "skip"


def test_manual_rule_wins_over_target_list_for_same_company():
    """Ручной штраф по «сбербанк» побеждает лайк «Сбербанк» из списка."""
    list_rules = rules_from_search_lists(["Сбербанк"], [])
    manual = [
        CompanyAdjustmentRule(
            match=("сбербанк", "сбер "),
            delta=-7,
            reason="экосистема Сбер (риск выгорания)",
        )
    ]
    score = _make_score(overall_score=70)
    text = "Компания: ПАО Сбербанк. Работа в экосистеме сбербанка."
    adj = compute_adjustments(
        score,
        text,
        company_adjustments=manual,
        company="ПАО Сбербанк",
        list_rules=list_rules,
        format_prefs=_REMOTE_PREFS,
    )
    deltas = [(a.delta, a.reason) for a in adj]
    assert (-7, "экосистема Сбер (риск выгорания)") in deltas
    assert not any(d == TARGET_COMPANY_DELTA for d, _ in deltas)
