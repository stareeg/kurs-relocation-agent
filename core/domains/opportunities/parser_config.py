"""Контракт и источник динамического конфига селекторов hh (Шаги 0–1).

Сервер может менять «как найти» (строки CSS), но не «что собрать»: неизвестный ключ
отбрасывается, регекс с сервера не принимается. Расширение валидирует тем же контрактом
(`extension/src/dom/selectors-config.ts`); битый оверрайд не должен расширять объём
вычитываемого со страницы авторизованной сессии hh.

Источник правды двухслойный: JSON в репозитории, горячий оверрайд в
`parser_selector_configs`. Битый оверрайд → репозиторный дефолт, не 500.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

SOURCE_HH = "hh"
PG_OVERRIDE_TTL_S = 60.0
ConfigOrigin = Literal["db_override", "repo"]

MAX_SELECTOR_LEN = 200
MAX_ARRAY_LEN = 10

SELECTOR_GROUPS: tuple[str, ...] = (
    "vacancy",
    "serp",
    "responseLinks",
    "fallbacks",
    "negotiations",
    "hrThread",
)

# Ключ → "str" | "list". responseLinks — сама группа является списком селекторов.
SELECTOR_VALUE_KIND: dict[str, str | dict[str, str]] = {
    "vacancy": {
        "title": "str",
        "company": "str",
        "salary": "str",
        "description": "str",
        "schedule": "str",
        "remote": "str",
        "workFormat": "str",
        "employmentText": "str",
        "scheduleByDays": "str",
        "workingHours": "str",
        "experienceText": "str",
        "address": "str",
        "addressMap": "str",
        "addCoverLetter": "str",
        "addCoverLetterPopup": "str",
        "coverLetterInput": "str",
        "coverLetterInputPopup": "str",
        "modalOverlay": "str",
        "alreadyApplied": "str",
        "archiveDescription": "str",
        "archiveHeader": "str",
        "responsesCount": "str",
        "responsesInfo": "str",
    },
    "serp": {
        "vacancyCard": "str",
        "title": "str",
        "titleLink": "str",
        "employer": "str",
        "employerLink": "str",
        "salary": "str",
        "address": "str",
        "metro": "str",
        "respondBtn": "str",
        "pagerNext": "str",
    },
    "responseLinks": "list",
    "fallbacks": {
        "title": "list",
        "company": "list",
        "salary": "list",
        "description": "list",
        "serpTitleLink": "list",
        "serpEmployer": "list",
        "serpSalary": "list",
    },
    "negotiations": {
        "card": "list",
        "titleLink": "str",
        "company": "list",
        "statusBadge": "list",
        "date": "str",
        "lastMessage": "list",
    },
    "hrThread": {
        "vacancyLink": "str",
        "companyLink": "str",
        "messageItem": "list",
        "dayDivider": "str",
    },
}

PATTERN_SLOTS: tuple[str, ...] = ("appliedText", "responsesText", "negotiationStatus")
PATTERN_NAMES: frozenset[str] = frozenset({"hh_applied", "hh_responses", "hh_negotiation_status"})
PATTERN_SLOT_DEFAULT: dict[str, str] = {
    "appliedText": "hh_applied",
    "responsesText": "hh_responses",
    "negotiationStatus": "hh_negotiation_status",
}

# Поля конверта API (Шаг 1) — не селекторы, молча игнорируются.
_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {"version", "selectors", "patterns", "updated_at", "origin"}
)

IssueReason = Literal[
    "unknown_selector_key",
    "invalid_selector",
    "config_schema_invalid",
    "config_http_insecure",
]

_REGEX_VALUE_RE = re.compile(r"^/.+/[gimsuy]*$")
_LOCAL_HTTP_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1"})

_REPO_JSON = Path(__file__).resolve().parent / "sources" / "hh_selectors.json"


@dataclass(frozen=True)
class ConfigIssue:
    reason: IssueReason
    detail: str


@dataclass(frozen=True)
class ParsedSelectorsConfig:
    version: int
    selectors: dict[str, Any]
    patterns: dict[str, str | bool]
    issues: tuple[ConfigIssue, ...]
    schema_valid: bool
    used_defaults: bool


@dataclass(frozen=True)
class PgSelectorOverride:
    """Строка `parser_selector_configs` до валидации контракта."""

    version: int
    config: Any
    updated_at: datetime


@dataclass(frozen=True)
class HhSelectorsConfig:
    """То, что отдаёт API: уже прогнанное через контракт, никогда не 500 из-за БД."""

    version: int
    updated_at: datetime
    origin: ConfigOrigin
    selectors: dict[str, Any]
    patterns: dict[str, str | bool]


_pg_cache: tuple[float, HhSelectorsConfig] | None = None


def _monotonic() -> float:
    return time.monotonic()


def reset_parser_config_cache() -> None:
    """Сброс TTL-кэша оверрайда — только для тестов."""
    global _pg_cache
    _pg_cache = None


def _repo_updated_at() -> datetime:
    return datetime.fromtimestamp(_REPO_JSON.stat().st_mtime, tz=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _from_parsed(
    parsed: ParsedSelectorsConfig, *, origin: ConfigOrigin, updated_at: datetime
) -> HhSelectorsConfig:
    return HhSelectorsConfig(
        version=parsed.version,
        updated_at=_as_utc(updated_at),
        origin=origin,
        selectors=parsed.selectors,
        patterns=parsed.patterns,
    )


def _log_invalid_override(override: PgSelectorOverride, parsed: ParsedSelectorsConfig) -> None:
    detail = parsed.issues[0].detail if parsed.issues else "схема"
    event(
        logger,
        "РАСШИРЕНИЕ",
        "битый оверрайд селекторов %s в БД, отдаём репозиторный дефолт: %s",
        SOURCE_HH,
        detail,
        level=logging.ERROR,
        event="parser_config_invalid",
        source=SOURCE_HH,
        version=override.version,
        detail=detail,
    )


def resolve_hh_selectors(override: PgSelectorOverride | None) -> HhSelectorsConfig:
    """Оверрайд из PG (уже прочитанный) или None → валидный конфиг. Без I/O в БД."""
    repo = load_repo_hh_selectors()
    repo_cfg = _from_parsed(
        parse_selectors_config(repo, defaults=repo),
        origin="repo",
        updated_at=_repo_updated_at(),
    )
    if override is None:
        return repo_cfg
    payload: object
    if isinstance(override.config, dict):
        payload = {**override.config, "version": override.version}
    else:
        payload = override.config
    parsed = parse_selectors_config(payload, defaults=repo)
    if not parsed.schema_valid:
        _log_invalid_override(override, parsed)
        return repo_cfg
    return _from_parsed(parsed, origin="db_override", updated_at=override.updated_at)


async def _fetch_hh_override(*, db: Executor | None = None) -> PgSelectorOverride | None:
    """Строка source='hh'; нет таблицы / нет PG / нет строки → None, не исключение."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            "select version, config, updated_at from parser_selector_configs where source = $1",
            SOURCE_HH,
        )
    except Exception as exc:
        logger.debug("parser_selector_configs: чтение недоступно: %s", exc)
        return None
    if row is None:
        return None
    return PgSelectorOverride(
        version=int(row["version"]),
        config=row["config"],
        updated_at=_as_utc(row["updated_at"]),
    )


