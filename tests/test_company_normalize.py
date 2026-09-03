"""FR2-39: детерминированная канонизация названий компаний + LLM-fallback на мусоре."""

from __future__ import annotations

import core.domains.opportunities.companies.normalize as m
from core.domains.opportunities.companies.normalize import (
    needs_brand_extract,
    normalize_company,
    normalize_company_deterministic,
)


def test_sberbank_variants_collapse_to_canonical():
    """Кейс из постановки: ПАО/ОАО Сбербанк и Sber → один канон."""
    assert normalize_company_deterministic("ПАО Сбербанк") == "Сбербанк"
    assert normalize_company_deterministic("ОАО Сбербанк") == "Сбербанк"
    assert normalize_company_deterministic("Sber") == "Сбербанк"
    assert normalize_company_deterministic("сбер") == "Сбербанк"
    assert normalize_company_deterministic("Сбербанк") == "Сбербанк"
    assert normalize_company_deterministic("ООО «Сбербанк»") == "Сбербанк"


def test_strips_org_forms_quotes_and_group_tails():
    assert normalize_company_deterministic('ООО "Ромашка"') == "Ромашка"
    assert normalize_company_deterministic("VK, группа компаний") == "VK"
    assert normalize_company_deterministic("Acme Ltd.") == "Acme"
    assert normalize_company_deterministic("Foo Inc") == "Foo"
    assert normalize_company_deterministic("Bar GmbH") == "Bar"


def test_known_aliases():
    assert normalize_company_deterministic("Yandex") == "Яндекс"
    assert normalize_company_deterministic("ВК") == "VK"
    assert normalize_company_deterministic("Тинькофф") == "Т-Банк"
    assert normalize_company_deterministic("Avito") == "Авито"


def test_empty_and_whitespace():
    assert normalize_company_deterministic(None) == ""
    assert normalize_company_deterministic("") == ""
    assert normalize_company_deterministic("   ") == ""


def test_needs_brand_extract_flags_long_and_slogan():
    assert needs_brand_extract("Сбербанк") is False
    assert needs_brand_extract("Короткий Бренд") is False
    long = "Очень Длинное Название Работодателя Со Слоганом И Ещё Словами"
    assert len(long) > 40
    assert needs_brand_extract(long) is True
    assert needs_brand_extract("Мы ищем лучших инженеров мира") is True
    assert needs_brand_extract("Лидер рынка финтеха 2026") is True


async def test_normalize_company_skips_llm_when_clean(monkeypatch):
    called = {"n": 0}

    async def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("LLM не должен вызываться для чистого бренда")

    monkeypatch.setattr(m, "_extract_brand_llm", boom)
    assert await normalize_company("ПАО Сбербанк") == "Сбербанк"
    assert called["n"] == 0


async def test_normalize_company_llm_fallback_on_garbage(monkeypatch):
    garbage = "Инновационная экосистема будущего - лидер рынка цифровых сервисов и платформ"

    async def fake_extract(raw: str) -> str | None:
        assert raw == garbage
        return "ЭкоПлатформа"

    monkeypatch.setattr(m, "_extract_brand_llm", fake_extract)
    assert needs_brand_extract(normalize_company_deterministic(garbage)) is True
    assert await normalize_company(garbage) == "Экоплатформа"


async def test_normalize_company_allow_llm_false_keeps_deterministic(monkeypatch):
    garbage = "Мы создаём будущее вместе с лучшими инженерами планеты сегодня"

    async def boom(*_a, **_k):
        raise AssertionError("allow_llm=False — LLM запрещён")

    monkeypatch.setattr(m, "_extract_brand_llm", boom)
    det = normalize_company_deterministic(garbage)
    assert await normalize_company(garbage, allow_llm=False) == det


async def test_normalize_company_llm_failure_keeps_deterministic(monkeypatch):
    garbage = "Best place to work hiring dream job engineers for innovation lab forever"

    async def fail(_raw: str) -> str | None:
        return None

    monkeypatch.setattr(m, "_extract_brand_llm", fail)
    det = normalize_company_deterministic(garbage)
    assert await normalize_company(garbage) == det
