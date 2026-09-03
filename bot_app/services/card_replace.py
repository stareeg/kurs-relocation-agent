"""Повторная карточка той же vacancy_id не плодится.

Найти прежние ``kind=card`` в реестре → edit (текст, <48ч) или delete + новая отправка.
PNG-стиль: ``send_photo`` + короткая подпись; сбой рендера → текстовый фолбэк.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import Message

from bot_app.services.vacancy_card import (
    build_card_caption,
    build_vacancy_actions_keyboard,
    build_vacancy_card_text,
)
from bot_app.storage.message_registry import (
    KIND_CARD,
    TrackedMessage,
    pop_by_vacancy,
    track,
)
from bot_app.telegram_send import safe_send, safe_send_photo
from core.config import current_account_id
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.models import ScoreResult
from core.domains.profile.telegram_prefs import CardStyle, get_telegram_prefs
from core.platform.repo.accounts import resolve_default_account_id

logger = logging.getLogger(__name__)

# Окно, в котором предпочитаем edit вместо delete+send (план TB-4.5).
_CARD_EDIT_WINDOW = timedelta(hours=48)


def can_edit_card(
    prev: TrackedMessage,
    *,
    card_style: CardStyle,
    now: datetime | None = None,
) -> bool:
    """Edit только для текстового стиля и сообщения младше 48ч."""
    if card_style != "text":
        return False
    if prev.created_at is None:
        return False
    created = prev.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    ref = now or datetime.now(UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return (ref - created) < _CARD_EDIT_WINDOW


async def _delete_tracked(bot: Bot, items: list[TrackedMessage]) -> None:
    for item in items:
        try:
            await bot.delete_message(item.chat_id, item.message_id)
        except Exception as exc:  # noqa: BLE001 — >48ч / уже удалено
            logger.debug(
                "card_replace delete_message failed chat=%s msg=%s: %s",
                item.chat_id,
                item.message_id,
                exc,
            )


async def _resolve_card_style() -> CardStyle:
    try:
        # M8 (plans/multitenancy_gaps_2026_08_06.md §3.13): `current_account_id()` — вызывающий
        # этого апдейта (bot-middleware) или получатель этой tg_push-задачи (worker выставляет
        # его из task.account_id, core/app/background.py) — сначала он, владелец только для
        # путей вне такого контекста. Раньше падало прямо на владельца, и стиль карточки друга
        # определялся настройками владельца.
        account_id = current_account_id() or await resolve_default_account_id()
        return (await get_telegram_prefs(account_id=account_id)).card_style
    except Exception as exc:  # noqa: BLE001 — prefs down → text/edit по умолчанию
        logger.debug("card_replace prefs read failed: %s", exc)
        return "text"


async def send_or_replace_card(
    bot: Bot,
    chat_id: int,
    *,
    vacancy_id: str,
    text: str,
    reply_markup: Any = None,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
    photo: bytes | None = None,
) -> Message | None:
    """Отправить карточку; прежние по vacancy_id — edit или удалить.

    ``photo`` — PNG: тогда ``text`` идёт в caption, edit не используется.
    Без vacancy_id — обычный ``safe_send`` / ``safe_send_photo`` без pop.
    """
    vid = (vacancy_id or "").strip()
    card_style: CardStyle = "image" if photo else "text"

    if not vid:
        if photo is not None:
            return await safe_send_photo(
                bot,
                chat_id,
                photo,
                caption=text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                track_kind=KIND_CARD,
            )
        return await safe_send(
            bot,
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
            track_kind=KIND_CARD,
        )

    previous = await pop_by_vacancy(chat_id, KIND_CARD, vid)
    primary = previous[0] if previous else None
    extras = previous[1:] if len(previous) > 1 else []
    if extras:
        await _delete_tracked(bot, extras)

    # Для photo-ветки стиль уже image; иначе читаем prefs (edit vs delete).
    if photo is None:
        card_style = await _resolve_card_style()

    if photo is None and primary is not None and can_edit_card(primary, card_style=card_style):
        try:
            edited = await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=primary.message_id,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
            await track(chat_id, primary.message_id, KIND_CARD, vacancy_id=vid)
            return edited if isinstance(edited, Message) else None
        except Exception as exc:  # noqa: BLE001 — падаем в delete+send
            logger.debug(
                "card_replace edit failed chat=%s msg=%s: %s",
                chat_id,
                primary.message_id,
                exc,
            )
            await _delete_tracked(bot, [primary])
    elif primary is not None:
        await _delete_tracked(bot, [primary])

    if photo is not None:
        return await safe_send_photo(
            bot,
            chat_id,
            photo,
            caption=text,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            track_kind=KIND_CARD,
            vacancy_id=vid,
        )

    return await safe_send(
        bot,
        chat_id,
        text,
        reply_to_message_id=reply_to_message_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        reply_markup=reply_markup,
        track_kind=KIND_CARD,
        vacancy_id=vid,
    )


async def send_or_replace_score_card(
    bot: Bot,
    chat_id: int,
    *,
    job: Job,
    score: ScoreResult,
    header: str,
    reply_to_message_id: int | None = None,
    reply_markup: Any = None,
) -> Message | None:
    """Скоринг → PNG или текст по ``telegram_prefs.card_style``.

    Сбой рендера PNG → WARNING и текстовая карточка; бот не падает.
    """
    markup = reply_markup if reply_markup is not None else build_vacancy_actions_keyboard(job)
    text_card = build_vacancy_card_text(job, score, header)
    caption = build_card_caption(job, score)
    vid = job.vacancy_id or ""

    card_style = await _resolve_card_style()
    photo: bytes | None = None
    if card_style == "image":
        try:
            from bot_app.services.card_image import render_score_card

            photo = render_score_card(job, score)
        except Exception:
            logger.warning(
                "card_image render failed vacancy_id=%s, fallback to text",
                vid or "—",
                exc_info=True,
            )
            photo = None

    if photo is not None:
        return await send_or_replace_card(
            bot,
            chat_id,
            vacancy_id=vid,
            text=caption,
            photo=photo,
            reply_to_message_id=reply_to_message_id,
            parse_mode=None,
            reply_markup=markup,
        )

    return await send_or_replace_card(
        bot,
        chat_id,
        vacancy_id=vid,
        text=text_card,
        reply_to_message_id=reply_to_message_id,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=markup,
    )


__all__ = [
    "can_edit_card",
    "send_or_replace_card",
    "send_or_replace_score_card",
]
