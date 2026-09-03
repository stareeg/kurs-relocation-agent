"""Политика раскрытия и анонимизация резюме под международные исходящие письма (Э4.2).

Снижает случайную обнаружимость поиска второй работы/зарубежного контракта — не даёт
анонимность (комбинация стека, дат и проектов остаётся узнаваемой, см. докстринг
`anonymize_resume`). Настройка — `app_settings.disclosure_policy` (jsonb, без отдельной
таблицы), та же механика, что `telegram_prefs.py`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from core.domains.opportunities.companies.normalize import normalize_company_deterministic
from core.domains.profile.employer_descriptor import EmployerDescriptor
from core.domains.profile.model import Experience, ResumeData
from core.kernel.timezones import city_geo
from core.platform.db.pool import Executor
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

KEY_POLICY = "disclosure_policy"

_URL_RE = re.compile(r"https?://\S+|(?:www\.)\S+\.[a-z]{2,}\S*", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class DisclosurePolicy(BaseModel):
    """Что скрываем в исходящих артефактах. Дефолт — скрыть только текущее место."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    hide_current_employer: bool = True
    hide_all_employers: bool = False
    hide_public_links: bool = True
    coarse_dates: bool = False
    coarse_city: bool = False


DEFAULT_DISCLOSURE_POLICY = DisclosurePolicy()


def default_disclosure_policy_dict() -> dict[str, Any]:
    """Сериализованные дефолты для `default_app_settings_values`."""
    return DEFAULT_DISCLOSURE_POLICY.model_dump()


def policy_from_mapping(raw: Any) -> DisclosurePolicy:
    """Разобрать jsonb; нет / мусор → дефолты (частичные ключи мержатся)."""
    if not isinstance(raw, dict):
        return DisclosurePolicy()
    try:
        return DisclosurePolicy.model_validate(raw)
    except Exception:
        logger.debug("disclosure_policy: некорректные данные, использую дефолты: %r", raw)
        return DisclosurePolicy()


async def get_disclosure_policy(
    *, account_id: int | None, db: Executor | None = None
) -> DisclosurePolicy:
    """Текущая политика; нет строки / ошибка PG → дефолты. Без in-process кэша."""
    raw = await get_setting(KEY_POLICY, default=None, account_id=account_id, db=db)
    return policy_from_mapping(raw)


async def set_disclosure_policy(
    policy: DisclosurePolicy, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Записать политику целиком (частичный PATCH — на стороне API)."""
    await set_setting(KEY_POLICY, policy.model_dump(), account_id=account_id, db=db)


def current_employer_experience(data: ResumeData) -> Experience | None:
    """Первая запись опыта с `current=True` — то самое «текущее место»."""
    for exp in data.experience:
        if exp.current:
            return exp
    return None


def _strip_urls(text: str) -> str:
    return _URL_RE.sub("", text).strip()


def _coarse_period(exp: Experience) -> tuple[str, str]:
    """«Март 2024» → «2024». Год не находится - строка остаётся как есть (не выдумываем)."""

    def year_of(raw: str) -> str:
        match = _YEAR_RE.search(raw or "")
        return match.group(0) if match else raw

    return year_of(exp.start), ("" if exp.current else year_of(exp.end))


def _descriptor_text(descriptor: EmployerDescriptor | None, *, lang: str) -> str:
    if descriptor is None:
        return "текущее место работы" if lang == "ru" else "current employer"
    return descriptor.descriptor_en if lang == "en" else descriptor.descriptor_ru


def anonymize_resume(
    data: ResumeData,
    *,
    policy: DisclosurePolicy,
    descriptors: Mapping[str, EmployerDescriptor] | None = None,
    lang: str = "ru",
) -> ResumeData:
    """Копия резюме с обобщёнными фактами. Ничего не выдумывает: только убирает и обобщает.

    `descriptors` — готовые описания по `company_canonical` (см. `employer_descriptor.py`);
    отсутствующий дескриптор для скрываемой компании даёт нейтральную заглушку («текущее место
    работы» / «current employer»), а не выдумку.

    Снижает СЛУЧАЙНУЮ обнаружимость (рекрутер/коллега не наткнётся на резюме по названию
    компании), а не даёт анонимность — комбинация стека, дат и проектов остаётся узнаваемой.
    Это ограничение — продуктовая правда, не баг: обещать больше нельзя (§2 dual_employment
    plan, правило 6/7 по духу — не выдаём то, чего не гарантируем).
    """
    descriptors = descriptors or {}
    if not any(
        (
            policy.hide_current_employer,
            policy.hide_all_employers,
            policy.hide_public_links,
            policy.coarse_dates,
            policy.coarse_city,
        )
    ):
        return data

    new_experience: list[Experience] = []
    for exp in data.experience:
        updates: dict[str, Any] = {}
        hide_this = policy.hide_all_employers or (policy.hide_current_employer and exp.current)
        if hide_this and exp.company.strip():
            canonical = normalize_company_deterministic(exp.company)
            descriptor = descriptors.get(canonical)
            updates["company"] = _descriptor_text(descriptor, lang=lang)
            updates["company_url"] = ""
        if policy.coarse_dates:
            start, end = _coarse_period(exp)
            updates["start"] = start
            updates["end"] = end
        new_experience.append(exp.model_copy(update=updates) if updates else exp)

    personal_updates: dict[str, Any] = {}
    if policy.coarse_city and data.personal.city.strip():
        geo = city_geo(data.personal.city)
        if geo is not None:
            personal_updates["city"] = geo.country

    contacts_updates: dict[str, Any] = {}
    about = data.about
    if policy.hide_public_links:
        contacts_updates["site"] = ""
        contacts_updates["other"] = [_strip_urls(o) for o in data.contacts.other if _strip_urls(o)]
        about = _strip_urls(about)

    return data.model_copy(
        update={
            "experience": new_experience,
            "personal": data.personal.model_copy(update=personal_updates)
            if personal_updates
            else data.personal,
            "contacts": data.contacts.model_copy(update=contacts_updates)
            if contacts_updates
            else data.contacts,
            "about": about,
        }
    )


__all__ = [
    "KEY_POLICY",
    "DEFAULT_DISCLOSURE_POLICY",
    "DisclosurePolicy",
    "anonymize_resume",
    "current_employer_experience",
    "default_disclosure_policy_dict",
    "get_disclosure_policy",
    "policy_from_mapping",
    "set_disclosure_policy",
]
