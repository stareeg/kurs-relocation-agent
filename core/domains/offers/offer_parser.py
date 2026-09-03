"""LLM-извлечение структуры оффера из текста письма/HR-сообщения (порт из backend, S8).

Транспорт — порт `kernel.ports.llm().complete` (тир — из декларации фичи);
схемы — `core.domains.offers.models`.
Без БД: чистый LLM + парсинг. Ошибки LLM — core `LlmError`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import get_settings
from core.domains.offers.bonus import (
    normalize_bonus_types,
    primary_bonus_type,
    snap_bonus_pct,
)
from core.domains.offers.models import OfferRecord, WorkFormat
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.ids import VacancyId
from core.platform.observability import event

logger = logging.getLogger(__name__)

_MSK = timezone(timedelta(hours=3))
MAX_TEXT_CHARS = 24_000
_ALLOWED_FORMATS: set[str] = {"remote", "hybrid", "office", "currency", "unknown"}
_ALLOWED_PERIODS: set[str] = {"month", "year"}
_ALLOWED_TAX_BASIS: set[str] = {"gross", "net"}
_ALLOWED_CONTRACT_TYPES: set[str] = {"employment", "gph", "ip", "self_employed"}


_SYSTEM_PROMPT_TEMPLATE = """\
Ты — ассистент по поиску работы. Извлекаешь структуру оффера из текста письма/сообщения HR
для конкретной вакансии.

Сегодня: {today}

ВАЖНО:
- Не выдумывай числа. Если KPI описан словами — пиши условия в bonus, bonus_amount оставь null.
- Если ЗП — годовая, base_salary_period="year". Если месячная — "month" (по умолчанию).
- В рублях — base_salary_currency="RUB", иначе ISO-код ("USD", "EUR").
- deadline — когда HR ждёт ответа. Если HR не указал — null.
- start_date — желаемая дата выхода. null если неизвестна.
- Если work_format="hybrid" и в письме явно названо число дней в офисе («3 дня в офисе»,
  «2/3 гибрид» — второе число, «офис по вторникам-средам» — посчитать дни недели) —
  office_days_per_week=это число. Не выдумывай число, если в письме его нет — тогда null.
  Для remote/office/unknown — всегда null.
- base_salary_tax_basis — по словам письма: «на руки»/«net» → "net", «gross»/«до вычета
  налогов» или не указано → "gross" (это дефолт).
- bonus_types — массив, можно несколько сразу: годовая → "annual", квартальная → "quarterly",
  KPI/перфоманс-ревью → "kpi", welcome/sign-on → "welcome", опционы/акции/RSU → "equity".
  Премия не упомянута → [].
- annual_bonus_pct / quarterly_bonus_pct — целое 5..150, если в письме назван процент
  годовой/квартальной премии от периода (год / квартал). Иначе null. Не переводи сумму в %.
- contract_type — почти всегда в письме HR явно не сказано, дефолт "employment". Не выдумывай,
  проставляй "gph"/"ip"/"self_employed" только если формат договора явно назван.
- location_country — страна работодателя/выплаты, заполняй только если из письма явно понятно,
  что формат работы валютный/зарубежный (например work_format="currency"). Иначе — пустая строка.
