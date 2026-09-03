"""Э4.2 dual_employment_and_contracting_2026.md: анонимизация резюме под международные письма."""

from __future__ import annotations

from core.domains.profile.anonymize import (
    DisclosurePolicy,
    anonymize_resume,
    current_employer_experience,
)
from core.domains.profile.employer_descriptor import EmployerDescriptor
from core.domains.profile.model import Contacts, Experience, Personal, ResumeData


def _resume() -> ResumeData:
    return ResumeData(
        personal=Personal(city="Москва"),
        contacts=Contacts(site="https://ivanov.dev", other=["см. https://linkedin.com/in/ivanov"]),
        about="Собираю сервисы. Подробнее на https://ivanov.dev/about",
        experience=[
            Experience(
                company="Сбер",
                company_url="https://sber.ru",
                industry="Банки",
                position="Lead ML Engineer",
                start="Март 2024",
                end="",
                current=True,
                area="Москва",
                description="Строил рекомендательную систему.",
            ),
            Experience(
                company="Яндекс",
                position="ML Engineer",
                start="Январь 2020",
                end="Февраль 2024",
                current=False,
                description="Работал над поиском.",
            ),
        ],
    )


def _descriptor() -> EmployerDescriptor:
    return EmployerDescriptor(
        descriptor_ru="крупный банк с ИТ-подразделением",
        descriptor_en="a major bank with an in-house tech division",
        industry="Банки",
    )


def test_all_flags_false_returns_identical_resume() -> None:
    data = _resume()
    policy = DisclosurePolicy(
        hide_current_employer=False,
        hide_all_employers=False,
        hide_public_links=False,
        coarse_dates=False,
        coarse_city=False,
    )
    result = anonymize_resume(data, policy=policy)
    assert result == data


def test_hide_current_employer_replaces_only_current_job() -> None:
    from core.domains.opportunities.companies.normalize import normalize_company_deterministic

    data = _resume()
    policy = DisclosurePolicy(hide_current_employer=True)
    canonical = normalize_company_deterministic("Сбер")
    descriptors = {canonical: _descriptor()}
    result = anonymize_resume(data, policy=policy, descriptors=descriptors, lang="ru")

    current = result.experience[0]
    assert current.company == "крупный банк с ИТ-подразделением"
    assert current.company_url == ""
    # Прошлое место не тронуто — hide_current_employer, не hide_all_employers.
    assert result.experience[1].company == "Яндекс"


def test_hide_current_employer_without_descriptor_uses_neutral_fallback() -> None:
    """Нет дескриптора для скрываемой компании -> нейтральная заглушка, не выдумка (§2.8)."""
    data = _resume()
    policy = DisclosurePolicy(hide_current_employer=True)
    result = anonymize_resume(data, policy=policy, descriptors={}, lang="ru")
    assert "Сбер" not in result.experience[0].company
    assert result.experience[0].company == "текущее место работы"


def test_anonymized_markdown_has_no_current_employer_name() -> None:
    from core.domains.opportunities.companies.normalize import normalize_company_deterministic
    from core.domains.profile.model import to_markdown

    data = _resume()
    policy = DisclosurePolicy(hide_current_employer=True)
    canonical = normalize_company_deterministic("Сбер")
    result = anonymize_resume(data, policy=policy, descriptors={canonical: _descriptor()}, lang="ru")
    markdown = to_markdown(result)
    assert "Сбер" not in markdown
    assert "sber.ru" not in markdown
    # Прошлый работодатель (не скрываемый) остаётся видимым.
    assert "Яндекс" in markdown


def test_hide_public_links_strips_urls() -> None:
    data = _resume()
    policy = DisclosurePolicy(
        hide_current_employer=False, hide_all_employers=False, hide_public_links=True
    )
    result = anonymize_resume(data, policy=policy)
    assert result.contacts.site == ""
    assert "https://" not in result.about
    assert all("https://" not in o for o in result.contacts.other)


def test_current_employer_experience_finds_current_flag() -> None:
    data = _resume()
    current = current_employer_experience(data)
    assert current is not None
    assert current.company == "Сбер"


def test_current_employer_experience_none_without_current_job() -> None:
    data = ResumeData(experience=[Experience(company="Яндекс", current=False)])
    assert current_employer_experience(data) is None
