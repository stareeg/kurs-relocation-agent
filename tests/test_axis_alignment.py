"""Этап 7 §7.2-7.3: разделяющая сила осей score_breakdown по решениям владельца."""

from __future__ import annotations

from core.domains.opportunities.axis_alignment import (
    _AXES,
    build_axis_alignment_report_from_rows,
    suggest_weight_adjustment,
)
from core.domains.opportunities.jobs import Job
from core.kernel.schemas.funnel import FunnelStatus


def _breakdown(**axis_points: int) -> dict[str, int]:
    base = dict.fromkeys(_AXES, 10)
    base.update(axis_points)
    return base


def _job(
    job_id: int,
    *,
    status: str = FunnelStatus.VIEWED.value,
    skipped: bool = False,
    overall_score: int = 50,
    gate: str | None = None,
    **axis_points: int,
) -> Job:
    score: dict[str, object] = {"score_breakdown": _breakdown(**axis_points)}
    if gate:
        score["gate_triggered"] = gate
    return Job(
        id=job_id,
        vacancy_id=str(job_id),
        vacancy_text="x" * 40,
        title=f"Job {job_id}",
        company="ACME",
        status=status,
        overall_score=overall_score,
        score=score,
        skipped=skipped,
    )


def test_stub_jobs_without_score_breakdown_are_excluded():
    stub = Job(id=1, vacancy_id="1", vacancy_text="", status="Просмотр", overall_score=99, score={})
    report = build_axis_alignment_report_from_rows([stub], [])
    assert report.n_responded == 0
    assert report.n_not_responded == 0


def test_responded_excludes_only_viewed_status_including_rejected():
    responded = [
        _job(i, status=FunnelStatus.APPLIED.value, role_content=20) for i in range(1, 11)
    ] + [_job(11, status=FunnelStatus.REJECTED.value, role_content=20)]
    silent = [_job(100 + i, status=FunnelStatus.VIEWED.value, role_content=5) for i in range(11)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    assert report.n_responded == 11
    assert report.n_not_responded == 11
    assert not report.insufficient_data


def test_skipped_jobs_are_excluded_from_not_responded_bucket():
    responded = [_job(i, status=FunnelStatus.APPLIED.value) for i in range(1, 11)]
    silent = [_job(100 + i) for i in range(10)]
    skipped_with_reason = [_job(200 + i, skipped=True) for i in range(10)]
    report = build_axis_alignment_report_from_rows(responded + silent + skipped_with_reason, [])
    # Skipped-строки не попадают ни в откликнулся, ни в «молчание».
    assert report.n_responded == 10
    assert report.n_not_responded == 10


def test_insufficient_data_below_minimum_bucket_size():
    responded = [_job(i, status=FunnelStatus.APPLIED.value) for i in range(1, 4)]
    silent = [_job(100 + i) for i in range(3)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    assert report.insufficient_data
    assert report.axes == []


def test_axis_delta_and_inversion_flag():
    responded = [
        _job(i, status=FunnelStatus.APPLIED.value, role_content=90, salary=16)
        for i in range(1, 11)
    ]
    silent = [_job(100 + i, role_content=40, salary=17) for i in range(10)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    by_axis = {a.axis: a for a in report.axes}

    role_content = by_axis["role_content"]
    assert role_content.avg_responded == 90
    assert role_content.avg_not_responded == 40
    assert role_content.delta == 50
    assert role_content.inverted is False

    salary = by_axis["salary"]
    assert salary.delta == -1
    assert salary.inverted is True


def test_high_score_no_response_excludes_responded_and_skipped():
    strong_silent = _job(1, overall_score=92, role_content=10)
    strong_responded = _job(2, status=FunnelStatus.APPLIED.value, overall_score=95, role_content=10)
    strong_skipped = _job(3, skipped=True, overall_score=90, role_content=10)
    weak_silent = _job(4, overall_score=40, role_content=10)
    filler_responded = [_job(10 + i, status=FunnelStatus.APPLIED.value) for i in range(9)]
    filler_silent = [_job(20 + i) for i in range(9)]

    jobs = [
        strong_silent,
        strong_responded,
        strong_skipped,
        weak_silent,
        *filler_responded,
        *filler_silent,
    ]
    report = build_axis_alignment_report_from_rows(jobs, [])
    ids = [d.job_id for d in report.high_score_no_response]
    assert ids == [1]


def test_low_score_responded_includes_gate_and_excludes_silent():
    weak_responded = _job(
        1, status=FunnelStatus.APPLIED.value, overall_score=30, gate="формат-гейт", role_content=10
    )
    strong_responded = _job(2, status=FunnelStatus.APPLIED.value, overall_score=80, role_content=10)
    weak_silent = _job(3, overall_score=20, role_content=10)
    filler_responded = [
        _job(10 + i, status=FunnelStatus.APPLIED.value, overall_score=70) for i in range(8)
    ]
    filler_silent = [_job(20 + i, overall_score=70) for i in range(10)]

    jobs = [weak_responded, strong_responded, weak_silent, *filler_responded, *filler_silent]
    report = build_axis_alignment_report_from_rows(jobs, [])
    assert len(report.low_score_responded) == 1
    d = report.low_score_responded[0]
    assert d.job_id == 1
    assert d.gate_triggered == "формат-гейт"


def test_skip_reason_counts_canonicalized():
    report = build_axis_alignment_report_from_rows(
        [], ["Сомнительная компания", "Риск выгорания", "Низкая зарплата"]
    )
    counts = dict(report.skip_reason_counts)
    assert counts["Избегать компанию"] == 1
    assert counts["Не та роль (IC vs рук)"] == 1
    assert counts["Низкая зарплата"] == 1
    assert report.n_skipped == 3


def test_suggest_weight_adjustment_none_when_insufficient_data():
    responded = [_job(i, status=FunnelStatus.APPLIED.value) for i in range(1, 4)]
    silent = [_job(100 + i) for i in range(3)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    assert suggest_weight_adjustment(report, {"salary": 20}) is None


def test_suggest_weight_adjustment_none_when_no_meaningful_inversion():
    responded = [_job(i, status=FunnelStatus.APPLIED.value, salary=15) for i in range(1, 11)]
    silent = [_job(100 + i, salary=15) for i in range(10)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    assert suggest_weight_adjustment(report, {"salary": 20}) is None


def test_suggest_weight_adjustment_flags_worst_inverted_axis():
    responded = [_job(i, status=FunnelStatus.APPLIED.value, salary=16) for i in range(1, 11)]
    silent = [_job(100 + i, salary=17) for i in range(10)]
    report = build_axis_alignment_report_from_rows(responded + silent, [])
    suggestion = suggest_weight_adjustment(report, {"salary": 20})
    assert suggestion is not None
    assert suggestion.axis == "salary"
    assert suggestion.current_weight == 20
    assert suggestion.suggested_weight < 20
