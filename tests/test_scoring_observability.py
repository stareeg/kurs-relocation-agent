"""Этап 9 (plans/scoring_precision_2026_08_17.md): наблюдаемость скоринга.

§9.1 — `event(...)` в `scorer.score_vacancy` несёт `weights_version`, сумму breakdown до
мягких калибровок, гейт/adjustments и обе половины «Содержания роли» (llm + overlap), не
только `overall_score`/`recommendation`.
§9.2 — WARNING про расхождение JD/вердикта формата и событие «гейты вакансии» несут
`vacancy_id`: раньше сигнал сидел в базе (21 строка на проде), но не появлялся в логах ни
разу, и без `vacancy_id` «почему у ЭТОЙ вакансии skip» всё равно требовал перескора.
§9.3 — раз в сутки в лог уходит доля вакансий с заполненными `total_responses`/
`letter_required`/`published_at`/`salary.source=explicit` (D11: было 0 из 342 на проде).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from core.domains.opportunities import coverage_metrics
from core.domains.opportunities.jobs import input_coverage_stats
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.rules import (
    CandidateFormatPrefs,
    compute_adjustments,
    detect_gates,
)
from core.domains.opportunities.scorer import score_vacancy
from tests.fakes import FakeLlm

_OFFICE_ONLY_PREFS = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
_OFFICE_JD = "формат работы: на месте работодателя\nсеньор в офис 5/5"
_NEUTRAL_JD = "формат работы: удалённо\nсеньор, без ограничений"


def _score(*, format_level: str = "ok", grade_level: str = "match") -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level=format_level, reasoning="r"),
        grade_match=GradeMatch(level=grade_level, reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


# --- §9.2: vacancy_id в логах гейтов/расхождений ------------------------------------------


def test_format_conflict_warning_carries_vacancy_id(caplog: pytest.LogCaptureFixture) -> None:
    """Регекс кричит «офис», модель говорит «формат подходит» → WARNING с `vacancy_id`."""
    with caplog.at_level(logging.WARNING, logger="core.domains.opportunities.rules"):
        compute_adjustments(
            _score(format_level="ok"),
            _OFFICE_JD,
            format_prefs=_OFFICE_ONLY_PREFS,
            vacancy_id="135900007",
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "расхождение JD/модели должно оставить WARNING"
    assert warnings[0].vacancy_id == "135900007"


def test_format_conflict_warning_empty_vacancy_id_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Без `vacancy_id` (старые вызывающие) поле остаётся пустой строкой, не падает."""
    with caplog.at_level(logging.WARNING, logger="core.domains.opportunities.rules"):
        compute_adjustments(_score(format_level="ok"), _OFFICE_JD, format_prefs=_OFFICE_ONLY_PREFS)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings[0].vacancy_id == ""


def test_gates_event_carries_vacancy_id(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="core.domains.opportunities.rules"):
        badge = detect_gates(
            _score(grade_level="far_below"),
            _NEUTRAL_JD,
            format_prefs=_OFFICE_ONLY_PREFS,
            vacancy_id="42",
        )

    assert badge == "Балл срезан: грейд-гейт"
    gate_records = [r for r in caplog.records if getattr(r, "gates", None)]
    assert gate_records and gate_records[0].vacancy_id == "42"


# --- §9.1: диагностические поля в "скоринг готов" ------------------------------------------


