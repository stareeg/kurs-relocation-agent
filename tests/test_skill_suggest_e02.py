"""E-02 (`plans/skills_2026_07_28.md`): порог автопересборки снимка навыков.

Три вещи проверяются здесь: (1) skills-отпечаток резюме игнорирует телефон/образование/языки
и реагирует на key_skills/роль/критерии/опыт/«Обо мне» (Решение 2); (2) счётчик «+N новых
вакансий» считает по составу выборки, а не по размеру; (3) оба автотриггера уважают порог и
нижнюю границу между пересборками и никогда не пересобирают на пустой выборке.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.profile.model import Experience, ResumeData
from core.domains.profile.skill_suggest import (
    SkillSnapshot,
    count_new_vacancies,
    maybe_auto_refresh_for_new_vacancies,
    maybe_auto_refresh_for_resume_change,
    resume_skills_fingerprint,
)
from core.domains.profile.skills_corpus import SelectionVacancy


def _resume(**overrides) -> ResumeData:
    data = ResumeData()
    data.key_skills = overrides.get("key_skills", ["Python"])
    data.position.title = overrides.get("title", "Backend developer")
    data.about = overrides.get("about", "Люблю бэкенд")
    data.experience = overrides.get(
        "experience", [Experience(company="Ozon", position="Backend", description="API")]
    )
    data.contacts.phone = overrides.get("phone", "+7 900 000-00-00")
    data.education_level = overrides.get("education_level", "Высшее")
    return data


def _vac(vacancy_id: str) -> SelectionVacancy:
    return SelectionVacancy(
        vacancy_id=vacancy_id, title="Backend", company="Ozon", text="", score=60, status="Отклик"
    )


def _fake_read_resume_data(data: ResumeData):
    """Фейк `read_resume_data_for_account` (async, account-aware) с фиксированным ответом."""

    async def _fake(account_id, *, db=None):
        return data

    return _fake


# --- resume_skills_fingerprint: что двигает отпечаток, а что нет (Решение 2) -----------------


def test_fingerprint_ignores_phone_and_education():
    a = _resume(phone="+7 900 000-00-00", education_level="Высшее")
    b = _resume(phone="+7 911 111-11-11", education_level="Неоконченное высшее")
    assert resume_skills_fingerprint(a) == resume_skills_fingerprint(b)


def test_fingerprint_reacts_to_key_skills():
    a = _resume(key_skills=["Python"])
    b = _resume(key_skills=["Python", "Go"])
    assert resume_skills_fingerprint(a) != resume_skills_fingerprint(b)


def test_fingerprint_reacts_to_title():
    a = _resume(title="Backend developer")
    b = _resume(title="Backend team lead")
    assert resume_skills_fingerprint(a) != resume_skills_fingerprint(b)


def test_fingerprint_reacts_to_experience_text():
    a = _resume(experience=[Experience(company="Ozon", position="Backend", description="API")])
    b = _resume(
        experience=[Experience(company="Ozon", position="Backend", description="API + gRPC")]
    )
    assert resume_skills_fingerprint(a) != resume_skills_fingerprint(b)


def test_fingerprint_reacts_to_about():
    a = _resume(about="Люблю бэкенд")
    b = _resume(about="Люблю бэкенд и devops")
    assert resume_skills_fingerprint(a) != resume_skills_fingerprint(b)


# --- count_new_vacancies: по составу выборки, а не по размеру --------------------------------


def test_count_new_vacancies_no_snapshot_counts_everything():
    selection = [_vac("v1"), _vac("v2")]
    assert count_new_vacancies(None, selection) == 2


def test_count_new_vacancies_only_ids_missing_from_snapshot():
    previous = SkillSnapshot(vacancy_ids=["v1"])
    selection = [_vac("v1"), _vac("v2"), _vac("v3")]
    assert count_new_vacancies(previous, selection) == 2


def test_count_new_vacancies_shrunk_selection_is_not_negative():
    # Корпус мог сократиться (вакансия ушла в skip) — не должно уйти в минус или считать «новыми».
    previous = SkillSnapshot(vacancy_ids=["v1", "v2", "v3"])
    selection = [_vac("v1")]
    assert count_new_vacancies(previous, selection) == 0


# --- maybe_auto_refresh_for_new_vacancies: порог + нижняя граница -----------------------------


async def test_auto_refresh_new_vacancies_skips_when_selection_empty(monkeypatch):
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return []

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_new_vacancies(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_new_vacancies_skips_below_threshold(monkeypatch):
    selection = [_vac(f"v{i}") for i in range(5)]
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return None

    async def fake_threshold(*, db=None, **_kw):
        return 10

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_new_vacancies_threshold", fake_threshold
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_new_vacancies(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_new_vacancies_skips_within_min_interval(monkeypatch):
    selection = [_vac(f"v{i}") for i in range(10)]
    previous = SkillSnapshot(vacancy_ids=[], created_at=datetime.now(UTC) - timedelta(hours=1))
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return previous

    async def fake_threshold(*, db=None, **_kw):
        return 10

    async def fake_min_interval(*, db=None, **_kw):
        return 6

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_new_vacancies_threshold", fake_threshold
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_min_refresh_interval_hours", fake_min_interval
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    # Порог достигнут (10 новых из 10), но снимок собран час назад - меньше 6-часовой границы.
    assert await maybe_auto_refresh_for_new_vacancies(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_new_vacancies_runs_when_threshold_and_interval_met(monkeypatch):
    selection = [_vac(f"v{i}") for i in range(10)]
    previous = SkillSnapshot(vacancy_ids=[], created_at=datetime.now(UTC) - timedelta(hours=7))
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return previous

    async def fake_threshold(*, db=None, **_kw):
        return 10

    async def fake_min_interval(*, db=None, **_kw):
        return 6

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_new_vacancies_threshold", fake_threshold
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_min_refresh_interval_hours", fake_min_interval
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_new_vacancies(account_id=1, db=object()) is True
    assert calls["n"] == 1


# --- maybe_auto_refresh_for_resume_change: только на сдвиг skills-отпечатка ------------------


async def test_auto_refresh_resume_change_skips_when_selection_empty(monkeypatch):
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return []

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_resume_change(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_resume_change_skips_when_fingerprint_unchanged(monkeypatch):
    selection = [_vac("v1")]
    data = _resume()
    previous = SkillSnapshot(resume_fp=resume_skills_fingerprint(data))
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return previous

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(data),
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_resume_change(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_resume_change_skips_within_min_interval(monkeypatch):
    selection = [_vac("v1")]
    previous = SkillSnapshot(
        resume_fp="old-fp", created_at=datetime.now(UTC) - timedelta(hours=1)
    )
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return previous

    async def fake_min_interval(*, db=None, **_kw):
        return 6

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(key_skills=["Go"])),
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_min_refresh_interval_hours", fake_min_interval
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_resume_change(account_id=1, db=object()) is False
    assert calls["n"] == 0


async def test_auto_refresh_resume_change_runs_when_fingerprint_shifted_past_interval(
    monkeypatch,
):
    selection = [_vac("v1")]
    previous = SkillSnapshot(
        resume_fp="old-fp", created_at=datetime.now(UTC) - timedelta(hours=7)
    )
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return previous

    async def fake_min_interval(*, db=None, **_kw):
        return 6

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(key_skills=["Go"])),
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest._load_min_refresh_interval_hours", fake_min_interval
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_resume_change(account_id=1, db=object()) is True
    assert calls["n"] == 1


async def test_auto_refresh_resume_change_runs_without_previous_snapshot(monkeypatch):
    selection = [_vac("v1")]
    calls = {"n": 0}

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_latest_snapshot(*, db=None, **_kw):
        return None

    async def fake_refresh(*, db=None, llm=None, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_latest_snapshot", fake_latest_snapshot
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume()),
    )
    monkeypatch.setattr("core.domains.profile.skill_suggest.refresh_snapshot", fake_refresh)

    assert await maybe_auto_refresh_for_resume_change(account_id=1, db=object()) is True
    assert calls["n"] == 1
