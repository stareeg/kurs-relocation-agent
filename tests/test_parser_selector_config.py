"""Контракт и источник конфига селекторов hh (Шаги 0–1).

Ловит дрейф между `hh_selectors.json`, Python-allowlist и константами расширения;
битый PG-оверрайд не должен отдаваться клиенту; ETag/304 — без тела.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.domains.opportunities.parser_config import (
    MAX_ARRAY_LEN,
    MAX_SELECTOR_LEN,
    PATTERN_NAMES,
    PATTERN_SLOT_DEFAULT,
    PATTERN_SLOTS,
    PG_OVERRIDE_TTL_S,
    SELECTOR_GROUPS,
    SELECTOR_VALUE_KIND,
    PgSelectorOverride,
    get_hh_selectors,
    is_config_fetch_allowed,
    is_valid_css_selector,
    load_repo_hh_selectors,
    looks_like_regex,
    parse_selectors_config,
    reset_parser_config_cache,
    resolve_hh_selectors,
)

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = (
    ROOT / "core" / "domains" / "opportunities" / "sources" / "hh_selectors.json"
)
SELECTORS_TS = ROOT / "extension" / "src" / "dom" / "selectors.ts"
CONFIG_TS = ROOT / "extension" / "src" / "dom" / "selectors-config.ts"


def _ts_object_keys(src: str, const_name: str) -> list[str]:
    match = re.search(
        rf"const {re.escape(const_name)} = \{{(.*?)\n\}};",
        src,
        re.DOTALL,
    )
    assert match, f"не найден const {const_name} в selectors.ts"
    keys: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        key_m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
        if key_m:
            keys.append(key_m.group(1))
    return keys


def test_repo_json_exists_and_parses_clean() -> None:
    assert JSON_PATH.is_file()
    parsed = parse_selectors_config(load_repo_hh_selectors())
    assert parsed.schema_valid
    assert parsed.issues == ()
    assert parsed.version == 1
    assert parsed.selectors.keys() == set(SELECTOR_GROUPS)


def test_allowlist_covers_repo_json_keys() -> None:
    data = load_repo_hh_selectors()
    selectors = data["selectors"]
    assert set(selectors) == set(SELECTOR_GROUPS)
    for group, kind in SELECTOR_VALUE_KIND.items():
        payload = selectors[group]
        if kind == "list":
            assert isinstance(payload, list), group
            assert 1 <= len(payload) <= MAX_ARRAY_LEN
            continue
        assert isinstance(kind, dict)
        assert set(payload) == set(kind), f"дрейф ключей в группе {group}"
        for key, value_kind in kind.items():
            val = payload[key]
            if value_kind == "str":
                assert isinstance(val, str) and is_valid_css_selector(val), f"{group}.{key}"
            else:
                assert isinstance(val, list), f"{group}.{key}"
                assert 1 <= len(val) <= MAX_ARRAY_LEN
                assert all(is_valid_css_selector(item) for item in val), f"{group}.{key}"
    assert set(data["patterns"]) == set(PATTERN_SLOTS)
    for slot, name in data["patterns"].items():
        assert name == PATTERN_SLOT_DEFAULT[slot]
        assert name in PATTERN_NAMES


def _ts_string_fields(src: str, const_name: str) -> dict[str, str]:
    """Простые поля `key: '...'` — без массивов (их ключи уже сверяет `_ts_object_keys`)."""
    match = re.search(
        rf"const {re.escape(const_name)} = \{{(.*?)\n\}};",
        src,
        re.DOTALL,
    )
    assert match, f"не найден const {const_name} в selectors.ts"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        field_m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*'([^']*)'", stripped)
        if field_m:
            fields[field_m.group(1)] = field_m.group(2)
    return fields


def test_json_keys_match_extension_constants() -> None:
    src = SELECTORS_TS.read_text(encoding="utf-8")
    data = load_repo_hh_selectors()["selectors"]
    assert _ts_object_keys(src, "DEFAULT_HH_SELECTORS") == list(data["vacancy"])
    assert _ts_object_keys(src, "DEFAULT_HH_SERP_SELECTORS") == list(data["serp"])
    assert _ts_object_keys(src, "DEFAULT_HH_FALLBACKS") == list(data["fallbacks"])
    assert _ts_object_keys(src, "DEFAULT_HH_NEGOTIATIONS_SELECTORS") == list(data["negotiations"])
    assert _ts_object_keys(src, "DEFAULT_HR_THREAD_SELECTORS") == list(data["hrThread"])
    vacancy_vals = _ts_string_fields(src, "DEFAULT_HH_SELECTORS")
    assert vacancy_vals == data["vacancy"], "значения DEFAULT_HH_SELECTORS разошлись с JSON"
    serp_vals = _ts_string_fields(src, "DEFAULT_HH_SERP_SELECTORS")
    assert serp_vals == data["serp"], "значения DEFAULT_HH_SERP_SELECTORS разошлись с JSON"
    assert data["responseLinks"][-1] == data["serp"]["respondBtn"]
    assert data["responseLinks"][0] == '[data-qa="vacancy-response-link-top"]'


def test_unknown_selector_key_is_dropped() -> None:
    raw = {
        "version": 2,
        "selectors": {
            "vacancy": {
                "salary": '[data-qa="vacancy-salary-v2"]',
                "passport": '[data-qa="passport"]',
                "cardNumber": "input[name=card]",
            }
        },
        "archived_text_re": "/secret/i",
    }
    parsed = parse_selectors_config(raw)
    assert parsed.schema_valid
    assert parsed.version == 2
    vacancy = parsed.selectors["vacancy"]
    assert vacancy["salary"] == '[data-qa="vacancy-salary-v2"]'
    assert "passport" not in vacancy
    assert "cardNumber" not in vacancy
    reasons = {issue.reason for issue in parsed.issues}
    details = {issue.detail for issue in parsed.issues}
    assert "unknown_selector_key" in reasons
    assert "selectors.vacancy.passport" in details
    assert "selectors.vacancy.cardNumber" in details
    assert "archived_text_re" in details
    # соседние дефолтные поля живы
    assert vacancy["title"] == '[data-qa="vacancy-title"]'


def test_unknown_group_is_dropped() -> None:
    raw = {"version": 1, "selectors": {"bankCards": {"pan": "input.pan"}}}
    parsed = parse_selectors_config(raw)
    assert parsed.schema_valid
    assert "bankCards" not in parsed.selectors
    assert any(i.detail == "selectors.bankCards" for i in parsed.issues)


def test_invalid_selector_dropped_individually() -> None:
    raw = {
        "version": 3,
        "selectors": {
            "vacancy": {
                "title": "[[[",
                "company": '[data-qa="vacancy-company-name"]',
                "salary": "/foo/i",
            }
        },
    }
    parsed = parse_selectors_config(raw)
    assert parsed.schema_valid
    vacancy = parsed.selectors["vacancy"]
    assert vacancy["title"] == '[data-qa="vacancy-title"]'  # дефолт, битый отброшен
    assert vacancy["company"] == '[data-qa="vacancy-company-name"]'
    assert vacancy["salary"] == '[data-qa="vacancy-salary"]'
    invalid = [i for i in parsed.issues if i.reason == "invalid_selector"]
    assert {i.detail for i in invalid} >= {
        "selectors.vacancy.title",
        "selectors.vacancy.salary",
    }


def test_regex_value_rejected() -> None:
    assert looks_like_regex("/вы отклик/i")
    assert looks_like_regex("/foo/gim")
    assert looks_like_regex("(?i)secret")
    assert not looks_like_regex('a[href*="/vacancy/"]')
    raw = {
        "version": 1,
        "selectors": {"vacancy": {"title": "/vacancy-title/i"}},
        "patterns": {"appliedText": "/отклик/i"},
    }
    parsed = parse_selectors_config(raw)
    assert parsed.selectors["vacancy"]["title"] == '[data-qa="vacancy-title"]'
    assert parsed.patterns["appliedText"] == "hh_applied"
    assert any(i.reason == "invalid_selector" for i in parsed.issues)


def test_selector_length_and_array_cap() -> None:
    too_long = "div" + ("a" * MAX_SELECTOR_LEN)
    raw = {
        "version": 1,
        "selectors": {
            "vacancy": {"title": too_long},
            "fallbacks": {"title": [f"h{i}" for i in range(MAX_ARRAY_LEN + 3)]},
        },
    }
    parsed = parse_selectors_config(raw)
    assert parsed.selectors["vacancy"]["title"] == '[data-qa="vacancy-title"]'
    titles = parsed.selectors["fallbacks"]["title"]
    assert len(titles) == MAX_ARRAY_LEN
    assert titles == [f"h{i}" for i in range(MAX_ARRAY_LEN)]


def test_schema_error_rolls_back_to_defaults() -> None:
    defaults = load_repo_hh_selectors()
    for raw in (None, "nope", [], {"version": 0}, {"version": 1.5}, {"version": True}):
        parsed = parse_selectors_config(raw)
        assert parsed.used_defaults
        assert not parsed.schema_valid
        assert parsed.issues[0].reason == "config_schema_invalid"
        assert parsed.selectors == defaults["selectors"]
        assert parsed.version == defaults["version"]


def test_broken_selectors_object_rolls_back() -> None:
    parsed = parse_selectors_config({"version": 4, "selectors": ["oops"]})
    assert not parsed.schema_valid
    assert parsed.used_defaults
    assert parsed.version == load_repo_hh_selectors()["version"]


def test_pattern_enum_and_boolean_flag() -> None:
    parsed = parse_selectors_config(
        {
            "version": 1,
            "patterns": {
                "appliedText": False,
                "responsesText": "hh_responses",
                "negotiationStatus": "nope",
                "extra": True,
            },
        }
    )
    assert parsed.patterns["appliedText"] is False
    assert parsed.patterns["responsesText"] == "hh_responses"
    assert parsed.patterns["negotiationStatus"] == "hh_negotiation_status"
    details = {i.detail for i in parsed.issues}
    assert "patterns.negotiationStatus" in details
    assert "patterns.extra" in details


def test_https_only_except_localhost() -> None:
    assert is_config_fetch_allowed("https://copilot.example.com")
    assert is_config_fetch_allowed("https://example.com:443/api")
    assert is_config_fetch_allowed("http://localhost:8000")
    assert is_config_fetch_allowed("http://127.0.0.1:8000")
    assert is_config_fetch_allowed("HTTP://LOCALHOST")
    assert not is_config_fetch_allowed("http://evil.example")
    assert not is_config_fetch_allowed("http://192.168.0.1")
    assert not is_config_fetch_allowed("http://localhost.evil.com")
    assert not is_config_fetch_allowed("ftp://localhost")
    assert not is_config_fetch_allowed("")
    assert not is_config_fetch_allowed("not a url")


def test_ts_contract_mentions_same_reasons_and_limits() -> None:
    src = CONFIG_TS.read_text(encoding="utf-8")
    assert "unknown_selector_key" in src
    assert "invalid_selector" in src
    assert "config_schema_invalid" in src
    assert "config_http_insecure" in src
    assert f"MAX_SELECTOR_LEN = {MAX_SELECTOR_LEN}" in src
    assert f"MAX_ARRAY_LEN = {MAX_ARRAY_LEN}" in src


_FIXED_TS = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def test_no_override_resolves_to_repo() -> None:
    cfg = resolve_hh_selectors(None)
    repo = load_repo_hh_selectors()
    assert cfg.origin == "repo"
    assert cfg.version == repo["version"]
    assert cfg.selectors == repo["selectors"]
    assert cfg.updated_at.tzinfo is not None


def test_broken_db_override_falls_back_and_logs_error(caplog: logging.LogCaptureFixture) -> None:
    override = PgSelectorOverride(version=9, config=["не", "объект"], updated_at=_FIXED_TS)
    with caplog.at_level(logging.ERROR, logger="core.domains.opportunities.parser_config"):
        cfg = resolve_hh_selectors(override)
    repo = load_repo_hh_selectors()
    assert cfg.origin == "repo"
    assert cfg.version == repo["version"]
    assert cfg.selectors == repo["selectors"]
    assert any(getattr(rec, "event", None) == "parser_config_invalid" for rec in caplog.records)


def test_db_override_drops_unknown_keys_and_keeps_origin() -> None:
    override = PgSelectorOverride(
        version=4,
        config={
            "selectors": {
                "vacancy": {
                    "salary": '[data-qa="vacancy-salary-v2"]',
                    "passport": "input.pan",
                }
            }
        },
        updated_at=_FIXED_TS,
    )
    cfg = resolve_hh_selectors(override)
    assert cfg.origin == "db_override"
    assert cfg.version == 4
    assert cfg.updated_at == _FIXED_TS
    vacancy = cfg.selectors["vacancy"]
    assert vacancy["salary"] == '[data-qa="vacancy-salary-v2"]'
    assert "passport" not in vacancy
    assert vacancy["title"] == '[data-qa="vacancy-title"]'


async def test_get_hh_selectors_pg_down_returns_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.domains.opportunities.parser_config as pc

    reset_parser_config_cache()
    monkeypatch.setattr(pc, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("нет PG")))
    cfg = await get_hh_selectors()
    assert cfg.origin == "repo"


async def test_pg_override_cached_for_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.domains.opportunities.parser_config as pc

    reset_parser_config_cache()
    calls = {"n": 0}

    async def fake_fetch(*, db=None):
        _ = db
        calls["n"] += 1
        return None

    clock = {"t": 100.0}
    monkeypatch.setattr(pc, "_fetch_hh_override", fake_fetch)
    monkeypatch.setattr(pc, "_monotonic", lambda: clock["t"])
    await get_hh_selectors()
    await get_hh_selectors()
    assert calls["n"] == 1
    clock["t"] = 100.0 + PG_OVERRIDE_TTL_S
    await get_hh_selectors()
    assert calls["n"] == 2
    reset_parser_config_cache()


def _parser_config_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from api.routers.opportunities import parser_config as parser_config_router

    cfg = resolve_hh_selectors(None)

    async def fake_get() -> object:
        return cfg

    monkeypatch.setattr(parser_config_router, "get_hh_selectors", fake_get)
    app = FastAPI()
    app.include_router(parser_config_router.router)
    return TestClient(app)


def test_parser_config_etag_and_304(monkeypatch: pytest.MonkeyPatch) -> None:
    with _parser_config_client(monkeypatch) as client:
        first = client.get("/api/opportunities/parser-config/hh")
        assert first.status_code == 200
        assert first.headers["etag"] == '"hh-1"'
        assert first.headers["cache-control"] == "no-cache"
        body = first.json()
        assert body["origin"] == "repo"
        assert body["version"] == 1
        assert "vacancy" in body["selectors"]
        assert "title" in body["selectors"]["vacancy"]

        cached = client.get(
            "/api/opportunities/parser-config/hh",
            headers={"If-None-Match": first.headers["etag"]},
        )
        assert cached.status_code == 304
        assert cached.content == b""
        assert cached.headers["etag"] == '"hh-1"'


def test_parser_config_requires_auth() -> None:
    from api.routers.opportunities import parser_config as parser_config_router
    from api.security import require_account

    async def deny() -> None:
        raise HTTPException(status_code=401, detail="Не авторизован")

    app = FastAPI()
    app.include_router(parser_config_router.router, dependencies=[Depends(require_account)])
    app.dependency_overrides[require_account] = deny
    with TestClient(app) as client:
        res = client.get("/api/opportunities/parser-config/hh")
        assert res.status_code == 401
