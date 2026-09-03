"""Нормализация идентификатора HR для привязки к вакансиям (порт `bot.utils.hr_identity`, S11).

Один HR (`tg:@user` / `mail:...` / `tel:+...` / `name:...`) — много вакансий. Чистые regex без БД.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import Message

_TG_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?t\.me/(?:joinchat/)?([a-zA-Z0-9_]{4,32})",
    re.I,
)
_TG_AT_RE = re.compile(r"(?<![\w/])@([a-zA-Z][a-zA-Z0-9_]{4,31})\b")
_TG_HINT_RE = re.compile(
    r"\[HR\s+Telegram:\s*@([a-zA-Z0-9_]{4,32})\s*\]",
    re.I,
)
_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b",
)
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_HR_TAG_RE = re.compile(r"\bhr[_\s-]?link:\s*(\S+)", re.I)


def normalize_hr_link(raw: str) -> str:
    """Канонический ключ HR: tg:@user | mail:email | tel:+79... | name:Имя Фамилия."""
    s = (raw or "").strip()
    if not s:
        return ""

    m = _HR_TAG_RE.search(s)
    if m:
        s = m.group(1).strip()

    m = _TG_HINT_RE.search(s)
    if m:
        return f"tg:@{m.group(1).lower()}"

    m = _TG_URL_RE.search(s)
    if m:
        user = m.group(1).lower()
        if user not in ("joinchat", "share", "addstickers"):
            return f"tg:@{user}"

    m = _TG_AT_RE.search(s)
    if m:
        user = m.group(1).lower()
        if user not in ("gmail", "mail", "yandex", "hh"):
            return f"tg:@{user}"

    m = _EMAIL_RE.search(s)
    if m:
        return f"mail:{m.group(1).lower()}"

    digits = re.sub(r"\D", "", s)
    if len(digits) >= 10 and _PHONE_RE.search(s):
        return f"tel:+{digits[-11:] if len(digits) > 11 else digits}"

    if s.lower().startswith(("tg:", "mail:", "tel:", "name:")):
        return s

    cleaned = re.sub(r"\s+", " ", s).strip()
    if 2 <= len(cleaned) <= 80:
        return f"name:{cleaned}"
    return ""


def extract_hr_link_from_text(text: str) -> str:
    """Извлечь ссылку/контакт HR из текста переписки."""
    if not text:
        return ""

    for pattern in (_TG_HINT_RE, _TG_URL_RE, _TG_AT_RE, _EMAIL_RE):
        m = pattern.search(text)
        if m:
            return normalize_hr_link(m.group(0) if pattern != _TG_AT_RE else f"@{m.group(1)}")

    m = re.search(
        r"(?:рекрут[её]р|hr|эйч[\s-]?ар)\s*[:\-—]?\s*"
        r"([А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)?)",
        text,
        re.I,
    )
    if m:
        return normalize_hr_link(m.group(1))

    return ""


def merge_hr_link(*candidates: str) -> str:
    for c in candidates:
        key = normalize_hr_link(c)
        if key:
            return key
    return ""


def telegram_forward_hr_hint(message: Message) -> str:
    """Контакт HR из метаданных пересланного Telegram-сообщения."""
    parts: list[str] = []

    user = getattr(message, "forward_from", None)
    if user:
        if getattr(user, "username", None):
            parts.append(f"tg:@{user.username}")
        elif getattr(user, "first_name", None):
            name = user.first_name
            if getattr(user, "last_name", None):
                name = f"{name} {user.last_name}"
            parts.append(normalize_hr_link(name))

    if not parts and getattr(message, "forward_sender_name", None):
        parts.append(normalize_hr_link(message.forward_sender_name or ""))

    chat = getattr(message, "forward_from_chat", None)
    if chat and getattr(chat, "username", None):
        parts.append(f"tg:@{chat.username}")

    return merge_hr_link(*parts)


def hr_link_display(hr_link: str) -> str:
    """Человекочитаемая подпись для UI."""
    if not hr_link:
        return ""
    if hr_link.startswith("tg:@") and not hr_link.startswith("tg:@http"):
        return f"https://t.me/{hr_link[4:]}"
    if hr_link.startswith("mail:"):
        return hr_link[5:]
    return hr_link
