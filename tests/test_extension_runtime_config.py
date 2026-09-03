"""Рантайм-конфиг расширения (`core.domains.opportunities.extension_runtime_config`).

Сервер меняет *значения* (флаги/тюнинг/селекторы), не *структуру*: неизвестное отбрасывается,
числа клампятся, регекс в селекторе не принимается, битый оверрайд → репозиторный дефолт.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.domains.opportunities.extension_runtime_config import (
    _APPLY_SELECTOR_KEYS,
    _PARSE_SELECTOR_KEYS,
    _TEXT_SIGNAL_KEYS,
    _TUNING_RANGE,
    _TUNING_SCALAR,
    FLAG_KEYS,
    load_repo_config,
    reset_extension_runtime_config_cache,
    resolve_extension_runtime_config,
)

_ROOT = Path(__file__).resolve().parents[1]
_TS_CLIENT = _ROOT / "extension" / "src" / "dom" / "extension-runtime-config.ts"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_extension_runtime_config_cache()
    yield
    reset_extension_runtime_config_cache()


def test_no_override_returns_repo_defaults() -> None:
    cfg = resolve_extension_runtime_config(None, None)
    assert cfg.origin == "repo"
    assert cfg.flags["auto_apply_enabled"] is True
    assert cfg.tuning["auto_apply_tick_minutes"] == 5
    assert (
        cfg.apply_selectors["hh"]["responseLinkTop"]
        == '[data-qa="vacancy-response-link-top"]'
    )
    assert cfg.issues == ()


def test_repo_json_shape_is_complete() -> None:
    """Дефолтный JSON должен нести все ключи, на которые опирается расширение."""
    repo = load_repo_config()
    assert set(repo["flags"]) >= {
        "auto_apply_enabled",
        "auto_apply_hh_enabled",
        "discovery_enabled",
        "anketa_resume_enabled",
    }
    assert repo["tuning"]["max_real_applications_per_tick"] == 1
    assert len(repo["apply_selectors"]["hh"]) == 9
    assert set(repo["parse_selectors"]["getmatch"]) == set(_PARSE_SELECTOR_KEYS["getmatch"])
    assert set(repo["text_signals"]["getmatch"]) == set(_TEXT_SIGNAL_KEYS["getmatch"])
    assert set(repo["text_signals"]["hh"]) == set(_TEXT_SIGNAL_KEYS["hh"])


def test_flag_override_and_unknown_flag_reported() -> None:
    cfg = resolve_extension_runtime_config(
        {"version": 7, "flags": {"auto_apply_hh_enabled": False, "bogus": True}}, None
    )
    assert cfg.origin == "db_override"
    assert cfg.version == 7
    assert cfg.flags["auto_apply_hh_enabled"] is False
    assert "bogus" not in cfg.flags
    assert any("bogus" in i for i in cfg.issues)


def test_tuning_clamped_both_ends() -> None:
    cfg = resolve_extension_runtime_config(
        {
            "version": 2,
            "tuning": {
                "auto_apply_tick_minutes": 9999,
                "max_real_applications_per_tick": 0,
                "auto_apply_delay_ms": [90000, 20000],
                "apply_reading_delay_ms": [1, 10_000_000],
            },
        },
        None,
    )
    assert cfg.tuning["auto_apply_tick_minutes"] == 60
    assert cfg.tuning["max_real_applications_per_tick"] == 1
    assert cfg.tuning["auto_apply_delay_ms"] == [20000, 90000]
    assert cfg.tuning["apply_reading_delay_ms"] == [1, 60000]


def test_discovery_tick_minutes_keeps_fraction() -> None:
    """`discovery_tick_minutes` = период chrome.alarms; 0.5 (= 30с) не округляется до целого,
    ниже пола 0.5 — кламп."""
    cfg = resolve_extension_runtime_config(
        {"version": 2, "tuning": {"discovery_tick_minutes": 0.5}}, None
    )
    assert cfg.tuning["discovery_tick_minutes"] == 0.5
    low = resolve_extension_runtime_config(
        {"version": 2, "tuning": {"discovery_tick_minutes": 0.1}}, None
    )
    assert low.tuning["discovery_tick_minutes"] == 0.5


def test_repo_default_discovery_tempo_is_30_to_90s() -> None:
    cfg = resolve_extension_runtime_config(None, None)
    assert cfg.tuning["discovery_tick_minutes"] == 0.5
    assert cfg.tuning["discovery_delay_ms"] == [30000, 90000]


def test_selector_regex_rejected_unknown_key_dropped() -> None:
    cfg = resolve_extension_runtime_config(
        {
            "version": 3,
            "apply_selectors": {
                "hh": {
                    "responseLinkTop": "a.new-btn",
                    "letterTextarea": "/evil/",
                    "nope": ".x",
                },
                "mystery": {"a": ".b"},
            },
        },
        None,
    )
    assert cfg.apply_selectors["hh"]["responseLinkTop"] == "a.new-btn"
    assert (
        cfg.apply_selectors["hh"]["letterTextarea"]
        == '[data-qa="vacancy-response-popup-form-letter-input"]'
    )
    assert "nope" not in cfg.apply_selectors["hh"]
    assert "mystery" not in cfg.apply_selectors
    assert len([i for i in cfg.issues if "letterTextarea" in i or "nope" in i or "mystery" in i]) == 3


def test_every_bundled_json_import_is_copied_in_dockerfile() -> None:
    """Каждый `import ... from '.../core/domains/opportunities/sources/*.json'` в TS расширения
    должен попадать в docker build (COPY в deploy/Dockerfile), иначе esbuild «Could not
    resolve» и деплой падает (инцидент 2026-08-28: extension_runtime_config.json забыли)."""
    imported: set[str] = set()
    for ts in (_ROOT / "extension" / "src").rglob("*.ts"):
        for m in re.finditer(
            r"from '\.\./\.\./\.\./core/domains/opportunities/sources/([\w.]+\.json)'",
            ts.read_text(encoding="utf-8"),
        ):
            imported.add(m.group(1))
    assert imported, "не нашли ни одного JSON-импорта — регекс/раскладка изменились?"

    dockerfile = (_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    copy_line = next(
        line
        for line in dockerfile.splitlines()
        if line.startswith("COPY core/domains/opportunities/sources/")
    )
    for name in imported:
        covered = (
            f"sources/{name} " in copy_line
            or "sources/*.json " in copy_line
            or copy_line.rstrip().endswith("sources/*.json")
        )
        assert covered, f"{name} импортируется в расширении, но не COPY'ится в Dockerfile: {copy_line}"


@pytest.mark.parametrize("junk", [42, "x", [1, 2], {"version": "no"}, {}])
def test_garbage_override_falls_back_to_repo(junk: object) -> None:
    cfg = resolve_extension_runtime_config(junk, datetime.now(UTC))
    assert cfg.flags["auto_apply_enabled"] is True
    assert cfg.tuning["auto_apply_tick_minutes"] == 5


def test_backend_and_extension_client_stay_in_sync() -> None:
    """Клиент расширения дублирует диапазоны/ключи валидации — они не должны разъезжаться
    (тот же приём, что `test_json_keys_match_extension_constants` для hh-селекторов)."""
    src = _TS_CLIENT.read_text(encoding="utf-8")

    def _block(name: str) -> str:
        m = re.search(rf"const {name}[^=]*= \{{(.*?)\n\}}", src, re.S)
        assert m is not None, f"{name} не найден в TS-клиенте"
        return m.group(1)

    ts_flags = re.search(r"FLAG_KEYS = \[(.*?)\] as const", src, re.S)
    assert ts_flags is not None
    assert set(re.findall(r"'([a-z_]+)'", ts_flags.group(1))) == set(FLAG_KEYS)

    for key, (lo, hi) in {**_TUNING_SCALAR, **_TUNING_RANGE}.items():
        m = re.search(rf"{key}: \[([\d_.]+), ([\d_.]+)\]", src)
        assert m is not None, f"{key} не найден в TS-клиенте"
        got = (float(m.group(1).replace("_", "")), float(m.group(2).replace("_", "")))
        assert got == (float(lo), float(hi)), key

    for name, backend in (
        ("APPLY_SELECTOR_KEYS", _APPLY_SELECTOR_KEYS),
        ("PARSE_SELECTOR_KEYS", _PARSE_SELECTOR_KEYS),
        ("TEXT_SIGNAL_KEYS", _TEXT_SIGNAL_KEYS),
    ):
        block = _block(name)
        for platform, keys in backend.items():
            group = re.search(rf"{platform}: \[(.*?)\]", block, re.S)
            assert group is not None, f"{name}.{platform}"
            assert set(re.findall(r"'([a-zA-Z_]+)'", group.group(1))) == set(keys), f"{name}.{platform}"


def test_repo_json_and_client_builtin_tuning_match() -> None:
    """Зашитый дефолт JSON и фолбэк-числа в `buildFromRaw` клиента не должны разъезжаться."""
    repo = load_repo_config()
    src = _TS_CLIENT.read_text(encoding="utf-8")
    for key, value in repo["tuning"].items():
        if isinstance(value, list):
            m = re.search(rf"{key}, \[([\d_.]+), ([\d_.]+)\]", src)
            assert m is not None, key
            got = [float(m.group(1).replace("_", "")), float(m.group(2).replace("_", ""))]
            assert got == [float(v) for v in value], key
        else:
            m = re.search(rf"{key} \?\? ([\d_.]+)", src)
            assert m is not None, key
            assert float(m.group(1).replace("_", "")) == float(value), key
