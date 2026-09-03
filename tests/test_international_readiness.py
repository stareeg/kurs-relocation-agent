"""Э1.2: чистая деривация международного профиля из ResumeData."""

from __future__ import annotations

from core.domains.profile.international import (
    derive_international_readiness,
)
from core.domains.profile.model import (
    DesiredPosition,
    Experience,
    Language,
    Personal,
    ResumeData,
    SearchCriteria,
)
from core.domains.profile.profile import derive_candidate_profile


def _resume(**kwargs: object) -> ResumeData:
    return ResumeData.model_validate(kwargs)


def test_empty_resume_is_unknown_on_ru_market() -> None:
    ready = derive_international_readiness(_resume())
    assert ready.readiness == "unknown"
    assert ready.home_timezone == ""
    assert ready.overlap == {}
    assert ready.english_level == ""


def test_empty_resume_intl_is_weak_not_ready() -> None:
    ready = derive_international_readiness(
        _resume(search_criteria=SearchCriteria(market_scope="Международный"))
    )
    assert ready.readiness == "weak"
    assert ready.english_level == ""


def test_unknown_city_timezone_empty_readiness_at_most_partial() -> None:
    ready = derive_international_readiness(
        ResumeData(
            personal=Personal(city="Хогвартс"),
            search_criteria=SearchCriteria(market_scope="Международный"),
            languages=[Language(name="Английский", level="C1")],
            position=DesiredPosition(salary_currency="USD"),
        )
    )
    assert ready.home_timezone == ""
    assert ready.readiness in {"partial", "weak"}
    assert ready.readiness != "ready"


def test_moscow_b2_usd_intl_is_ready() -> None:
    ready = derive_international_readiness(
        ResumeData(
            personal=Personal(city="Москва"),
            search_criteria=SearchCriteria(market_scope="Международный"),
            languages=[
                Language(name="Русский", level="Родной"),
                Language(name="Английский", level="B2 — средне-продвинутый"),
            ],
            position=DesiredPosition(salary_currency="USD"),
        )
    )
    assert ready.english_level == "B2"
    assert ready.home_timezone == "Europe/Moscow"
    assert "Русский" in ready.working_languages
    assert "Английский" in ready.working_languages
    assert "USD" in ready.accepted_currencies
    assert "RUB" in ready.accepted_currencies
    assert ready.overlap["EMEA"] > 0
    assert ready.readiness == "ready"


def test_currently_employed_sets_evenings() -> None:
    ready = derive_international_readiness(
        ResumeData(
            experience=[Experience(company="Acme", current=True)],
            search_criteria=SearchCriteria(market_scope="Любой"),
        )
    )
    assert ready.hours_band == "evenings"
    assert "gph" in ready.contract_forms


def test_part_time_without_job_is_part_day() -> None:
    ready = derive_international_readiness(
        ResumeData(
            position=DesiredPosition(employment="Подработка"),
            search_criteria=SearchCriteria(market_scope="Международный"),
        )
    )
    assert ready.hours_band == "part_day"
    assert "employment" not in ready.contract_forms
    assert "gph" in ready.contract_forms


def test_gph_dealbreaker_keeps_contractor_forms_on_intl() -> None:
    ready = derive_international_readiness(
        ResumeData(
            search_criteria=SearchCriteria(
                market_scope="Международный",
                dealbreakers=["Только ГПХ / ИП"],
            ),
            position=DesiredPosition(employment="Полная занятость"),
        )
    )
    assert "employment" in ready.contract_forms
    assert "gph" in ready.contract_forms


def test_candidate_profile_embeds_international() -> None:
    profile = derive_candidate_profile(
        ResumeData(personal=Personal(city="Тбилиси"))
    )
    assert profile.international.home_timezone == "Asia/Tbilisi"
    assert profile.international.readiness == "unknown"


def test_native_english_counts_as_c2() -> None:
    ready = derive_international_readiness(
        ResumeData(
            languages=[Language(name="English", level="Native")],
            search_criteria=SearchCriteria(market_scope="Международный"),
        )
    )
    assert ready.english_level == "C2"