@pytest.fixture(autouse=True)
def _patch_account_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Резюме/ручные company-правила без Postgres (тот же приём, что test_scorer_determinism.py)."""
    from pathlib import Path

    from core.domains.profile.model import ResumeData

    fixture = Path(__file__).resolve().parent / "fixtures" / "resume_smoke_frontend.json"
    resume = ResumeData.model_validate_json(fixture.read_text(encoding="utf-8"))

    async def fake_resume(_account_id: int, db: object | None = None) -> ResumeData:
        return resume

    async def fake_manual_rules(_account_id: int) -> list:
        return []

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_resume
    )
    monkeypatch.setattr(
        "core.domains.opportunities.scorer.load_manual_company_adjustments", fake_manual_rules
    )


async def test_score_vacancy_ready_event_carries_diagnostic_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canned = _score(format_level="ok")
    llm = FakeLlm(result=canned)

    with caplog.at_level(logging.INFO, logger="core.domains.opportunities.scorer"):
        result = await score_vacancy(
            "Middle Python-разработчик, формат работы: удалённо, зарплата 300 000 ₽ на руки",
            account_id=1,
            salary_use_llm=False,
            salary_text="300 000 ₽ на руки",
            vacancy_id="777",
            llm=llm,
        )

    ready = [r for r in caplog.records if "скоринг готов" in str(r.msg)]
    assert ready, "не найдено событие «скоринг готов»"
    record = ready[0]

    assert record.vacancy_id == "777"
    assert record.weights_version == result.weights_version
    assert record.weights_version  # не пусто — версия рубрики всегда проставлена
    assert record.breakdown_sum == sum(result.score_breakdown.values())
    assert record.gate_triggered == result.gate_triggered
    assert record.adjustments == [f"{a.delta:+d} {a.reason}" for a in result.adjustments]
    # role_content_llm_score — сырой вердикт модели (не колебается от breakdown/веса),
    # role_content_points — итог оси после веса/подмешивания оверлапа.
    assert record.role_content_llm_score == canned.role_content_match.score
    assert record.role_content_points == result.score_breakdown.get("role_content", -1)


# --- §9.3: суточная метрика покрытия входных данных -----------------------------------------


class _FakeDb:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        assert "from jobs" in query.lower()
        assert args == (1,)
        return self._row


async def test_input_coverage_stats_maps_row_to_dict() -> None:
    db = _FakeDb(
        {
            "total": 10,
            "total_responses_filled": 4,
            "letter_required_true": 1,
            "published_at_filled": 6,
            "salary_explicit": 2,
        }
    )
    stats = await input_coverage_stats(account_id=1, db=db)
    assert stats == {
        "total": 10,
        "total_responses_filled": 4,
        "letter_required_true": 1,
        "published_at_filled": 6,
        "salary_explicit": 2,
    }


async def test_log_input_coverage_logs_percentages(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fake_owner_id(**_kw: Any) -> int:
        return 1

    async def fake_stats(*, account_id: int, db: Any = None) -> dict[str, int]:
        assert account_id == 1
        return {
            "total": 4,
            "total_responses_filled": 1,
            "letter_required_true": 0,
            "published_at_filled": 2,
            "salary_explicit": 4,
        }

    monkeypatch.setattr(
        "core.platform.repo.accounts.resolve_default_account_id", fake_owner_id
    )
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.input_coverage_stats", fake_stats
    )

    with caplog.at_level(logging.INFO, logger="core.domains.opportunities.coverage_metrics"):
        await coverage_metrics._log_input_coverage({})  # noqa: SLF001

    records = [r for r in caplog.records if getattr(r, "event", None) == "ЗАДАЧА"]
    assert records, "метрика покрытия должна оставить событие"
    record = records[0]
    assert record.total == 4
    assert record.total_responses_filled == 1
    assert record.published_at_filled == 2
    assert record.salary_explicit == 4


async def test_log_input_coverage_skips_without_owner_account(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def no_owner(**_kw: Any) -> None:
        return None

    async def unexpected_stats(**_kw: Any) -> dict[str, int]:
        raise AssertionError("без владельца метрика не должна запрашивать jobs")

    monkeypatch.setattr("core.platform.repo.accounts.resolve_default_account_id", no_owner)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.input_coverage_stats", unexpected_stats
    )

    with caplog.at_level(logging.INFO, logger="core.domains.opportunities.coverage_metrics"):
        await coverage_metrics._log_input_coverage({})  # noqa: SLF001


def test_pct_handles_zero_total() -> None:
    assert coverage_metrics._pct(0, 0) == 0.0  # noqa: SLF001
    assert coverage_metrics._pct(1, 4) == 25.0  # noqa: SLF001
