"""Рантайм-конфиг расширения: флаги/тюнинг/селекторы отклика — правятся с сервера без zip.

Мотив (2026-08-28): пользователей раздражают частые пересборки расширения. MV3 запрещает
исполнять код не из пакета, поэтому плюмбинг service worker'а всё равно приезжает пересборкой —
но всё, что *реально* дёргается (селекторы `data-qa` площадок, задержки анти-детекта, дневные
темпы, аварийный стоп) — это данные, не код. Их держим здесь, по образцу
`parser_config.py` (репозиторный дефолт + горячий оверрайд в `app_settings`, жёсткая валидация,
битый оверрайд → дефолт, не 500).

Контракт: сервер меняет *значения*, не *структуру*. Неизвестный ключ отбрасывается; булевы
флаги — только `bool`; числа тюнинга — клампятся в безопасный диапазон; селекторы проходят тот
же CSS-валидатор, что у парсера (регекс с сервера запрещён). Раздел, целиком не прошедший
валидацию, откатывается на репозиторный дефолт — расширение никогда не остаётся без рабочего
конфига.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.domains.opportunities.parser_config import is_valid_css_selector
from core.platform.db.pool import Executor
from core.platform.observability import event
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "extension_runtime_config"
PG_OVERRIDE_TTL_S = 60.0

_REPO_JSON = Path(__file__).resolve().parent / "sources" / "extension_runtime_config.json"

# Флаги — только эти ключи, только bool. Дефолт True = «глобального оверрайда нет, решает
# per-account конфиг»; False = аварийный стоп для всех сразу.
FLAG_KEYS: tuple[str, ...] = (
    "auto_apply_enabled",
    "auto_apply_hh_enabled",
    "auto_apply_getmatch_enabled",
    "auto_apply_habr_enabled",
    "anketa_resume_enabled",
    "discovery_enabled",
)

# Числа тюнинга: ключ → (min, max). Пара [min, max] задаётся как двухэлементный список, где
# каждый элемент клампится своим диапазоном и min ≤ max принудительно.
# Скаляры, которым дробное значение осмысленно (период chrome.alarms в минутах): не округляем
# до целого при клампе. `discovery_tick_minutes=0.5` → alarm раз в 30с (минимум chrome.alarms
# c Chrome 120; распакованному расширению и вовсе без ограничения) → интервал автопросмотра
# 30–90с вместе с `discovery_delay_ms`.
_TUNING_FRACTIONAL: frozenset[str] = frozenset({"discovery_tick_minutes"})

_TUNING_SCALAR: dict[str, tuple[float, float]] = {
    "auto_apply_tick_minutes": (1, 60),
    "discovery_tick_minutes": (0.5, 60),
    "max_real_applications_per_tick": (1, 10),
    # Жёсткий пол паузы между РЕАЛЬНЫМИ откликами одной площадки: раннер спит минимум столько
    # между `sendAutoApplyRun` в боевом режиме и в досыле подтверждённых
    # (`runAnketaResumeCycle`). Не опускается ниже 2 минут даже оверрайдом из админки
    # (owner's spec 2026-08-28: не чаще 1 автоотклика в 2 минуты для всех площадок).
    "auto_apply_min_real_interval_ms": (120_000, 600_000),
    "tab_load_timeout_ms": (5_000, 120_000),
    "post_load_settle_ms": (0, 10_000),
    "vacancy_ready_timeout_ms": (10_000, 180_000),
    "apply_confirm_timeout_ms": (2_000, 60_000),
}
_TUNING_RANGE: dict[str, tuple[float, float]] = {
    # [нижняя, верхняя] границы паузы между автооткликами. Дефолт [2мин, 5мин] (owner's spec
    # 2026-08-28); жёсткий пол «не чаще 1 в 2 мин» держит `auto_apply_min_real_interval_ms`.
    "auto_apply_delay_ms": (1_000, 600_000),
    "apply_reading_delay_ms": (0, 60_000),
    # Темп автопросмотра: `discovery_tick_minutes` задаёт период alarm (нижняя граница), раннер
    # добирает рандом до верхней. Дефолт [30с, 90с] (owner's spec 2026-09; было [1мин, 2мин]).
    # Нижняя граница дефолта ДОЛЖНА совпадать с `discovery_tick_minutes`×60000, иначе интервал
    # уедет: alarm тикает по своему периоду, а джиттер отсчитывается от `discovery_delay_ms[0]`.
    "discovery_delay_ms": (30_000, 600_000),
}

# Селекторы отклика: площадка → набор допустимых ключей.
_APPLY_SELECTOR_KEYS: dict[str, frozenset[str]] = {
    "hh": frozenset(
        {
            "responseLinkTop",
            "responseLinkBottom",
            "alreadyApplied",
            "attachLetterButton",
            "letterTextarea",
            "letterSubmit",
            "anketaQuestionBody",
            "anketaQuestionText",
            "anketaSubmit",
        }
    ),
    "getmatch": frozenset({"form", "coverLetterTextarea"}),
}

# Селекторы разбора карточки вакансии. hh живёт в зрелом `hh_selectors.json` (своя типизированная
# валидация) — сюда не дублируем. getmatch горячего пути не имел вовсе, добавляем здесь.
_PARSE_SELECTOR_KEYS: dict[str, frozenset[str]] = {
    "getmatch": frozenset(
        {
            "header",
            "title",
            "companyLink",
            "salary",
            "locations",
            "specs",
            "stack",
            "description",
            "applyButton",
            "archived",
            "appliedBanner",
        }
    ),
}

# Текстовые сигналы состояния страницы (площадка сменила формулировку — раньше это была
# пересборка ради одного слова). Матчинг — plain `.includes()` по нормализованному нижнему
# регистру, поэтому регекс не нужен и ReDoS невозможен: только массив коротких подстрок.
# habr не участвует: его состояния (is_archived, отклики) приходят структурно из SSR-JSON /
# XHR-перехватчика, а не текстом со страницы — конфигурировать нечего.
_TEXT_SIGNAL_KEYS: dict[str, frozenset[str]] = {
    "hh": frozenset({"already_applied"}),
    "getmatch": frozenset({"already_applied", "archived", "letter_required"}),
}
_TEXT_SIGNAL_MIN_LEN = 2
_TEXT_SIGNAL_MAX_LEN = 200
_TEXT_SIGNAL_MAX_ITEMS = 20

_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "flags",
        "tuning",
        "apply_selectors",
        "parse_selectors",
        "text_signals",
        "updated_at",
        "origin",
    }
)


@dataclass(frozen=True)
class ExtensionRuntimeConfig:
    version: int
    updated_at: datetime
    origin: str  # "db_override" | "repo"
    flags: dict[str, bool]
    tuning: dict[str, Any]
    apply_selectors: dict[str, dict[str, str]]
    parse_selectors: dict[str, dict[str, str]] = field(default_factory=dict)
    text_signals: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    issues: tuple[str, ...] = field(default=())


@lru_cache(maxsize=1)
def _load_repo_raw() -> dict[str, Any]:
    return json.loads(_REPO_JSON.read_text(encoding="utf-8"))


def load_repo_config() -> dict[str, Any]:
    return copy.deepcopy(_load_repo_raw())


def _repo_updated_at() -> datetime:
    return datetime.fromtimestamp(_REPO_JSON.stat().st_mtime, tz=UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _merge_flags(incoming: object, base: dict[str, bool], issues: list[str]) -> dict[str, bool]:
    out = dict(base)
    if not isinstance(incoming, dict):
        if incoming not in (None, {}):
            issues.append("flags: не объект")
        return out
    for key, raw in incoming.items():
        if key not in FLAG_KEYS:
            issues.append(f"flags.{key}: неизвестный флаг")
            continue
        if not isinstance(raw, bool):
            issues.append(f"flags.{key}: не bool")
            continue
        out[key] = raw
    return out


def _merge_tuning(incoming: object, base: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    if not isinstance(incoming, dict):
        if incoming not in (None, {}):
            issues.append("tuning: не объект")
        return out
    for key, raw in incoming.items():
        if key in _TUNING_SCALAR:
            lo, hi = _TUNING_SCALAR[key]
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                issues.append(f"tuning.{key}: не число")
                continue
            clamped = _clamp(float(raw), lo, hi)
            out[key] = round(clamped, 2) if key in _TUNING_FRACTIONAL else int(clamped)
        elif key in _TUNING_RANGE:
            lo, hi = _TUNING_RANGE[key]
            if (
                not isinstance(raw, list)
                or len(raw) != 2
                or any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in raw)
            ):
                issues.append(f"tuning.{key}: ожидается [min, max] из двух чисел")
                continue
            a, b = int(_clamp(float(raw[0]), lo, hi)), int(_clamp(float(raw[1]), lo, hi))
            out[key] = [min(a, b), max(a, b)]
        else:
            issues.append(f"tuning.{key}: неизвестный ключ")
    return out


def _merge_selector_group(
    incoming: object,
    base: dict[str, dict[str, str]],
    allowed_by_platform: dict[str, frozenset[str]],
    section: str,
    issues: list[str],
) -> dict[str, dict[str, str]]:
    """Оверлей CSS-селекторов площадок (apply_selectors / parse_selectors) — тот же контракт."""
    out = copy.deepcopy(base)
    if not isinstance(incoming, dict):
        if incoming not in (None, {}):
            issues.append(f"{section}: не объект")
        return out
    for platform, group in incoming.items():
        allowed = allowed_by_platform.get(platform)
        if allowed is None:
            issues.append(f"{section}.{platform}: неизвестная площадка")
            continue
        if not isinstance(group, dict):
            issues.append(f"{section}.{platform}: не объект")
            continue
        for key, raw in group.items():
            path = f"{section}.{platform}.{key}"
            if key not in allowed:
                issues.append(f"{path}: неизвестный ключ")
                continue
            if not isinstance(raw, str) or not is_valid_css_selector(raw):
                issues.append(f"{path}: не валидный CSS-селектор")
                continue
            out.setdefault(platform, {})[key] = raw.strip()
    return out


def _merge_text_signals(
    incoming: object, base: dict[str, dict[str, list[str]]], issues: list[str]
) -> dict[str, dict[str, list[str]]]:
    """Оверлей списков подстрок-сигналов состояния страницы. Только массивы коротких строк —
    нормализуем в нижний регистр, регекс/ReDoS невозможен."""
    out = copy.deepcopy(base)
    if not isinstance(incoming, dict):
        if incoming not in (None, {}):
            issues.append("text_signals: не объект")
        return out
    for platform, group in incoming.items():
        allowed = _TEXT_SIGNAL_KEYS.get(platform)
        if allowed is None:
            issues.append(f"text_signals.{platform}: неизвестная площадка")
            continue
        if not isinstance(group, dict):
            issues.append(f"text_signals.{platform}: не объект")
            continue
        for key, raw in group.items():
            path = f"text_signals.{platform}.{key}"
            if key not in allowed:
                issues.append(f"{path}: неизвестный ключ")
                continue
            if not isinstance(raw, list):
                issues.append(f"{path}: ожидается список строк")
                continue
            # Объединяем с дефолтом, не заменяем: площадка часто показывает и старую, и новую
            # формулировку во время раскатки — админ добавляет новую подстроку, старые остаются.
            merged: list[str] = list(out.get(platform, {}).get(key, []))
            for item in raw[:_TEXT_SIGNAL_MAX_ITEMS]:
                if not isinstance(item, str):
                    issues.append(f"{path}: элемент не строка")
                    continue
                norm = " ".join(item.split()).strip().lower()
                if not (_TEXT_SIGNAL_MIN_LEN <= len(norm) <= _TEXT_SIGNAL_MAX_LEN):
                    issues.append(
                        f"{path}: строка вне длины {_TEXT_SIGNAL_MIN_LEN}..{_TEXT_SIGNAL_MAX_LEN}"
                    )
                    continue
                if norm not in merged:
                    merged.append(norm)
            out.setdefault(platform, {})[key] = merged[:_TEXT_SIGNAL_MAX_ITEMS]
    return out


def _valid_version(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def resolve_extension_runtime_config(
    override: Any | None, override_updated_at: datetime | None
) -> ExtensionRuntimeConfig:
    """Оверрайд из PG (уже прочитанный) или None → валидный конфиг. Без I/O."""
    repo = load_repo_config()
    base_flags: dict[str, bool] = dict(repo.get("flags") or {})
    base_tuning: dict[str, Any] = dict(repo.get("tuning") or {})
    base_apply: dict[str, dict[str, str]] = dict(repo.get("apply_selectors") or {})
    base_parse: dict[str, dict[str, str]] = dict(repo.get("parse_selectors") or {})
    base_signals: dict[str, dict[str, list[str]]] = dict(repo.get("text_signals") or {})

    if not isinstance(override, dict) or not override:
        return ExtensionRuntimeConfig(
            version=int(repo["version"]),
            updated_at=_repo_updated_at(),
            origin="repo",
            flags=base_flags,
            tuning=base_tuning,
            apply_selectors=base_apply,
            parse_selectors=base_parse,
            text_signals=base_signals,
        )

    issues: list[str] = []
    raw_version = override.get("version")
    if _valid_version(raw_version):
        version = int(raw_version)  # type: ignore[arg-type]  # _valid_version гарантирует int
    else:
        version = int(repo["version"])
        issues.append("version: целое больше нуля")
    for extra in override:
        if extra not in _ENVELOPE_KEYS:
            issues.append(f"{extra}: лишний ключ конверта")

    flags = _merge_flags(override.get("flags"), base_flags, issues)
    tuning = _merge_tuning(override.get("tuning"), base_tuning, issues)
    apply_sel = _merge_selector_group(
        override.get("apply_selectors"), base_apply, _APPLY_SELECTOR_KEYS, "apply_selectors", issues
    )
    parse_sel = _merge_selector_group(
        override.get("parse_selectors"), base_parse, _PARSE_SELECTOR_KEYS, "parse_selectors", issues
    )
    signals = _merge_text_signals(override.get("text_signals"), base_signals, issues)

    if issues:
        event(
            logger,
            "РАСШИРЕНИЕ",
            "рантайм-конфиг: оверрайд с замечаниями (%d), применяю прошедшее валидацию: %s",
            len(issues),
            "; ".join(issues[:5]),
            level=logging.WARNING,
            event="extension_runtime_config_issues",
            issue_count=len(issues),
        )

    return ExtensionRuntimeConfig(
        version=version,
        updated_at=_as_utc(override_updated_at) if override_updated_at else _repo_updated_at(),
        origin="db_override",
        flags=flags,
        tuning=tuning,
        apply_selectors=apply_sel,
        parse_selectors=parse_sel,
        text_signals=signals,
        issues=tuple(issues),
    )


_cache: tuple[float, ExtensionRuntimeConfig] | None = None


def reset_extension_runtime_config_cache() -> None:
    """Сброс TTL-кэша — для тестов и сразу после записи оверрайда из админки."""
    global _cache
    _cache = None


async def _fetch_override(*, db: Executor | None = None) -> tuple[Any | None, datetime | None]:
    raw = await get_setting(SETTINGS_KEY, default=None, account_id=None, db=db)
    if raw is None:
        return None, None
    updated_at: datetime | None = None
    if isinstance(raw, dict):
        stamp = raw.get("updated_at")
        if isinstance(stamp, str):
            try:
                updated_at = datetime.fromisoformat(stamp)
            except ValueError:
                updated_at = None
    return raw, updated_at


async def get_extension_runtime_config(*, db: Executor | None = None) -> ExtensionRuntimeConfig:
    """Оверрайд из `app_settings` (TTL 60 с), иначе дефолт из репозитория."""
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached is not None and (now - cached[0]) < PG_OVERRIDE_TTL_S:
        return cached[1]
    override, updated_at = await _fetch_override(db=db)
    cfg = resolve_extension_runtime_config(override, updated_at)
    _cache = (now, cfg)
    return cfg


async def set_extension_runtime_config_override(
    payload: dict[str, Any], *, db: Executor | None = None
) -> ExtensionRuntimeConfig:
    """Записать оверрайд (уже провалидированный вызывающей стороной как dict-конверт) в
    `app_settings`, поднять `version` монотонно, сбросить кэш и вернуть новый merged-конфиг."""
    current = await get_extension_runtime_config(db=db)
    stored = {
        "version": current.version + 1,
        "flags": payload.get("flags", {}),
        "tuning": payload.get("tuning", {}),
        "apply_selectors": payload.get("apply_selectors", {}),
        "parse_selectors": payload.get("parse_selectors", {}),
        "text_signals": payload.get("text_signals", {}),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    await set_setting(SETTINGS_KEY, stored, account_id=None, db=db)
    reset_extension_runtime_config_cache()
    return await get_extension_runtime_config(db=db)


__all__ = [
    "FLAG_KEYS",
    "SETTINGS_KEY",
    "ExtensionRuntimeConfig",
    "get_extension_runtime_config",
    "load_repo_config",
    "reset_extension_runtime_config_cache",
    "resolve_extension_runtime_config",
    "set_extension_runtime_config_override",
]
