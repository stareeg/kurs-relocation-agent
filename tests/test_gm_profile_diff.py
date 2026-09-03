"""Тесты сравнения getmatch-профиля с Copilot-резюме (gm_profile.diff_gm_profile)."""

from __future__ import annotations

from core.domains.profile.gm_profile import (
    GmEducation,
    GmExperience,
    GmProfile,
    GmSalaryExpectation,
    diff_gm_profile,
)
from core.domains.profile.model import (
    DesiredPosition,
    Education,
    Experience,
    ResumeData,
)


def test_no_discrepancies_on_empty() -> None:
    """Пустой getmatch-профиль vs пустое Copilot-резюме — расхождений нет (оба пусты)."""
    gm = GmProfile()
    resume = ResumeData()
    assert diff_gm_profile(gm, resume) == []


def test_salary_discrepancy() -> None:
    """Разные зарплатные ожидания — расхождение."""
    gm = GmProfile(
        salary_expectation=GmSalaryExpectation(currency="RUB", from_=300_000, to=400_000),
    )
    resume = ResumeData(
        position=DesiredPosition(salary_min=250_000, salary_comfortable=350_000),
    )
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "salary"
    assert "300" in result[0].getmatch
    assert "250" in result[0].copilot


def test_salary_match() -> None:
    """Одинаковые ожидания — без расхождения."""
    gm = GmProfile(
        salary_expectation=GmSalaryExpectation(currency="RUB", from_=300_000, to=400_000),
    )
    resume = ResumeData(
        position=DesiredPosition(
            salary_min=300_000,
            salary_comfortable=400_000,
            salary_currency="RUB",
        ),
    )
    assert diff_gm_profile(gm, resume) == []


def test_skills_discrepancy() -> None:
    """Навыки, которые есть на getmatch, но нет в Copilot — расхождение (и наоборот)."""
    gm = GmProfile(skills=["Python", "Docker", "PostgreSQL"])
    resume = ResumeData(key_skills=["Python", "Kubernetes", "AWS"])
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "skills"
    assert "docker" in result[0].getmatch.casefold()
    assert "kubernetes" in result[0].copilot.casefold()


def test_skills_case_insensitive() -> None:
    """Сравнение скиллов нечувствительно к регистру."""
    gm = GmProfile(skills=["PYTHON", "Docker"])
    resume = ResumeData(key_skills=["python", "docker"])
    assert diff_gm_profile(gm, resume) == []


def test_skills_whitespace_normalized() -> None:
    """Пробелы в скиллах нормализуются."""
    gm = GmProfile(skills=["  Python  ", "Docker"])
    resume = ResumeData(key_skills=["python", "docker"])
    assert diff_gm_profile(gm, resume) == []


def test_summary_discrepancy() -> None:
    """Разное «Обо мне» — расхождение."""
    gm = GmProfile(summary="Senior backend developer")
    resume = ResumeData(about="Middle backend developer")
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "summary"


def test_summary_match() -> None:
    """Одинаковое «Обо мне» — без расхождения."""
    gm = GmProfile(summary="Senior backend developer, Python/Docker/K8s")
    resume = ResumeData(about="Senior backend developer, Python/Docker/K8s")
    assert diff_gm_profile(gm, resume) == []


def test_position_discrepancy() -> None:
    """Разная текущая/желаемая позиция — расхождение."""
    gm = GmProfile(current_position="Senior Backend Developer")
    resume = ResumeData(position=DesiredPosition(title="Lead Developer"))
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "position"


def test_position_from_current_experience() -> None:
    """Если position.title пуст, берём последнее текущее место работы."""
    gm = GmProfile(
        current_position="Team Lead",
        experience=[
            GmExperience(company="OldCo", position="Middle Dev", start="2020", end="2023"),
            GmExperience(
                company="NewCo",
                position="Team Lead",
                start="2023",
                end="",
                current=True,
            ),
        ],
    )
    resume = ResumeData(
        experience=[
            Experience(company="OldCo", position="Middle Dev", start="2020", end="2023"),
            Experience(
                company="NewCo",
                position="Team Lead",
                start="2023",
                end="",
                current=True,
            ),
        ],
    )
    # position.title пуст, gm.position = "Team Lead", resume берёт current.position = "Team Lead"
    assert diff_gm_profile(gm, resume) == []


def test_experience_count_discrepancy() -> None:
    """Разное число мест работы — расхождение."""
    gm = GmProfile(
        experience=[
            GmExperience(company="A", position="Dev"),
            GmExperience(company="B", position="Senior"),
        ],
    )
    resume = ResumeData(
        experience=[
            Experience(company="A Ltd", position="Developer", start="2020"),
        ],
    )
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "experience"
    assert "2 места" in result[0].getmatch
    assert "1 место" in result[0].copilot


def test_education_count_discrepancy() -> None:
    """Разное число записей об образовании — расхождение."""
    gm = GmProfile(
        education=[
            GmEducation(institution="MSU", degree="Bachelor"),
            GmEducation(institution="HSE", degree="Master"),
        ],
    )
    resume = ResumeData(
        education=[Education(institution="MSU", degree="Бакалавр")],
    )
    result = diff_gm_profile(gm, resume)
    assert len(result) == 1
    assert result[0].field == "education"


def test_multiple_discrepancies() -> None:
    """Несколько расхождений одновременно."""
    gm = GmProfile(
        summary="Senior engineer",
        current_position="Senior Backend",
        skills=["Python", "Docker", "Go"],
    )
    resume = ResumeData(
        about="Middle engineer",
        position=DesiredPosition(title="Middle Backend"),
        key_skills=["Python", "Docker", "Rust"],
    )
    result = diff_gm_profile(gm, resume)
    # salary сумма совпадают (оба пустые), должно быть 3 расхождения
    assert len(result) == 3
    fields = {r.field for r in result}
    assert fields == {"summary", "position", "skills"}


def test_no_discrepancies_full_match() -> None:
    """Полное совпадение профиля getmatch и Copilot-резюме."""
    gm = GmProfile(
        summary="Senior Python разработчик",
        current_position="Senior Backend Developer",
        skills=["Python", "PostgreSQL", "Docker"],
    )
    resume = ResumeData(
        about="Senior Python разработчик",
        position=DesiredPosition(title="Senior Backend Developer"),
        key_skills=["Python", "PostgreSQL", "Docker"],
    )
    assert diff_gm_profile(gm, resume) == []
