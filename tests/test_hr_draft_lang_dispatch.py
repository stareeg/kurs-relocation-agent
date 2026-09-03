"""Э4.5: `_hr_draft_lang` — трек вакансии second_job или резюме на английском -> "en"."""

from __future__ import annotations

import pytest

from core.domains.assistant import service as assistant_service
from core.domains.profile.model import Experience, ResumeData


def _resume_en() -> ResumeData:
    return ResumeData(
        about="I build distributed backend services for international teams.",
        experience=[Experience(position="Backend Engineer", description="Built payment systems.")],
    )


def _resume_ru() -> ResumeData:
    return ResumeData(about="Собираю бэкенд-сервисы для распределённых команд.")


async def test_second_job_track_forces_english_regardless_of_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read(account_id: int, db=None):
        return _resume_ru()

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )
    lang = await assistant_service._hr_draft_lang({"track": "second_job"}, account_id=1)
    assert lang == "en"


async def test_primary_track_falls_back_to_resume_language_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read(account_id: int, db=None):
        return _resume_en()

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )
    lang = await assistant_service._hr_draft_lang({"track": "primary"}, account_id=1)
    assert lang == "en"


async def test_primary_track_russian_resume_stays_russian(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_read(account_id: int, db=None):
        return _resume_ru()

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )
    lang = await assistant_service._hr_draft_lang({}, account_id=1)
    assert lang == "ru"


async def test_no_resume_falls_back_to_russian_without_raising() -> None:
    lang = await assistant_service._hr_draft_lang({}, account_id=999999)
    assert lang == "ru"
