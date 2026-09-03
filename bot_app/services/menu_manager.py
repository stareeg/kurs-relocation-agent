"""Адаптивное inline-меню бота — одно активное сообщение на чат.

`refresh` обновляет существующее menu-сообщение (edit-in-place); если редактировать нечего
или не вышло (старое/удалено) — удаляет прежние и шлёт новое с `track_kind=menu`. Это
гарантирует, что активное меню всегда одно: пользователь не наткнётся на кнопки из
протухшего прошлого меню. Подписи без декоративных эмодзи.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot_app.storage.message_registry import KIND_MENU, pop_kind, track
from bot_app.telegram_send import safe_send

logger = logging.getLogger(__name__)

MenuKind = Literal["idle", "after_score", "after_hr", "member_home"]

# Callback'и меню. Хендлеры — bot_app/handlers/menu.py.
CB_TOP_TODAY = "menu:top_today"
CB_CLEANUP_CHAT = "menu:cleanup_chat"
CB_HR_CONTACTS = "menu:hr_contacts"
# AUTH-1: токен входа в веб — главная кнопка, доступна всегда (в т.ч. до привязки владельца).
CB_AUTH_TOKEN = "menu:auth_token"
# «Привязать другой Telegram»: привязать этот Telegram как secondary-identity уже
# существующего аккаунта по его токену (bot_app.services.account_link) — вместо нового.
CB_ADD_ACCOUNT = "menu:add_account"


@dataclass(frozen=True)
class BatchStats:
    """Сводка батча скоринга; для подписи after_score."""

    total: int = 0
    strong: int = 0
    apply: int = 0
    skip: int = 0


@dataclass(frozen=True)
class MenuContext:
    """Контекст «живого» меню: kind + опциональные поля сценария."""

    kind: MenuKind
    vacancy_id: str | None = None
    batch_stats: BatchStats | None = None


def idle() -> MenuContext:
    return MenuContext(kind="idle")


def after_score(
    vacancy_id: str = "",
    *,
    batch_stats: BatchStats | None = None,
) -> MenuContext:
    return MenuContext(
        kind="after_score",
        vacancy_id=vacancy_id or None,
        batch_stats=batch_stats,
    )


def after_hr(vacancy_id: str = "") -> MenuContext:
    return MenuContext(kind="after_hr", vacancy_id=vacancy_id or None)


def member_home() -> MenuContext:
    """Меню member-аккаунта (Этап 5): то, что реально работает для любого активного
    аккаунта — карточки вакансий, токен входа, привязка второго Telegram.

    Ключа OpenRouter здесь больше нет (2026-08-25): заявка и выдача переехали в веб —
    «Аккаунт» у пользователя, админ-панель у оператора."""
    return MenuContext(kind="member_home")


def _https_button(text: str, url: str) -> InlineKeyboardButton | None:
    """Только https: Telegram отвергает localhost/http у inline-URL."""
    u = (url or "").strip()
    if u.startswith("https://"):
        return InlineKeyboardButton(text=text, url=u)
    return None


def _chat_url(web_url: str, vacancy_id: str) -> str:
    return f"{(web_url or '').rstrip('/')}/chat?vacancy={vacancy_id}"


def menu_text(ctx: MenuContext) -> str:
    """Короткая подпись над кнопками (без эмодзи)."""
    if ctx.kind == "after_score" and ctx.batch_stats is not None and ctx.batch_stats.total > 0:
        s = ctx.batch_stats
        return f"Оценено {s.total}: сильных {s.strong}, подать {s.apply}, мимо {s.skip}"
    if ctx.kind == "after_hr":
        return "HR разобран"
    return "Меню"


def build_menu(ctx: MenuContext, *, web_url: str = "") -> InlineKeyboardMarkup:
    """Ряды кнопок под контекст. Подписи без эмодзи.

    Кнопки «Веб» здесь больше нет: ссылка на сайт живёт в закреплённом сообщении (см.
    `menu.send_site_pin`), чтобы не дублировать навигацию в каждом меню.

    «Привязать другой Telegram» — вторичный ряд: это не шаг онбординга, а редкий
    сценарий (второй Telegram у уже существующего аккаунта). Рядом с токеном путает
    новичков («куда вставлять токен?»).
    """
    rows: list[list[InlineKeyboardButton]] = []

    if ctx.kind in ("idle", "member_home"):
        rows.append([InlineKeyboardButton(text="Токен авторизации", callback_data=CB_AUTH_TOKEN)])
        rows.append(
            [
                InlineKeyboardButton(
                    text="Привязать другой Telegram",
                    callback_data=CB_ADD_ACCOUNT,
                )
            ]
        )

    elif ctx.kind == "after_score":
        rows.append(
            [
                InlineKeyboardButton(text="Топ за сегодня", callback_data=CB_TOP_TODAY),
                InlineKeyboardButton(text="Подчистить чат", callback_data=CB_CLEANUP_CHAT),
            ]
        )

    elif ctx.kind == "after_hr":
        row: list[InlineKeyboardButton] = []
        if ctx.vacancy_id:
            thread = _https_button("Открыть тред", _chat_url(web_url, ctx.vacancy_id))
            if thread:
                row.append(thread)
        row.append(InlineKeyboardButton(text="HR-контакты", callback_data=CB_HR_CONTACTS))
        rows.append(row)

    else:
        # Неожиданный kind — безопасный idle (не роняем refresh).
        return build_menu(idle(), web_url=web_url)

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _delete_tracked(bot: Bot, chat_id: int, items) -> None:
    for item in items:
        try:
            await bot.delete_message(chat_id, item.message_id)
        except Exception as exc:  # noqa: BLE001 — >48ч / уже удалено / нет прав
            logger.debug(
                "menu delete_message failed chat=%s msg=%s: %s",
                chat_id,
                item.message_id,
                exc,
            )


async def refresh(
    bot: Bot,
    chat_id: int,
    ctx: MenuContext,
    *,
    web_url: str | None = None,
) -> Message | None:
    """Обновить единственное меню чата: edit-in-place, иначе delete+send.

    Гарантия «одно активное меню»: сначала пробуем отредактировать уже отслеженное
    menu-сообщение (новейшее). Если редактировать нечего или Telegram не дал (старое,
    удалено, другое содержимое) — удаляем все прошлые menu и шлём новое.
    """
    if web_url is None:
        from bot_app.config import get_bot_settings

        web_url = get_bot_settings().web_url

    text = menu_text(ctx)
    markup = build_menu(ctx, web_url=web_url)

    previous = await pop_kind(chat_id, KIND_MENU)
    if previous:
        # Новейшее меню — кандидат на edit; остальные сразу удаляем.
        previous.sort(key=lambda t: t.message_id, reverse=True)
        primary, extras = previous[0], previous[1:]
        if extras:
            await _delete_tracked(bot, chat_id, extras)
        try:
            edited = await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=primary.message_id,
                parse_mode="HTML",
                reply_markup=markup,
            )
            if isinstance(edited, Message):
                await track(chat_id, primary.message_id, KIND_MENU)
                return edited
        except Exception as exc:  # noqa: BLE001 — не вышло edit → delete+send ниже
            logger.debug(
                "menu edit failed chat=%s msg=%s: %s",
                chat_id,
                primary.message_id,
                exc,
            )
        await _delete_tracked(bot, chat_id, [primary])

    return await safe_send(
        bot,
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=markup,
        track_kind=KIND_MENU,
    )


async def show_menu(
    bot: Bot | None,
    chat_id: int,
    ctx: MenuContext | None = None,
    *,
    web_url: str | None = None,
) -> Message | None:
    """Единая точка вызова в конце сценария: refresh с ctx или idle.

    Не размазывай `refresh(...)` по хендлерам — зови `show_menu`.
    """
    if bot is None:
        return None
    return await refresh(bot, chat_id, ctx if ctx is not None else idle(), web_url=web_url)


async def show_menu_for(
    message: Message,
    ctx: MenuContext | None = None,
    *,
    web_url: str | None = None,
) -> Message | None:
    """show_menu из Message (chat_id + bot)."""
    return await show_menu(message.bot, message.chat.id, ctx, web_url=web_url)


def auth_token_kb() -> InlineKeyboardMarkup:
    """Первый контакт (`/start` без аккаунта): только выдача токена входа.

    «Привязать другой Telegram» сюда не кладём — новичок ещё не знает про второй
    Telegram и воспринимает вторую кнопку как обязательный шаг онбординга.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Токен авторизации", callback_data=CB_AUTH_TOKEN)],
        ]
    )


__all__ = [
    "CB_ADD_ACCOUNT",
    "CB_AUTH_TOKEN",
    "CB_CLEANUP_CHAT",
    "CB_HR_CONTACTS",
    "CB_TOP_TODAY",
    "BatchStats",
    "MenuContext",
    "MenuKind",
    "after_hr",
    "after_score",
    "auth_token_kb",
    "build_menu",
    "idle",
    "member_home",
    "menu_text",
    "refresh",
    "show_menu",
    "show_menu_for",
]