- Никаких ` ```json `, никакого текста до/после JSON.

Верни ТОЛЬКО валидный JSON:
{{
  "company": str,
  "position": str,
  "base_salary": int|null,
  "base_salary_currency": "RUB"|"USD"|"EUR"|...,
  "base_salary_period": "month"|"year",
  "base_salary_tax_basis": "gross"|"net",
  "bonus": str,
  "bonus_amount": int|null,
  "bonus_types": ["annual"|"quarterly"|"kpi"|"welcome"|"equity"],
  "annual_bonus_pct": int|null,
  "quarterly_bonus_pct": int|null,
  "equity": str,
  "signon": int|null,
  "vacation_days": int|null,
  "notice_period": str,
  "start_date": "ISO 8601 +03:00"|null,
  "deadline": "ISO 8601 +03:00"|null,
  "relocation_package": str,
  "contract_type": "employment"|"gph"|"ip"|"self_employed",
  "work_format": "remote"|"hybrid"|"office"|"currency"|"unknown",
  "office_days_per_week": int|null,
  "location": str,
  "location_country": str,
  "summary": str
}}
"""


def _today_str() -> str:
    return datetime.now(tz=_MSK).strftime("%Y-%m-%d (%A, MSK)")


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = _strip_fences(raw)
    candidates = [text]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group())
        candidates.append(re.sub(r",\s*}", "}", match.group()))
        candidates.append(re.sub(r",\s*]", "]", match.group()))
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise LlmError("Offer parser: невалидный JSON в ответе")


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d]", "", value)
        if cleaned:
            try:
                return int(cleaned)
            except ValueError:
                return None
    return None


def _coerce_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_MSK)
    return dt


def _coerce_format(value: Any) -> WorkFormat:
    raw = str(value or "unknown").strip().lower()
    if raw in _ALLOWED_FORMATS:
        return raw  # type: ignore[return-value]
    return "unknown"


def _coerce_period(value: Any) -> str:
    raw = str(value or "month").strip().lower()
    if raw in _ALLOWED_PERIODS:
        return raw
    return "month"


def _coerce_office_days(value: Any, *, work_format: WorkFormat) -> int | None:
    if work_format != "hybrid":
        return None
    days = _coerce_int(value)
    if days is None or days > 7:
        return None
    return days


def _coerce_tax_basis(value: Any) -> str:
    raw = str(value or "gross").strip().lower()
    return raw if raw in _ALLOWED_TAX_BASIS else "gross"


def _coerce_bonus_types(parsed: dict[str, Any]) -> list[str]:
    raw = parsed.get("bonus_types")
    if raw in (None, "", []):
        raw = parsed.get("bonus_type")
    types = normalize_bonus_types(raw)
    if parsed.get("signon"):
        types = normalize_bonus_types([*types, "welcome"])
    if str(parsed.get("equity") or "").strip():
        types = normalize_bonus_types([*types, "equity"])
    return types


def _coerce_contract_type(value: Any) -> str:
    raw = str(value or "employment").strip().lower()
    return raw if raw in _ALLOWED_CONTRACT_TYPES else "employment"


def _build_record(
    parsed: dict[str, Any],
    *,
    vacancy_id: str,
    raw_text: str,
    fallback_company: str = "",
    fallback_position: str = "",
) -> OfferRecord:
    company = (parsed.get("company") or fallback_company or "").strip()
    position = (parsed.get("position") or fallback_position or "").strip()
    work_format = _coerce_format(parsed.get("work_format"))

    types = _coerce_bonus_types(parsed)
    equity = str(parsed.get("equity") or "").strip()[:1000]
    signon = _coerce_int(parsed.get("signon"))

    return OfferRecord(
        vacancy_id=VacancyId(vacancy_id),
        company=company,
        position=position,
        base_salary=_coerce_int(parsed.get("base_salary")),
        base_salary_currency=str(parsed.get("base_salary_currency") or "RUB").strip().upper()
        or "RUB",
        base_salary_period=_coerce_period(parsed.get("base_salary_period")),  # type: ignore[arg-type]
        bonus=str(parsed.get("bonus") or "").strip()[:1000],
        bonus_amount=_coerce_int(parsed.get("bonus_amount")),
        equity=equity,
        signon=signon,
        vacation_days=_coerce_int(parsed.get("vacation_days")),
        notice_period=str(parsed.get("notice_period") or "").strip()[:200],
        start_date=_coerce_dt(parsed.get("start_date")),
        deadline=_coerce_dt(parsed.get("deadline")),
        relocation_package=str(parsed.get("relocation_package") or "").strip()[:1000],
        work_format=work_format,
        office_days_per_week=_coerce_office_days(
            parsed.get("office_days_per_week"), work_format=work_format
        ),
        location=str(parsed.get("location") or "").strip()[:200],
        base_salary_tax_basis=_coerce_tax_basis(parsed.get("base_salary_tax_basis")),  # type: ignore[arg-type]
        bonus_types=types,  # type: ignore[arg-type]
        bonus_type=primary_bonus_type(types),  # type: ignore[arg-type]
        annual_bonus_pct=snap_bonus_pct(_coerce_int(parsed.get("annual_bonus_pct"))),
        quarterly_bonus_pct=snap_bonus_pct(_coerce_int(parsed.get("quarterly_bonus_pct"))),
        contract_type=_coerce_contract_type(parsed.get("contract_type")),  # type: ignore[arg-type]
        location_country=str(parsed.get("location_country") or "").strip()[:200],
        notes=str(parsed.get("summary") or "").strip()[:2000],
        raw_text=raw_text[:MAX_TEXT_CHARS],
        status="thinking",
    )


async def parse_offer_text(
    text: str,
    *,
    vacancy_id: str,
    fallback_company: str = "",
    fallback_position: str = "",
) -> OfferRecord:
    """Извлечь структуру оффера из произвольного текста.

    Поднимает LlmError при сбоях LLM, ValueError при пустом тексте.
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    stripped = text.strip()
    if len(stripped) < 20:
        raise ValueError("Текст оффера слишком короткий")
    if len(stripped) > MAX_TEXT_CHARS:
        stripped = stripped[: MAX_TEXT_CHARS - 20] + "\n[…обрезано]"

    system = _SYSTEM_PROMPT_TEMPLATE.format(today=_today_str())
    raw = await ports.llm().complete(
        "offer_parse",
        system=system,
        user=stripped,
        temperature=0.1,
    )
    try:
        parsed = _parse_llm_json(raw)
    except LlmError:
        logger.warning("Offer parse: невалидный JSON ответ — %s", raw[:300])
        raise

    record = _build_record(
        parsed,
        vacancy_id=vacancy_id,
        raw_text=stripped,
        fallback_company=fallback_company,
        fallback_position=fallback_position,
    )
    fields_found = sum(1 for v in parsed.values() if v not in (None, "", []))
    event(
        logger,
        "LLM",
        "offer_parse: распознано %d полей из %d",
        fields_found,
        len(parsed),
        vacancy_id=vacancy_id,
        fields_found=fields_found,
        fields_total=len(parsed),
        has_base_salary=record.base_salary is not None,
    )
    return record


__all__ = ["parse_offer_text", "MAX_TEXT_CHARS"]