async def get_hh_selectors(*, db: Executor | None = None) -> HhSelectorsConfig:
    """Оверрайд из PG (TTL 60 с), иначе дефолт из репозитория. Версия монотонная."""
    global _pg_cache
    now = _monotonic()
    cached = _pg_cache
    if cached is not None and (now - cached[0]) < PG_OVERRIDE_TTL_S:
        return cached[1]
    cfg = resolve_hh_selectors(await _fetch_hh_override(db=db))
    _pg_cache = (now, cfg)
    return cfg


def _valid_version(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


@lru_cache(maxsize=1)
def _load_repo_raw() -> dict[str, Any]:
    return json.loads(_REPO_JSON.read_text(encoding="utf-8"))


def load_repo_hh_selectors() -> dict[str, Any]:
    """Дефолт из репозитория. Копия: вызывающий не мутирует кэш процесса."""
    return copy.deepcopy(_load_repo_raw())


def is_config_fetch_allowed(api_base_url: str) -> bool:
    """0.4: конфиг с сети — только https, либо http на localhost/127.0.0.1."""
    if not api_base_url or not isinstance(api_base_url, str):
        return False
    parsed = urlparse(api_base_url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https":
        return True
    return scheme == "http" and host in _LOCAL_HTTP_HOSTS


def looks_like_regex(value: str) -> bool:
    """Регекс с сервера запрещён (ReDoS + контрабанда логики под видом данных)."""
    stripped = value.strip()
    if _REGEX_VALUE_RE.match(stripped):
        return True
    return "(?" in stripped


def is_valid_css_selector(value: object) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s or len(s) > MAX_SELECTOR_LEN:
        return False
    if "\x00" in s or looks_like_regex(s):
        return False
    if not _css_brackets_and_quotes_ok(s):
        return False
    return s[-1] not in ">+~,"


def _css_brackets_and_quotes_ok(s: str) -> bool:
    quote: str | None = None
    square = 0
    paren = 0
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if quote is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "[":
            square += 1
        elif ch == "]":
            square -= 1
            if square < 0:
                return False
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
            if paren < 0:
                return False
        i += 1
    return quote is None and square == 0 and paren == 0


def _defaults_from(raw: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str | bool]]:
    version = raw["version"]
    selectors = copy.deepcopy(raw["selectors"])
    patterns: dict[str, str | bool] = dict(raw.get("patterns") or PATTERN_SLOT_DEFAULT)
    return version, selectors, patterns


def _rollback(defaults: dict[str, Any], detail: str) -> ParsedSelectorsConfig:
    version, selectors, patterns = _defaults_from(defaults)
    return ParsedSelectorsConfig(
        version=version,
        selectors=selectors,
        patterns=patterns,
        issues=(ConfigIssue("config_schema_invalid", detail),),
        schema_valid=False,
        used_defaults=True,
    )


def _parse_string_field(value: object, *, path: str, issues: list[ConfigIssue]) -> str | None:
    if not isinstance(value, str) or not is_valid_css_selector(value):
        issues.append(ConfigIssue("invalid_selector", path))
        return None
    return value.strip()


def _parse_list_field(value: object, *, path: str, issues: list[ConfigIssue]) -> list[str] | None:
    if not isinstance(value, list):
        issues.append(ConfigIssue("invalid_selector", path))
        return None
    if len(value) > MAX_ARRAY_LEN:
        issues.append(ConfigIssue("invalid_selector", f"{path}: массив длиннее {MAX_ARRAY_LEN}"))
        value = value[:MAX_ARRAY_LEN]
    parsed: list[str] = []
    for i, item in enumerate(value):
        item_path = f"{path}[{i}]"
        if not isinstance(item, str) or not is_valid_css_selector(item):
            issues.append(ConfigIssue("invalid_selector", item_path))
            continue
        parsed.append(item.strip())
    return parsed if parsed else None


def _overlay_group(
    kind: str | dict[str, str],
    incoming: object,
    current: object,
    *,
    path: str,
    issues: list[ConfigIssue],
) -> object:
    if kind == "list":
        parsed = _parse_list_field(incoming, path=path, issues=issues)
        return parsed if parsed is not None else current
    if not isinstance(kind, dict):
        return current
    if not isinstance(incoming, dict):
        issues.append(ConfigIssue("invalid_selector", path))
        return current
    if not isinstance(current, dict):
        return current
    out = copy.deepcopy(current)
    for key, raw_val in incoming.items():
        key_kind = kind.get(key)
        key_path = f"{path}.{key}"
        if key_kind is None:
            issues.append(ConfigIssue("unknown_selector_key", key_path))
            continue
        if key_kind == "str":
            parsed_s = _parse_string_field(raw_val, path=key_path, issues=issues)
            if parsed_s is not None:
                out[key] = parsed_s
        else:
            parsed_l = _parse_list_field(raw_val, path=key_path, issues=issues)
            if parsed_l is not None:
                out[key] = parsed_l
    return out


def _overlay_patterns(
    incoming: object,
    current: dict[str, str | bool],
    issues: list[ConfigIssue],
) -> dict[str, str | bool]:
    if not isinstance(incoming, dict):
        issues.append(ConfigIssue("invalid_selector", "patterns"))
        return current
    out = dict(current)
    allowed_slots = set(PATTERN_SLOTS)
    for slot, raw_val in incoming.items():
        path = f"patterns.{slot}"
        if slot not in allowed_slots:
            issues.append(ConfigIssue("unknown_selector_key", path))
            continue
        if isinstance(raw_val, bool):
            out[slot] = raw_val
            continue
        if isinstance(raw_val, str) and raw_val in PATTERN_NAMES:
            out[slot] = raw_val
            continue
        issues.append(ConfigIssue("invalid_selector", path))
    return out


def parse_selectors_config(
    raw: object, *, defaults: dict[str, Any] | None = None
) -> ParsedSelectorsConfig:
    """Разобрать сырой конфиг: неизвестное и битое отбрасывается, схема целиком — откат.

    Та же функция применяется к ответу API и к кэшу (битый storage не заклинивает парсер).
    """
    base = defaults if defaults is not None else load_repo_hh_selectors()
    if not isinstance(raw, dict):
        return _rollback(base, "не объект")
    if not _valid_version(raw.get("version")):
        return _rollback(base, "version: целое больше нуля")

    selectors_in = raw.get("selectors", {})
    if selectors_in is None:
        selectors_in = {}
    if not isinstance(selectors_in, dict):
        return _rollback(base, "selectors: не объект")

    patterns_in = raw.get("patterns", {})
    if patterns_in is None:
        patterns_in = {}
    if patterns_in != {} and not isinstance(patterns_in, dict):
        return _rollback(base, "patterns: не объект")

    issues: list[ConfigIssue] = []
    for extra in raw:
        if extra not in _ENVELOPE_KEYS:
            issues.append(ConfigIssue("unknown_selector_key", extra))

    version, selectors, patterns = _defaults_from(base)
    version = raw["version"]

    for group, group_val in selectors_in.items():
        kind = SELECTOR_VALUE_KIND.get(group)
        if kind is None:
            issues.append(ConfigIssue("unknown_selector_key", f"selectors.{group}"))
            continue
        selectors[group] = _overlay_group(
            kind,
            group_val,
            selectors[group],
            path=f"selectors.{group}",
            issues=issues,
        )

    if patterns_in:
        patterns = _overlay_patterns(patterns_in, patterns, issues)

    return ParsedSelectorsConfig(
        version=version,
        selectors=selectors,
        patterns=patterns,
        issues=tuple(issues),
        schema_valid=True,
        used_defaults=False,
    )


def dump_selectors_config_json(parsed: ParsedSelectorsConfig) -> str:
    """Аудируемый dump (0.6): то, что реально применится, без служебных полей."""
    payload = {
        "version": parsed.version,
        "selectors": parsed.selectors,
        "patterns": parsed.patterns,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


__all__ = [
    "MAX_ARRAY_LEN",
    "MAX_SELECTOR_LEN",
    "PATTERN_NAMES",
    "PATTERN_SLOT_DEFAULT",
    "PATTERN_SLOTS",
    "PG_OVERRIDE_TTL_S",
    "SELECTOR_GROUPS",
    "SELECTOR_VALUE_KIND",
    "SOURCE_HH",
    "ConfigIssue",
    "HhSelectorsConfig",
    "ParsedSelectorsConfig",
    "PgSelectorOverride",
    "dump_selectors_config_json",
    "get_hh_selectors",
    "is_config_fetch_allowed",
    "is_valid_css_selector",
    "load_repo_hh_selectors",
    "looks_like_regex",
    "parse_selectors_config",
    "reset_parser_config_cache",
    "resolve_hh_selectors",
]
