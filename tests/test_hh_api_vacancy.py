"""Шаг 5: сервер не скрейпит hh.ru — карточка через api.hh.ru, SERP выключен."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bot_app.handlers.forwarded import _HH_OPEN_IN_BROWSER, _url_fetch_fallback
from core.domains.opportunities.sources.hh import (
    HH_API_DENIED_CODE,
    HH_SERP_DISABLED_CODE,
    HhVacancySource,
    discover_from_search_url,
    fetch_hh_vacancy_api,
    hh_api_user_agent,
    parse_hh_vacancy_api,
)
from core.kernel.errors import InvalidInput, Unprocessable

ROOT = Path(__file__).resolve().parents[1]
HH_PY = ROOT / "core" / "domains" / "opportunities" / "sources" / "hh.py"


def _sample_api_payload() -> dict:
    return {
        "id": "12345678",
        "name": "Senior Python Developer",
        "description": "<p>Нужен Python и FastAPI. Полная удалёнка по РФ.</p>",
        "employer": {"id": "42", "name": "Acme"},
        "area": {"name": "Москва"},
        "salary": {"from": 300000, "to": 400000, "currency": "RUR", "gross": False},
        "work_format": [{"id": "REMOTE", "name": "Удалённо"}],
        "key_skills": [{"name": "Python"}, {"name": "FastAPI"}],
        "alternate_url": "https://hh.ru/vacancy/12345678",
        "response_letter_required": True,
    }


def test_hh_source_does_not_spoof_chrome_ua() -> None:
    src = HH_PY.read_text(encoding="utf-8")
    assert "Mozilla/5.0" not in src
    assert "Chrome/" not in src
    assert "fetch_search_html" not in src
    assert "fetch_vacancy_description" not in src


def test_hh_api_user_agent_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_API_USER_AGENT", raising=False)
    ua = hh_api_user_agent()
    assert ua.startswith("CareerCopilot/")
    assert "Chrome" not in ua
    assert "Mozilla" not in ua
    assert "http" not in ua.lower()
    assert "copilot.example.com" not in ua


def test_hh_api_user_agent_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_API_USER_AGENT", "CareerCopilot/9.9")
    assert hh_api_user_agent() == "CareerCopilot/9.9"


def test_parse_hh_vacancy_api_maps_fields() -> None:
    raw = parse_hh_vacancy_api(_sample_api_payload())
    assert raw.vacancy_id == "12345678"
    assert raw.title == "Senior Python Developer"
    assert raw.company == "Acme"
    assert raw.area == "Москва"
    assert raw.work_format == "удалённо"
    assert "300000" in raw.salary_text and "на руки" in raw.salary_text
    assert "FastAPI" in raw.text
    assert raw.skills == ["Python", "FastAPI"]
    assert raw.source == "hh"
    assert raw.url == "https://hh.ru/vacancy/12345678"


def test_parse_hh_vacancy_api_empty_rejected() -> None:
    with pytest.raises(InvalidInput):
        parse_hh_vacancy_api({})


@pytest.mark.asyncio
async def test_discover_from_search_url_disabled() -> None:
    with pytest.raises(Unprocessable) as ei:
        await discover_from_search_url("https://hh.ru/search/vacancy?text=python")
    assert ei.value.code == HH_SERP_DISABLED_CODE


@pytest.mark.asyncio
async def test_fetch_search_url_does_not_hit_network() -> None:
    src = HhVacancySource()
    with pytest.raises(Unprocessable) as ei:
        await src.fetch("https://hh.ru/search/vacancy?text=python")
    assert ei.value.code == HH_SERP_DISABLED_CODE


@pytest.mark.asyncio
async def test_fetch_hh_vacancy_api_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/vacancies/12345678"
        assert "Chrome" not in request.headers.get("User-Agent", "")
        assert request.headers.get("User-Agent", "").startswith("CareerCopilot/")
        return httpx.Response(200, json=_sample_api_payload())

    raw = await fetch_hh_vacancy_api("12345678", transport=httpx.MockTransport(handler))
    assert raw.title == "Senior Python Developer"


@pytest.mark.asyncio
async def test_fetch_hh_vacancy_api_403_no_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={"errors": [{"value": "forbidden"}]})

    with pytest.raises(Unprocessable) as ei:
        await fetch_hh_vacancy_api("12345678", transport=httpx.MockTransport(handler))
    assert ei.value.code == HH_API_DENIED_CODE
    assert calls == 1


@pytest.mark.asyncio
async def test_fetch_hh_vacancy_api_429_no_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="rate limit")

    with pytest.raises(Unprocessable) as ei:
        await fetch_hh_vacancy_api("1", transport=httpx.MockTransport(handler))
    assert ei.value.code == HH_API_DENIED_CODE
    assert calls == 1


@pytest.mark.asyncio
async def test_hh_source_fetch_vacancy_url_uses_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake(vid: str, **_kwargs: object):
        seen.append(vid)
        return parse_hh_vacancy_api(_sample_api_payload())

    monkeypatch.setattr("core.domains.opportunities.sources.hh.fetch_hh_vacancy_api", fake)
    raws = await HhVacancySource().fetch("https://hh.ru/vacancy/12345678")
    assert seen == ["12345678"]
    assert raws[0].title == "Senior Python Developer"


def test_bot_hh_fallback_asks_to_open_extension() -> None:
    assert "браузере" in _url_fetch_fallback("hh")
    assert _url_fetch_fallback("hh") == _HH_OPEN_IN_BROWSER
    assert _url_fetch_fallback("getmatch") != _HH_OPEN_IN_BROWSER
    assert "пересылкой" in _url_fetch_fallback("getmatch")
