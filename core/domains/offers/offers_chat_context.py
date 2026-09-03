"""Живой контекст чата вкладки «Офферы»: собирается на каждый запрос, не кэшируется.

Агент видит актуальные карточки (зарплата, налоги, формат, дедлайн, статус, приоритет) и
критерии поиска кандидата — после правки оффера следующий вопрос уже с новыми цифрами.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from core.domains.offers.bonus import BONUS_KIND_RU, offer_bonus_types
from core.domains.offers.store import Offer, load_all_offers
from core.domains.profile import SearchProfile, derive_search_profile, read_resume_data_for_account

logger = logging.getLogger(__name__)

_FACTS_TIMEOUT_S = 8.0

_STATUS_RU = {"thinking": "думаю", "accepted": "принят", "declined": "отклонён"}
_FORMAT_RU = {
    "remote": "удалёнка",
    "hybrid": "гибрид",
    "office": "офис",
    "currency": "валютная удалёнка",
    "unknown": "не указан",
}
_TAX_RU = {"gross": "до вычета", "net": "на руки"}
_CONTRACT_RU = {
    "employment": "трудовой",
    "gph": "ГПХ",
    "ip": "ИП",
    "self_employed": "самозанятый",
}


def _fmt_money(amount: int | None, currency: str, period: str) -> str:
    if amount is None:
        return "не указан"
    per = "мес" if period == "month" else "год"
    return f"{amount:,}".replace(",", " ") + f" {currency}/{per}"


def _bonus_line(offer: Offer) -> str:
    types = offer_bonus_types(offer.bonus_types, offer.bonus_type)
    if not types:
        return "премия: нет"
    bits: list[str] = []
    for kind in types:
        label = BONUS_KIND_RU.get(kind, kind)
        if kind == "annual" and offer.annual_bonus_pct:
            bits.append(f"{label} {offer.annual_bonus_pct}% от года")
        elif kind == "quarterly" and offer.quarterly_bonus_pct:
            bits.append(f"{label} {offer.quarterly_bonus_pct}% от квартала")
        else:
            bits.append(label)
    line = "премия: " + ", ".join(bits)
    if "kpi" in types and offer.bonus.strip():
        line += f" ({offer.bonus.strip()})"
    return line


def _deadline_note(offer: Offer, *, now: datetime) -> str:
    if offer.deadline is None:
        return "дедлайна нет"
    dl = offer.deadline if offer.deadline.tzinfo is not None else offer.deadline.replace(tzinfo=UTC)
    days = (dl.date() - now.date()).days
    if days < 0:
        return "дедлайн прошёл"
    if days == 0:
        return "дедлайн сегодня"
    return f"осталось {days} дн. (до {dl.strftime('%d.%m.%Y')})"


def format_offer_block(offer: Offer, *, now: datetime | None = None) -> str:
    """Один оффер — блок фактов для промпта. Чистая, тестируется без БД."""
    now = now or datetime.now(UTC)
    office = ""
    if offer.work_format == "hybrid" and offer.office_days_per_week is not None:
        office = f", {offer.office_days_per_week} дн. в офисе"
    loc = offer.location.strip()
    country = offer.location_country.strip()
    place = ", ".join(p for p in (loc, country) if p)
    prio = f"приоритет {offer.priority}" if offer.priority is not None else "приоритет не задан"
    lines = [
        f"## {offer.company or 'компания не указана'} — {offer.position or 'должность не указана'}",
        f"vacancy_id: {offer.vacancy_id}; статус: {_STATUS_RU.get(offer.status, offer.status)}; {prio}",
        f"оклад: {_fmt_money(offer.base_salary, offer.base_salary_currency or 'RUB', offer.base_salary_period or 'month')}"
        f" ({_TAX_RU.get(offer.base_salary_tax_basis, offer.base_salary_tax_basis)})",
        f"формат: {_FORMAT_RU.get(offer.work_format, offer.work_format)}{office}",
        f"договор: {_CONTRACT_RU.get(offer.contract_type, offer.contract_type)}",
        _bonus_line(offer),
    ]
    if offer.signon:
        lines.append(f"welcome-бонус: {offer.signon:,} ₽".replace(",", " "))
    if offer.equity.strip():
        lines.append(f"акции: {offer.equity.strip()}")
    if offer.vacation_days is not None:
        lines.append(f"отпуск: {offer.vacation_days} дн.")
    if place:
        lines.append(f"локация: {place}")
    lines.append(_deadline_note(offer, now=now))
    if offer.notes.strip():
        lines.append(f"заметки: {offer.notes.strip()}")
    if offer.negotiation and isinstance(offer.negotiation, dict):
        draft = str(offer.negotiation.get("draft_message") or "").strip()
        args = offer.negotiation.get("arguments") or []
        if draft or args:
            lines.append("сохранённый бриф торга:")
            if draft:
                lines.append(draft)
            if isinstance(args, list):
                for arg in args:
                    if not isinstance(arg, dict):
                        continue
                    fact = str(arg.get("fact") or "").strip()
                    wording = str(arg.get("wording") or "").strip()
                    if fact or wording:
                        lines.append(f"- {fact}" + (f" → {wording}" if wording else ""))
    return "\n".join(lines)


def format_profile_block(profile: SearchProfile | None) -> str:
    """Критерии поиска кандидата — чтобы агент сравнивал офферы с целью, не с выдумкой."""
    if profile is None or not profile.is_filled:
        return "Критерии поиска: резюме ещё не заполнено — не выдумывай цель."
    formats = []
    if profile.allows_remote:
        formats.append("удалёнка")
    if profile.allows_hybrid:
        formats.append("гибрид")
    if profile.allows_office:
        formats.append("офис")
    grades = ", ".join(profile.target_grades) or "не указаны"
    salary = "не указана"
    if profile.salary_min:
        amount = f"{profile.salary_min:,}".replace(",", " ")
        salary = f"{amount} {profile.salary_currency} ({profile.salary_basis})"
    return (
        f"Цель кандидата: {profile.title or 'должность не указана'}; "
        f"грейды {grades}; зарплата от {salary}; "
        f"форматы: {', '.join(formats) or 'не указаны'}."
    )


def build_offers_chat_tail(
    offers: list[Offer],
    profile: SearchProfile | None,
    *,
    now: datetime | None = None,
) -> str:
    """dynamic_tail чата по офферам. Чистая — тестируется без БД."""
    now = now or datetime.now(UTC)
    parts = [format_profile_block(profile)]
    if not offers:
        parts.append("Офферов пока нет. Не выдумывай компании и суммы.")
        return "\n\n".join(parts)
    parts.append(f"Офферов в карточках: {len(offers)} (порядок = приоритет владельца).")
    parts.extend(format_offer_block(o, now=now) for o in offers)
    return "\n\n".join(parts)


async def gather_offers_chat_tail(*, account_id: int) -> str:
    """Собрать актуальный хвост для LLM. Best-effort: сбой → пустая строка, чат не падает."""
    try:
        resume = await asyncio.wait_for(
            read_resume_data_for_account(account_id),
            timeout=_FACTS_TIMEOUT_S,
        )
        profile = derive_search_profile(resume) if resume is not None else None
    except Exception as exc:  # noqa: BLE001 — профиль best-effort
        logger.debug("offers_chat: профиль недоступен: %s", exc)
        profile = None
    try:
        offers = await asyncio.wait_for(
            load_all_offers(account_id=account_id),
            timeout=_FACTS_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — офферы best-effort
        logger.debug("offers_chat: офферы недоступны: %s", exc)
        offers = []
    return build_offers_chat_tail(offers, profile)


__all__ = [
    "build_offers_chat_tail",
    "format_offer_block",
    "format_profile_block",
    "gather_offers_chat_tail",
]
