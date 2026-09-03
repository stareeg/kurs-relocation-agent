"""LLM-оценка помесячного эквивалента премии оффера, когда её нельзя посчитать детерминированно
(KPI/перфоманс-ревью — не плоский процент от периода).
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from core.config import get_settings
from core.domains.offers.bonus import offer_bonus_types
from core.domains.offers.models import OfferRecord
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_prompt() -> str:
    from pathlib import Path

    from core.domains.offers.llm import BONUS_ESTIMATE

    return Path(BONUS_ESTIMATE).read_text(encoding="utf-8")


def _monthly_base(offer: OfferRecord) -> int | None:
    if not offer.base_salary:
        return None
    if offer.base_salary_period == "year":
        return offer.base_salary // 12
    return offer.base_salary


def deterministic_bonus_monthly_equiv(offer: OfferRecord) -> int | None:
    """Годовая/квартальная как % от периода (или легаси-сумма). None — нужна LLM или считать нечего."""
    types = offer_bonus_types(offer.bonus_types, offer.bonus_type)
    if not types:
        return None
    monthly = _monthly_base(offer)
    total = 0
    has_det = False

    if "annual" in types:
        if offer.annual_bonus_pct and monthly:
            total += monthly * offer.annual_bonus_pct // 100
            has_det = True
        elif offer.bonus_amount and "quarterly" not in types:
            total += offer.bonus_amount // 12
            has_det = True

    if "quarterly" in types:
        if offer.quarterly_bonus_pct and monthly:
            total += monthly * offer.quarterly_bonus_pct // 100
            has_det = True
        elif offer.bonus_amount and "annual" not in types:
            total += offer.bonus_amount // 3
            has_det = True

    # KPI нельзя разложить без текста условий — даже если годовая уже посчитана.
    if "kpi" in types:
        return None
    return total if has_det else None


async def estimate_bonus_monthly_equiv(offer: OfferRecord) -> int | None:
    """LLM-оценка для случаев, где детерминированная формула не годится (KPI и т.п.)."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    system = _load_prompt()
    user = json.dumps(
        {
            "bonus_types": offer_bonus_types(offer.bonus_types, offer.bonus_type),
            "bonus_type": offer.bonus_type,
            "bonus": offer.bonus,
            "bonus_amount": offer.bonus_amount,
            "annual_bonus_pct": offer.annual_bonus_pct,
            "quarterly_bonus_pct": offer.quarterly_bonus_pct,
            "base_salary": offer.base_salary,
            "base_salary_period": offer.base_salary_period,
            "base_salary_currency": offer.base_salary_currency,
            "notes": offer.notes,
        },
        ensure_ascii=False,
    )
    raw = await ports.llm().complete(
        "offer_bonus_estimate",
        system=system,
        user=user,
        temperature=0.1,
    )
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Offer bonus estimate: невалидный JSON — %s", raw[:200])
        return None
    value = data.get("bonus_monthly_equiv")
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


__all__ = ["deterministic_bonus_monthly_equiv", "estimate_bonus_monthly_equiv"]
