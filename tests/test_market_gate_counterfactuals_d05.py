"""D-05: контрфакты на жёстких гейтах — `compute_gate_counterfactuals`, чистая функция."""

from __future__ import annotations

from core.domains.market.pulse import compute_gate_counterfactuals


def _row(estimated_min: int | None, verdict: str | None, *, score: int = 70) -> tuple:
    salary = {"meets_min": True, "estimated_min": estimated_min, "estimated_max": estimated_min}
    remote = {"verdict": verdict} if verdict else {}
    return ({"overall_score": score}, salary, remote)


def test_no_rows_gives_unavailable():
    result = compute_gate_counterfactuals([], salary_min=374_000)
    assert result.available is False
    assert result.measured == 0


def test_unscored_rows_excluded_from_measured():
    # нет overall_score — не заскорено
    rows = [({}, {"estimated_min": 400_000}, {"verdict": "real"})]
    result = compute_gate_counterfactuals(rows, salary_min=374_000)
    assert result.available is False


def test_salary_passes_now_matches_direct_threshold_query():
    # При пороге 374к проходят 400к и 380к, не проходит 350к — то же самое, что прямой запрос
    # к базе по estimated_min >= порог (готово-критерий плана D-05: число сходится с прямым
    # запросом, при любом пороге, не только текущем).
    rows = [
        _row(400_000, "real"),
        _row(380_000, "real"),
        _row(350_000, "real"),
    ]
    result_374k = compute_gate_counterfactuals(rows, salary_min=374_000)
    assert result_374k.salary.threshold == 374_000
    assert result_374k.salary.passes_now == 2

    result_350k = compute_gate_counterfactuals(rows, salary_min=350_000)
    direct_at_350k = sum(1 for _, salary, _ in rows if salary["estimated_min"] >= 350_000)
    assert result_350k.salary.passes_now == direct_at_350k == 3


def test_salary_counterfactual_steps_are_minus_10_and_minus_20_percent():
    rows = [
        _row(400_000, "real"),  # проходит всегда
        _row(340_000, "real"),  # проходит только при -10% (336_600) и мягче
        _row(300_000, "real"),  # проходит только при -20% (299_200) и мягче
        _row(250_000, "real"),  # не проходит нигде
    ]
    result = compute_gate_counterfactuals(rows, salary_min=374_000)
    assert result.salary.passes_now == 1
    minus10, minus20 = result.salary.steps
    assert minus10.label == "−10%"
    assert minus10.passes == 2
    assert minus10.delta == 1
    assert minus20.label == "−20%"
    assert minus20.passes == 3
    assert minus20.delta == 2


def test_salary_steps_empty_and_passes_now_is_all_measured_when_no_threshold():
    rows = [_row(400_000, "real"), _row(100_000, "real")]
    result = compute_gate_counterfactuals(rows, salary_min=0)
    assert result.salary.steps == []
    assert result.salary.passes_now == 2  # без порога планка не гейтит никого


def test_rows_without_readable_salary_are_not_counted_in_salary_passes():
    rows = [_row(400_000, "real"), _row(None, "real")]
    result = compute_gate_counterfactuals(rows, salary_min=374_000)
    assert result.measured == 2
    assert result.salary.passes_now == 1


def test_format_counterfactual_relaxes_from_real_to_conditional_to_any():
    rows = [
        _row(400_000, "real"),
        _row(400_000, "real"),
        _row(400_000, "conditional"),
        _row(400_000, "unlikely"),
    ]
    result = compute_gate_counterfactuals(rows, salary_min=0)
    assert result.format.passes_now == 2
    with_conditional, without_gate = result.format.steps
    assert with_conditional.label == "+ условная удалёнка"
    assert with_conditional.passes == 3
    assert with_conditional.delta == 1
    assert without_gate.label == "без ограничения формата"
    assert without_gate.passes == 4
    assert without_gate.delta == 2


def test_format_rows_without_measured_verdict_excluded():
    rows = [_row(400_000, "real"), _row(400_000, None)]
    result = compute_gate_counterfactuals(rows, salary_min=0)
    assert result.measured == 2
    assert result.format.passes_now == 1
    assert result.format.steps[-1].passes == 1  # немерянный формат не считается «любым»
