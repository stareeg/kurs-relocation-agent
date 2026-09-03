"""Быстрый экран «HR-контакты» в боте: последние 5–8, без пагинации.

Текст + кнопки-deeplink на `/chat?vacancy=` в вебе. Данные — `list_recent_hr_contacts`
(треды + enrichment). Рендер чистый — удобно тестировать без PG.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.services.hr_card import hr_contact_display
from bot_app.utils import esc
from core.domains.pipeline.hr_threads import RecentHrContact, list_recent_hr_contacts

_DEFAULT_LIMIT = 8


@dataclass(frozen=True)
class HrContactsScreen:
    """Готовый ответ бота: HTML-текст + опциональная клавиатура."""

    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def days_since(last_at: datetime | None, *, now: datetime | None = None) -> int | None:
    """Целые сутки с последнего контакта; None если даты нет."""
    at = _aware(last_at)
    if at is None:
        return None
    base = _aware(now) or datetime.now(UTC)
    return max(0, int((base - at).total_seconds() // 86400))


def _ago_label(days: int | None) -> str:
    if days is None:
        return "дата ?"
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "1д"
    return f"{days}д"


def contact_label(row: RecentHrContact) -> str:
    """Имя или @/email/tel для строки списка."""
    name = (row.contact_name or "").strip()
    if name:
        return name
    link = (row.hr_link or "").strip()
    if link:
        return hr_contact_display(link)
    return "без контакта"


def company_label(row: RecentHrContact) -> str:
    return (row.company or "").strip() or "без компании"


def _https_button(text: str, url: str) -> InlineKeyboardButton | None:
    url = (url or "").strip()
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, url=url)
    return None


def _chat_url(web_url: str, vacancy_id: str) -> str:
    return f"{(web_url or '').rstrip('/')}/chat?vacancy={vacancy_id}"


def format_hr_contacts_screen(
    rows: list[RecentHrContact],
    *,
    web_url: str = "",
    now: datetime | None = None,
) -> HrContactsScreen:
    """Один экран: список + URL-кнопки на треды (если web https)."""
    if not rows:
        return HrContactsScreen(text="<b>HR-контакты</b>\nПока пусто — пересылай переписку.")

    lines = ["<b>HR-контакты</b>"]
    buttons: list[list[InlineKeyboardButton]] = []

    for row in rows:
        who = contact_label(row)
        company = company_label(row)
        ago = _ago_label(days_since(row.last_at, now=now))
        lines.append(f"• {esc(who)} · {esc(company)} · {esc(ago)}")

        btn_label = company if company != "без компании" else who
        if len(btn_label) > 28:
            btn_label = btn_label[:27].rstrip() + "…"
        btn = _https_button(btn_label, _chat_url(web_url, row.vacancy_id))
        if btn:
            buttons.append([btn])

    markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    return HrContactsScreen(text="\n".join(lines), reply_markup=markup)


async def build_hr_contacts_screen(
    *,
    account_id: int,
    web_url: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> HrContactsScreen:
    """Загрузить из PG и отформатировать. PG-down → пустой экран с подсказкой."""
    try:
        rows = await list_recent_hr_contacts(limit=limit, account_id=account_id)
    except Exception:  # noqa: BLE001 — экран best-effort
        return HrContactsScreen(
            text="<b>HR-контакты</b>\nНе удалось загрузить список. Попробуй позже."
        )
    return format_hr_contacts_screen(rows, web_url=web_url)


__all__ = [
    "HrContactsScreen",
    "build_hr_contacts_screen",
    "contact_label",
    "days_since",
    "format_hr_contacts_screen",
]
