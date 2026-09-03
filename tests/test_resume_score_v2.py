"""FR2-46 / шаг 25: балл резюме из доступных компонент; market_coverage может быть None."""

from __future__ import annotations

from core.domains.profile.gap import (
    GapConcept,
    ResumeGapReport,
    ResumeScoreBreakdown,
    assemble_score,
    compute_report,
    _score_market_coverage,
    _score_structure,
)
from core.domains.profile.model import (
    Contacts,
    DesiredPosition,
    Experience,
    Personal,
    ResumeData,
    SearchCriteria,
    to_markdown,
)


def _minimal_resume(**kwargs) -> ResumeData:
    base = ResumeData(
        personal=Personal(full_name="Иван Иванов"),
        contacts=Contacts(phone="+79991234567", email="a@b.ru"),
        position=DesiredPosition(title="Lead LLM Engineer", salary_min=450000),
        experience=[
            Experience(
                company="Сбер",
                position="Lead",
                start="2024-01",
                current=True,
                description="- Построил multi-agent RAG на LangGraph\n- Поднял faithfulness с 0.6 до 0.85",
            )
        ],
        education_level="Высшее",
        key_skills=["Python", "LLM", "RAG", "LangGraph", "PostgreSQL"],
        about="Веду LLM-платформу. " * 5,
    )
    return base.model_copy(update=kwargs) if kwargs else base


def _pm_resume() -> ResumeData:
    """Заполненный PM-профиль (не-IT сегмент) — cold start без корпуса."""
    return ResumeData(
        personal=Personal(full_name="Анна Тестова"),
        contacts=Contacts(phone="+79991234567", email="anna@example.ru"),
        position=DesiredPosition(
            title="Project Manager",
            salary_min=250000,
            salary_comfortable=320000,
            grade=["Middle", "Senior"],
            schedule=["Гибрид", "Удалённая работа"],
        ),
        search_criteria=SearchCriteria(
            niches=["Agile delivery", "Кросс-функциональные команды"],
            role_kind="Управляю людьми",
            market_segment="Медиа / Продакшн",
        ),
        experience=[
            Experience(
                company="Медиахолдинг",
                position="Project Manager",
                start="2021-01",
                current=True,
                description=(
                    "- Вёл кросс-функциональные команды 8-12 человек\n"
                    "- Сократил time-to-market фич с 12 до 6 недель"
                ),
            )
        ],
        education_level="Высшее",
        key_skills=[
            "Jira",
            "Scrum",
            "Stakeholder management",
            "Roadmap",
            "Risk management",
            "Бюджет",
            "Стейкхолдеры",
            "Сроки",
            "Agile",
            "Конфликты",
            "Статус-репорты",
            "Риски",
            "Планирование",
            "Фасилитация",
            "Delivery",
        ],
        about="Senior Project Manager с опытом delivery в продуктовых командах. " * 3,
    )


def test_assemble_score_is_mean_of_available() -> None:
    data = _minimal_resume()
    text = "Иван\n**Навыки:** Python, LLM, RAG, LangGraph, PostgreSQL"
    report = ResumeGapReport(
        available=False,
        corpus_size=0,
        tags_count=5,
        concepts_total=10,
        concepts_covered=3,
    )
    score = assemble_score(data, text, report, top_jobs_texts=[])
    parts = [score.structure, score.writing, score.role_fit]
    if score.market_coverage is not None:
        parts.append(score.market_coverage)
    assert score.total == round(sum(parts) / len(parts))
    dump = score.model_dump()
    assert {"total", "structure", "market_coverage", "writing", "role_fit"} <= set(dump)
    assert "ats" not in ResumeScoreBreakdown.model_fields
    assert "skills_fit" not in ResumeScoreBreakdown.model_fields


def test_structure_without_double_count_empty_is_low() -> None:
    empty = ResumeData()
    # У пустого каркаса все пункты красные (зарплата/markdown-шум больше не входят).
    assert _score_structure("", empty) == 0


def test_structure_filled_is_high() -> None:
    data = _minimal_resume()
    text = "plain text without tables"
    assert _score_structure(text, data) >= 80


def test_market_cold_start_is_none_not_zero() -> None:
    report = compute_report([], "Python LLM RAG", market_segment="")
    assert report.available is False
    assert _score_market_coverage(report, "Python LLM RAG", [], market_segment="") is None


def test_market_empty_dict_non_it_is_none() -> None:
    report = compute_report([], "управление проектами", market_segment="Медиа / Продакшн")
    assert _score_market_coverage(
        report, "управление проектами", [], market_segment="Медиа / Продакшн"
    ) is None


def test_market_blend_uses_available_parts() -> None:
    # Корпус с одним текстом, где есть Python → demanded coverage считается
    corpus = ["Нужен Python и LLM для RAG-системы " * 5]
    resume = "Python LLM RAG LangGraph"
    report = compute_report(corpus, resume, market_segment="IT")
    assert report.available is True
    market = _score_market_coverage(
        report, resume, corpus, market_segment="IT"
    )
    assert market is not None
    assert 0 < market <= 100


def test_role_fit_fallback_between_0_and_100() -> None:
    data = _minimal_resume()
    text = "Python LLM"
    report = compute_report([], text, market_segment="")
    score = assemble_score(data, text, report, top_jobs_texts=[], market_segment="")
    assert 0 <= score.role_fit <= 100
    assert 0 <= score.writing <= 100
    # Без корпуса primary ≈ плотность навыков (5/30); role_fit = 85% primary + 15% criteria.
    from core.domains.profile.score_criteria import blend_role_fit, score_criteria_alignment

    primary = round(100 * 5 / 30)
    criteria = score_criteria_alignment(data, text)
    assert score.role_fit == blend_role_fit(primary, criteria)


def test_pm_filled_without_corpus_total_at_least_60() -> None:
    data = _pm_resume()
    text = to_markdown(data)
    report = compute_report([], text, market_segment="Медиа / Продакшн")
    score = assemble_score(
        data, text, report, top_jobs_texts=[], market_segment="Медиа / Продакшн"
    )
    assert score.market_coverage is None
    assert score.total >= 60
    # total = среднее трёх, без нуля market
    assert score.total == round((score.structure + score.writing + score.role_fit) / 3)


def test_details_structure_checklist_and_market_missing() -> None:
    """FR2-47: details.structure — именованные критерии; market_missing — из gap.missing."""
    empty = ResumeData()
    text = ""
    report = ResumeGapReport(
        available=True,
        corpus_size=3,
        concepts_total=5,
        concepts_covered=0,
        demanded_total=2,
        demanded_covered=0,
        missing=[
            GapConcept(name="LangGraph", demand_count=2, demand_pct=66.0, present=False),
            GapConcept(name="RAG", demand_count=2, demand_pct=66.0, present=False),
        ],
    )
    score = assemble_score(empty, text, report, top_jobs_texts=[])
    assert len(score.details.structure) == 8
    assert all(hasattr(c, "id") and hasattr(c, "label") and hasattr(c, "ok") for c in score.details.structure)
    assert sum(1 for c in score.details.structure if c.ok) == 0
    assert score.details.market_missing == ["LangGraph", "RAG"]
    assert score.role_fit_notes  # детерминированный фолбэк, если LLM-заметок нет
    failed = [c for c in score.details.structure if not c.ok]
    assert any(c.id == "full_name" for c in failed)
    assert any(c.id == "experience" for c in failed)
