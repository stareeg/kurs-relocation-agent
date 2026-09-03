"""Типы премии оффера: мультивыбор + шкала процентов годовой/квартальной.

`bonus_type` (одно значение) остаётся денормализованным primary — его читают старые
пути и CHECK в БД; источник истины — `bonus_types`.
"""

from __future__ import annotations

from typing import Any, Literal

BonusKind = Literal["annual", "quarterly", "kpi", "welcome", "equity"]
BonusType = Literal["none", "annual", "quarterly", "kpi", "welcome", "equity"]

BONUS_KINDS: tuple[BonusKind, ...] = ("annual", "quarterly", "kpi", "welcome", "equity")
BONUS_KIND_SET: frozenset[str] = frozenset(BONUS_KINDS)

# Экспоненциальная шкала «% от периода» (год / квартал) — те же значения, что на слайдере.
BONUS_PCT_STEPS: tuple[int, ...] = (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150)

BONUS_KIND_RU: dict[str, str] = {
    "annual": "годовая",
    "quarterly": "квартальная",
    "kpi": "KPI",
    "welcome": "welcome",
    "equity": "акции",
}

# Welcome и акции не дают помесячного эквивалента сами по себе — их некуда делить на 12.
_NON_MONTHLY_KINDS: frozenset[str] = frozenset({"welcome", "equity"})


def normalize_bonus_types(value: Any) -> list[str]:
    """Канонический список без дублей и `none`. Порядок — как в `BONUS_KINDS`."""
    raw: list[str]
    if value is None or value == "":
        raw = []
    elif isinstance(value, str):
        raw = [] if value.strip().lower() in ("", "none") else [value]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(x) for x in value]
    else:
        raw = []
    present = {item.strip().lower() for item in raw if item and str(item).strip()}
    return [kind for kind in BONUS_KINDS if kind in present]


def primary_bonus_type(types: list[str]) -> str:
    """Одно значение для колонки `bonus_type`: первый канонический или `none`."""
    return types[0] if types else "none"


def snap_bonus_pct(value: int | None) -> int | None:
    """Ближайшая ступень шкалы; 0/пусто → None (поле не заполнено)."""
    if value is None or value <= 0:
        return None
    return min(BONUS_PCT_STEPS, key=lambda step: abs(step - value))


def apply_bonus_patch(updates: dict[str, Any]) -> dict[str, Any]:
    """Нормализация полей премии в PATCH/upsert: `bonus_types` побеждает `bonus_type`."""
    if "bonus_types" in updates:
        types = normalize_bonus_types(updates["bonus_types"])
        updates["bonus_types"] = types
        updates["bonus_type"] = primary_bonus_type(types)
    elif "bonus_type" in updates:
        types = normalize_bonus_types(updates["bonus_type"])
        updates["bonus_types"] = types
        updates["bonus_type"] = primary_bonus_type(types)
    if "annual_bonus_pct" in updates:
        updates["annual_bonus_pct"] = snap_bonus_pct(updates["annual_bonus_pct"])
    if "quarterly_bonus_pct" in updates:
        updates["quarterly_bonus_pct"] = snap_bonus_pct(updates["quarterly_bonus_pct"])
    return updates


def offer_bonus_types(bonus_types: Any, bonus_type: Any = "none") -> list[str]:
    """Прочитать набор типов: массив, иначе fallback на старое одиночное поле."""
    types = normalize_bonus_types(bonus_types)
    if types:
        return types
    return normalize_bonus_types(bonus_type)


def needs_monthly_bonus_estimate(types: list[str]) -> bool:
    """Есть ли что считать в помесячный эквивалент (не только welcome/акции)."""
    return bool(set(types) - _NON_MONTHLY_KINDS)


__all__ = [
    "BONUS_KINDS",
    "BONUS_KIND_RU",
    "BONUS_KIND_SET",
    "BONUS_PCT_STEPS",
    "BonusKind",
    "BonusType",
    "apply_bonus_patch",
    "needs_monthly_bonus_estimate",
    "normalize_bonus_types",
    "offer_bonus_types",
    "primary_bonus_type",
    "snap_bonus_pct",
]
