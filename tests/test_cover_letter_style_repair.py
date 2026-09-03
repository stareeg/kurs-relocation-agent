"""Анти-slop ремонт сопроводительного (2026-08-17): один повтор при нарушениях style_lint,
максимум 2 LLM-вызова на сценарий — тот же паттерн, что у устного рассказа (pitch.py)."""

from __future__ import annotations

import pytest

from core.domains.pipeline import cover_letter as cover_letter_module
from core.domains.pipeline.cover_letter import generate_cover_letter
from core.domains.preparation.asker import record_from_request_fallback
from core.domains.preparation.models import VacancyRecord
from tests.fakes import FakeLlm, use_fake_llm


def _record() -> VacancyRecord:
    return record_from_request_fallback(
        "1",
        vacancy_text="Нужен инженер для оптимизации инференса моделей в проде.",
        title="ML Engineer",
        company="Acme",
    )


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cover_letter_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    # `data=` — после S-critical (2026-08-26) RU-путь резолвит резюме по account_id.
    monkeypatch.setattr(cover_letter_module, "load_resume", lambda **_: "РЕЗЮМЕ")
    monkeypatch.setattr(cover_letter_module, "load_candidate_identity", lambda **_: "Кандидат")

    async def fake_lang(lang, *, account_id: int):
        return "ru"

    monkeypatch.setattr(cover_letter_module, "_resolve_effective_lang", fake_lang)

    async def fake_read(account_id: int, db=None):
        return None

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )


async def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cover_letter_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": ""})()
    )
    with pytest.raises(Exception, match="OPENROUTER_API_KEY"):
        await generate_cover_letter(_record(), account_id=1)


async def test_clean_letter_skips_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    clean = "Собрал сервис оптимизации инференса, снизил задержку на 40%.\nГотов взять то же здесь."
    calls: list[str] = []

    async def fake_complete(feature: str, *, system: str, user: str, **kwargs) -> str:
        assert feature == "cover_letter"
        calls.append(user)
        return clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete))
    result, lang = await generate_cover_letter(_record(), account_id=1)
    assert len(calls) == 1
    assert result == clean
    assert lang == "ru"


async def test_repairs_once_on_style_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    dirty = "В заключение хочу отметить: обладаю глубокой экспертизой в инференсе моделей."
    clean = "Снизил задержку инференса на 40% в проде.\nГотов повторить то же здесь."
    calls: list[str] = []

    async def fake_complete(feature: str, *, system: str, user: str, **kwargs) -> str:
        assert feature == "cover_letter"
        calls.append(user)
        return dirty if len(calls) == 1 else clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete))
    result, lang = await generate_cover_letter(_record(), account_id=1)
    assert len(calls) == 2
    assert "Нарушения стиля" in calls[1]
    assert result == clean
    assert lang == "ru"


async def test_repair_failure_falls_back_to_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    dirty = "В заключение хочу отметить: обладаю глубокой экспертизой."
    calls: list[str] = []

    async def fake_complete(feature: str, *, system: str, user: str, **kwargs) -> str:
        calls.append(user)
        if len(calls) == 1:
            return dirty
        return ""  # второй вызов -> LlmError ("LLM вернул пустое письмо")

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete))
    result, lang = await generate_cover_letter(_record(), account_id=1)
    assert len(calls) == 2
    assert result == dirty
    assert lang == "ru"
