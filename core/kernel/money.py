"""Чистые функции нормализации зарплат: валюта/шкала/период.

Без I/O и без LLM. Источник — эвристики из `core.scoring.salary_*`.
"""

from __future__ import annotations

import re
from typing import Literal

SalaryPeriod = Literal["month", "year"]
TaxBasis = Literal["net", "gross"]

# Смешанная ставка НДФЛ 13–15%, ориентир для gross→net на рынке РФ.
GROSS_TO_NET_RATIO = 0.87

_ALLOWED_PERIODS: frozenset[str] = frozenset({"month", "year"})
_ALLOWED_TAX_BASIS: frozenset[str] = frozenset({"net", "gross"})

_NET_MARK = re.compile(r"на\s*руки|\bnet\b|нетто|после\s*налог|чист", re.IGNORECASE)
_GROSS_MARK = re.compile(
    r"\bgross\b|до\s*вычет|до\s*налог|грязн|на\s*бумаг|оклад\s*до", re.IGNORECASE
)


def round_step_for(amount: int) -> int:
    """Шаг округления от порядка суммы: 5к ниже 200к, иначе 10к."""
    return 5_000 if abs(amount) < 200_000 else 10_000


def round_salary(value: int, step: int | None = None) -> int:
    """Округлить сумму зарплаты до шага (не ниже самого шага)."""
    step = step if step is not None else round_step_for(value)
    return max(step, round(value / step) * step)


def gross_to_net(gross: int | None) -> int | None:
    """Gross → net (ориентир ×0.87) с округлением до шага рынка."""
    if gross is None:
        return None
    net = int(round(gross * GROSS_TO_NET_RATIO))
    step = round_step_for(net)
    return int(round(net / step) * step)


def detect_tax_basis(text: str | None) -> TaxBasis | None:
    """Шкала суммы по словам рядом с ней: «на руки» → net, «до вычета» → gross.

    `None` — в тексте про шкалу ничего не сказано. Различать «не сказано» и «net» обязательно:
    молчание нельзя трактовать как gross, иначе любая вилка без подписи автоматически
    падала бы на 13% (`parse_net_range` держит ту же конвенцию — unclear оставляем как есть).
    """
    raw = text or ""
    if not raw.strip():
        return None
    if _GROSS_MARK.search(raw) and not _NET_MARK.search(raw):
        return "gross"
    if _NET_MARK.search(raw):
        return "net"
    return None


def normalize_period(value: str | None, *, default: SalaryPeriod = "month") -> SalaryPeriod:
    """Привести период выплаты к `month` | `year`."""
    raw = str(value or default).strip().lower()
    if raw in _ALLOWED_PERIODS:
        return raw  # type: ignore[return-value]
    return default


def normalize_tax_basis(value: str | None, *, default: TaxBasis = "gross") -> TaxBasis:
    """Привести шкалу к `net` | `gross`."""
    raw = str(value or default).strip().lower()
    if raw in _ALLOWED_TAX_BASIS:
        return raw  # type: ignore[return-value]
    return default


def to_monthly(amount: int, period: str | None = "month") -> int:
    """Перевести сумму в месячный эквивалент (`year` → ÷12)."""
    normalized = normalize_period(period)
    if normalized == "year":
        return amount // 12
    return amount


def to_net(
    amount: int | None,
    *,
    tax_basis: str | None = "gross",
) -> int | None:
    """Привести сумму к net: gross конвертируется, net остаётся как есть."""
    if amount is None:
        return None
    basis = normalize_tax_basis(tax_basis)
    if basis == "gross":
        return gross_to_net(amount)
    return amount


__all__ = [
    "GROSS_TO_NET_RATIO",
    "SalaryPeriod",
    "TaxBasis",
    "detect_tax_basis",
    "gross_to_net",
    "normalize_period",
    "normalize_tax_basis",
    "round_salary",
    "round_step_for",
    "to_monthly",
    "to_net",
]
