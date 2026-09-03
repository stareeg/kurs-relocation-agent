"""Э4.4 dual_employment_and_contracting_2026.md: письмо под международный рынок + переключалка языка."""

from __future__ import annotations

import pytest

from core.domains.pipeline import cover_letter as cover_letter_module
from core.domains.pipeline.cover_letter import generate_cover_letter
from core.domains.preparation.asker import record_from_request_fallback
from core.domains.preparation.models import VacancyRecord
from core.domains.profile.anonymize import DisclosurePolicy
from core.domains.profile.employer_descriptor import EmployerDescriptor
from core.domains.profile.model import Contacts, Experience, Personal, ResumeData
from tests.fakes import FakeLlm, use_fake_llm


def _record() -> VacancyRecord:
    return record_from_request_fallback(
        "1",
        vacancy_text="We need a remote contractor to optimize our inference pipeline.",
        title="ML Engineer",
        company="Acme",
    )


def _resume_ru() -> ResumeData:
    return ResumeData(
        personal=Personal(city="Москва"),
        contacts=Contacts(telegram="@ivanov"),
        about="Собираю сервисы для оптимизации инференса моделей.",
        experience=[
            Experience(
                company="Сбер",
                industry="Банки",
                position="Lead ML Engineer",
                current=True,
                description="Строил рекомендательную систему в проде.",
            )
        ],
    )


def _resume_en() -> ResumeData:
    return ResumeData(
        personal=Personal(city="Moscow"),
        about="I build inference optimization services for distributed teams.",
        experience=[
            Experience(
                company="Acme Corp",
                industry="Cloud",
                position="Lead ML Engineer",
                current=True,
                description="Built a recommendation system in production.",
            )
        ],
    )


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cover_letter_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )


def _stub_resume(monkeypatch: pytest.MonkeyPatch, resume: ResumeData) -> None:
    async def fake_read(account_id: int, db=None):
        return resume

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )


def _stub_no_anonymization(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_policy(*, account_id, db=None):
        return DisclosurePolicy(
            hide_current_employer=False,
            hide_all_employers=False,
            hide_public_links=False,
        )

    monkeypatch.setattr("core.domains.profile.anonymize.get_disclosure_policy", fake_policy)


def _stub_anonymization_with_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_policy(*, account_id, db=None):
        return DisclosurePolicy(hide_current_employer=True)

    async def fake_descriptor(account_id, *, company, industry="", area="", role_context="", db=None, llm=None):
        return EmployerDescriptor(
            descriptor_ru="крупный банк с ИТ-подразделением",
            descriptor_en="a major bank with an in-house tech division",
            industry=industry,
        )

    monkeypatch.setattr("core.domains.profile.anonymize.get_disclosure_policy", fake_policy)
    monkeypatch.setattr(
        "core.domains.profile.employer_descriptor.get_or_create_employer_descriptor",
        fake_descriptor,
    )


async def test_auto_detects_russian_resume_as_ru() -> None:
    lang = await cover_letter_module._resolve_effective_lang(None, account_id=1)
    # Нет резюме в тестовом окружении (PG недоступен) -> безопасный дефолт "ru".
    assert lang == "ru"


async def test_explicit_lang_overrides_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch, _resume_ru())
    lang = await cover_letter_module._resolve_effective_lang("en", account_id=1)
    assert lang == "en"


async def test_detects_english_resume_as_en(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch, _resume_en())
    lang = await cover_letter_module._resolve_effective_lang(None, account_id=1)
    assert lang == "en"


async def test_detects_russian_resume_as_ru(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch, _resume_ru())
    lang = await cover_letter_module._resolve_effective_lang(None, account_id=1)
    assert lang == "ru"


async def test_en_letter_uses_cover_letter_intl_feature_and_en_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    _stub_resume(monkeypatch, _resume_en())
    _stub_no_anonymization(monkeypatch)
    clean = "Cut inference latency by 40% in production.\nReady to do the same here."
    llm = use_fake_llm(monkeypatch, FakeLlm(text=clean))

    letter, lang = await generate_cover_letter(_record(), account_id=1, lang="en")

    assert lang == "en"
    assert llm.calls[0]["feature"] == "cover_letter_intl"
    assert "Acme Corp" in llm.calls[0]["system"]  # анонимизация выключена - имя видно
    assert clean in letter


async def test_en_letter_repairs_on_cliches(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    _stub_resume(monkeypatch, _resume_en())
    _stub_no_anonymization(monkeypatch)
    dirty = "I am excited to apply - I have a proven track record."
    clean = "Cut inference latency by 40% in production.\nReady to do the same here."
    calls: list[str] = []

    async def fake_complete(feature: str, *, system: str, user: str, **kwargs) -> str:
        assert feature == "cover_letter_intl"
        calls.append(user)
        return dirty if len(calls) == 1 else clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete))
    letter, lang = await generate_cover_letter(_record(), account_id=1, lang="en")
    assert len(calls) == 2
    assert lang == "en"
    assert letter == clean


async def test_en_letter_hides_current_employer_when_policy_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    _stub_resume(monkeypatch, _resume_ru())
    _stub_anonymization_with_descriptor(monkeypatch)
    llm = use_fake_llm(monkeypatch, FakeLlm(text="Ready to help.\nLet's talk."))

    letter, lang = await generate_cover_letter(_record(), account_id=1, lang="en")

    assert lang == "en"
    system = llm.calls[0]["system"]
    assert "Сбер" not in system
    assert "a major bank with an in-house tech division" in system
