"""«Быстрый» пропуск (POST /skip) пишет только в `skipped_vacancies`, без jobs-stub.

До 2026-08-18 `skip_and_store` заводил пустой jobs-stub (`SOURCE_SKIP_STUB`), когда вакансии
ещё не было в `jobs` — чтобы клик «Пропустить» подтверждался карточкой на доске «Вакансии».
С надёжным парсингом страницы вакансии и автооткликами смысл в карточке без текста JD отпал —
десятки пустых «Просмотрено»-карточек только мешали (см. core/domains/opportunities/service.py).
Пропуск остаётся видимым через список пропущенных, не через доску.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities import service
from core.domains.opportunities.skipped import SkippedVacancy


async def test_skip_only_writes_skipped_vacancies(monkeypatch: pytest.MonkeyPatch):
    fake_record = SkippedVacancy(vacancy_id="136326946", skip_reason="Не подхожу по грейду")
    save_skipped = AsyncMock(return_value=fake_record)
    get_job = AsyncMock()
    save_job = AsyncMock()

    monkeypatch.setattr(service, "save_skipped", save_skipped)
    monkeypatch.setattr(service, "get_job_by_vacancy_id", get_job)
    monkeypatch.setattr(service, "save_job", save_job)

    result = await service.skip_and_store(
        "136326946",
        "Не подхожу по грейду",
        url="https://hh.ru/vacancy/136326946",
        title="Backend-разработчик",
        company="ООО Ромашка",
        account_id=1,
    )

    assert result == fake_record
    save_skipped.assert_awaited_once()
    get_job.assert_not_awaited()
    save_job.assert_not_awaited()


async def test_skip_passes_score_snapshot_to_skipped_vacancies_only(
    monkeypatch: pytest.MonkeyPatch,
):
    """Скор/рекомендация на момент решения — это снимок для аналитики в `skipped_vacancies`,
    не значит, что вакансия проходила `score_vacancy` целиком; в `jobs` он больше не пишется
    вообще (jobs-stub убран)."""
    fake_record = SkippedVacancy(vacancy_id="136326947", skip_reason="Низкая вилка")
    save_skipped = AsyncMock(return_value=fake_record)

    monkeypatch.setattr(service, "save_skipped", save_skipped)

    result = await service.skip_and_store(
        "136326947",
        "Низкая вилка",
        overall_score=99,
        recommendation="strong_apply",
        account_id=1,
    )

    assert result == fake_record
    assert save_skipped.await_args.kwargs["overall_score"] == 99
    assert save_skipped.await_args.kwargs["recommendation"] == "strong_apply"
