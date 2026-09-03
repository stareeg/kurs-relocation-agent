"""Обобщённое описание работодателя вместо его названия (фича `employer_descriptor`, Э4.1).

Деперсонализация исходящих писем/резюме под международный рынок (`anonymize.py`) заменяет
название текущей компании на обобщение «отрасль + масштаб + характер бизнеса» — не выдумку
(§2.8 dual_employment_and_contracting_2026.md: резюме не врёт, обобщение — это правда без имени).
Кэш по `(account_id, company_canonical)` — та же механика, что `intl_experience.py`: строится
один раз, переживает перегенерацию письма.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.domains.opportunities.companies.normalize import normalize_company_deterministic
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

FEATURE = "employer_descriptor"

# Фолбэк без LLM: используется, если модель дважды не смогла обобщить компанию без утечки
# имени (L-13: ремонт ≤1) — генерация письма не должна падать из-за одного капризного вызова.
_FALLBACK_RU = "текущее место работы"
_FALLBACK_EN = "current employer"


class EmployerDescriptor(BaseModel):
    """Обобщённое описание работодателя вместо его имени. Только правда, без выдумок."""

    descriptor_ru: str = Field(default="", max_length=120)
    descriptor_en: str = Field(default="", max_length=120)
    industry: str = ""
    size_band: Literal["startup", "midsize", "large", "enterprise", "unknown"] = "unknown"
    basis: list[str] = Field(default_factory=list)


def _fallback_descriptor(industry: str) -> EmployerDescriptor:
    ru = f"{_FALLBACK_RU} в сфере {industry}" if industry else _FALLBACK_RU
    en = f"{_FALLBACK_EN} in {industry}" if industry else _FALLBACK_EN
    return EmployerDescriptor(descriptor_ru=ru, descriptor_en=en, industry=industry)


def _leaks_company_name(descriptor: EmployerDescriptor, *names: str) -> bool:
    """Дескриптор не должен содержать имя компании/канон ни в одном языке (§2.8)."""
    haystacks = (descriptor.descriptor_ru.casefold(), descriptor.descriptor_en.casefold())
    for raw in names:
        needle = (raw or "").strip().casefold()
        if len(needle) < 3:
            continue
        if any(needle in hay for hay in haystacks):
            return True
    return False


def _descriptor_to_mapping(descriptor: EmployerDescriptor) -> dict[str, Any]:
    return descriptor.model_dump(mode="json")


async def load_descriptor(
    account_id: int,
    company_canonical: str,
    *,
    db: Executor | None = None,
) -> EmployerDescriptor | None:
    """Прочитать кэш без LLM. `None` — записи на этот канон ещё нет."""
    if not account_id or not company_canonical:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        "select descriptor from employer_descriptors "
        "where account_id = $1 and company_canonical = $2",
        account_id,
        company_canonical,
    )
    if row is None:
        return None
    try:
        return EmployerDescriptor.model_validate(row["descriptor"])
    except Exception:
        return None


async def _save_descriptor(
    account_id: int,
    company_canonical: str,
    descriptor: EmployerDescriptor,
    *,
    db: Executor | None = None,
) -> None:
    db = db or get_pool()
    await db.execute(
        "insert into employer_descriptors (account_id, company_canonical, descriptor) "
        "values ($1, $2, $3) "
        "on conflict (account_id, company_canonical) do update set "
        "descriptor = excluded.descriptor, updated_at = now()",
        account_id,
        company_canonical,
        _descriptor_to_mapping(descriptor),
    )


def _user_payload(*, company: str, industry: str, area: str, role_context: str) -> str:
    return (
        "Название компании (только для твоего рассуждения, НЕ для копирования в ответ): "
        f"{company}\n"
        f"Отрасль: {industry or '(не указана)'}\n"
        f"Регион: {area or '(не указан)'}\n"
        f"Роль/контекст задач кандидата в этой компании: {role_context or '(не указан)'}\n"
    )


async def _extract_descriptor(
    *,
    company: str,
    industry: str,
    area: str,
    role_context: str,
    llm: ports.LlmPort | None = None,
) -> EmployerDescriptor:
    port = llm or ports.llm()
    user = _user_payload(company=company, industry=industry, area=area, role_context=role_context)
    raw = await port.structured(
        FEATURE,
        schema=EmployerDescriptor,
        user=user,
        max_retries=1,
        tags=("profile", "employer_descriptor"),
    )
    if not isinstance(raw, EmployerDescriptor):  # pragma: no cover
        raise LlmError(f"employer_descriptor вернул неожиданный тип: {type(raw).__name__}")
    return raw


async def get_or_create_employer_descriptor(
    account_id: int,
    *,
    company: str,
    industry: str = "",
    area: str = "",
    role_context: str = "",
    db: Executor | None = None,
    llm: ports.LlmPort | None = None,
) -> EmployerDescriptor | None:
    """Кэш-или-создать дескриптор для `company`. Пустое название → `None`.

    Гвард против утечки имени (§2.8): если модель дважды подряд возвращает дескриптор,
    в котором встречается название компании — фолбэк без LLM (`_fallback_descriptor`),
    генерация письма не должна падать из-за одного капризного вызова (L-13: ремонт ≤1).
    """
    name = (company or "").strip()
    if not name:
        return None
    canonical = normalize_company_deterministic(name)
    if not canonical:
        return None

    cached = await load_descriptor(account_id, canonical, db=db)
    if cached is not None:
        return cached

    descriptor: EmployerDescriptor | None = None
    for _attempt in range(2):
        try:
            candidate = await _extract_descriptor(
                company=name, industry=industry, area=area, role_context=role_context, llm=llm
            )
        except LlmError as exc:
            event(
                logger,
                "LLM",
                "employer_descriptor: сбой генерации account_id=%s: %s",
                account_id,
                exc,
                level=logging.WARNING,
            )
            break
        if not _leaks_company_name(candidate, name, canonical):
            descriptor = candidate
            break
        event(
            logger,
            "LLM",
            "employer_descriptor: дескриптор содержит имя компании, повтор account_id=%s",
            account_id,
            level=logging.WARNING,
        )

    if descriptor is None:
        descriptor = _fallback_descriptor(industry)

    try:
        await _save_descriptor(account_id, canonical, descriptor, db=db)
    except Exception:
        logger.exception("employer_descriptor: не удалось сохранить account_id=%s", account_id)
    return descriptor


__all__ = [
    "FEATURE",
    "EmployerDescriptor",
    "get_or_create_employer_descriptor",
    "load_descriptor",
]
